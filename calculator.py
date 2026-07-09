"""
Reimplementasi logika perhitungan sheet "Final Calculation" (FTE Calculator).

Alur rumus (per unit / kategori equipment terpilih), mengikuti Final Calculation:

    G   = Target Physical Availability (PA%)              -> input user
    H   = 1 - G                                             (Breakdown %)
    I   = 24 * H                                            (Breakdown Hours/hari)
    J   = 12 - LostTime(Site) - (Jarak/40)                  (EMHD, jam efektif/hari)

    FTE_Mechanic    = ((I/J) * LoadMechanic    * Populasi * RatioShift(Site)) / CF * RACI_Mechanic
    FTE_Electrician = ((I/J) * LoadElectrican  * Populasi * RatioShift(Site)) / CF * RACI_Electrician
    FTE_Welder      = ((I/J) * LoadWelder      * Populasi * RatioShift(Site)) / CF * RACI_Welder

    (CF = Competency Factor, input user)

Kemudian setiap FTE role di-split ke M1/M2/M3 berdasarkan rasio dari BACKEND:
    Mechanic    : M1 = FTE*a, M2 = FTE*b, M3 = FTE*c      (a+b+c = 1, mis. 0.2/0.3/0.5)
    Electrician : M1 = FTE*a, M2 = FTE*b, M3 = 0          (mis. 3/7, 4/7)
    Welder      : M1 = FTE*a, M2 = FTE*b, M3 = 0          (mis. 3/7, 4/7)

── SKEMA ROUND (PENTING — disamakan persis dengan sheet "Final Calculation") ──
Di Excel, baris per-unit (baris 10:46, kolom P:AB) TIDAK PERNAH dibulatkan --
nilainya tetap desimal mentah (raw). Pembulatan HANYA terjadi SATU KALI, di
baris ringkasan "Summary Manpower" (baris 47), dengan formula:

    P47 = ROUND(SUM(P9:P46), 0)   -> jumlahkan dulu SEMUA unit (raw), baru ROUND
    Q47 = ROUND(SUM(Q9:Q46), 0)
    R47 = ROUND(SUM(R9:R46), 0)
    ... dst untuk T/U (Welder) dan W/X (Electrician)

Baris "Total" (AH10 = SUM(AE10:AG10)) lalu menjumlahkan M1+M2+M3 yang SUDAH
dibulatkan itu.

Ini BUKAN skema "round per-unit lalu jumlahkan" (round-then-sum) — itu keliru
karena round(a) + round(b) != round(a+b) secara umum, dan itulah sumber
perbedaan hasil antara versi lama app ini dengan sheet Excel aslinya.

Jadi di modul ini:
  - `compute_fte_raw()`  -> hasil PER UNIT, TANPA pembulatan (persis baris 10:46).
  - `aggregate_units()`  -> jumlahkan raw dari semua unit dulu, BARU dibulatkan
                             SATU KALI (persis baris 47 / Summary Manpower).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import List

from config import BASE_MECHANIC_HOURS, HOURS_PER_DAY, TRAVEL_DIVISOR, COST_RATE, ROLES, MONTH_COLS
from data_loader import BackendData


def excel_round(value: float, digits: int = 0) -> float:
    """Round-half-up seperti fungsi ROUND() Excel (bukan banker's rounding Python)."""
    if value is None:
        return 0.0
    q = Decimal("1") if digits == 0 else Decimal("1." + "0" * digits)
    result = Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)
    return float(result)


@dataclass
class FTEInput:
    site: str
    competency_factor: float          # D3, misal 0.6
    jarak_km: float                   # D4
    sub_category: str                 # Sub Section, mis. "Big Exca"
    jenis_unit: str                   # Attribute terkait sub_category (informasi/konfirmasi)
    pa_percent: float                 # 1-100, Target Physical Availability
    populasi: float = 1.0             # Equipment Population (tidak ada di form asal, default 1 unit)


class CalculationError(RuntimeError):
    pass


def compute_fte_raw(inputs: FTEInput, backend: BackendData) -> dict:
    """Hitung FTE untuk SATU unit/baris, TANPA pembulatan sama sekali —
    persis nilai mentah di baris 10:46 pada sheet 'Final Calculation'.
    Jangan bulatkan hasil fungsi ini sebelum dijumlahkan lintas unit; gunakan
    `aggregate_units()` untuk itu, supaya skema round-nya identik dengan Excel
    (ROUND(SUM(...)) di level total, bukan round per-unit).
    """
    if inputs.sub_category not in backend.load_factor.index:
        raise CalculationError(f"Sub Category '{inputs.sub_category}' tidak ditemukan di BACKEND.")
    if inputs.site not in backend.ratio_shift or inputs.site not in backend.lost_time:
        raise CalculationError(f"Site '{inputs.site}' tidak memiliki data Ratio Shift / Lost Time di BACKEND.")
    if inputs.competency_factor <= 0:
        raise CalculationError("Competency Factor harus lebih besar dari 0.")

    row = backend.load_factor.loc[inputs.sub_category]
    load_mechanic = row["Load Mechanic"]
    load_electrican = row["Load Electrican"]
    load_welder = row["Load Welder"]

    ratio_shift = backend.ratio_shift[inputs.site]
    lost_time = backend.lost_time[inputs.site]

    pa = max(1.0, min(100.0, inputs.pa_percent)) / 100.0
    breakdown_pct = 1 - pa                       # H
    breakdown_hours = HOURS_PER_DAY * breakdown_pct  # I
    emhd = BASE_MECHANIC_HOURS - lost_time - (inputs.jarak_km / TRAVEL_DIVISOR)  # J

    if emhd <= 0:
        raise CalculationError(
            "EMHD (Effective Mechanic Hours a Day) <= 0. "
            "Periksa kembali Lost Time & Jarak Area Kerja."
        )

    base_factor = (breakdown_hours / emhd) * inputs.populasi * ratio_shift / inputs.competency_factor

    fte_mechanic = base_factor * load_mechanic * backend.raci["Mechanic"]
    fte_electric = base_factor * load_electrican * backend.raci["Electric"]
    fte_welder = base_factor * load_welder * backend.raci["Welder"]

    m_a, m_b, m_c = backend.split_mechanic
    e_a, e_b = backend.split_electrician
    w_a, w_b = backend.split_welder

    # Raw = TIDAK dibulatkan (sama seperti kolom P:X baris 10:46 di Excel)
    raw = {
        "Mechanic": {
            "M1": fte_mechanic * m_a,
            "M2": fte_mechanic * m_b,
            "M3": fte_mechanic * m_c,
        },
        "Electric": {
            "M1": fte_electric * e_a,
            "M2": fte_electric * e_b,
            "M3": 0.0,
        },
        "Welder": {
            "M1": fte_welder * w_a,
            "M2": fte_welder * w_b,
            "M3": 0.0,
        },
    }
    for role in ROLES:
        raw[role]["Tot"] = sum(raw[role][m] for m in MONTH_COLS)

    total_row = {col: sum(raw[role][col] for role in ROLES) for col in MONTH_COLS}
    total_row["Tot"] = sum(total_row[m] for m in MONTH_COLS)
    raw["Total"] = total_row

    return {
        "raw": raw,
        "intermediate": {
            "Target PA (%)": inputs.pa_percent,
            "Breakdown % (H)": breakdown_pct,
            "Breakdown Hours/hari (I)": breakdown_hours,
            "EMHD - jam efektif/hari (J)": emhd,
            "Lost Time (Site)": lost_time,
            "Ratio Shift (Site)": ratio_shift,
            "Load Mechanic": load_mechanic,
            "Load Electrican": load_electrican,
            "Load Welder": load_welder,
            "RACI Mechanic": backend.raci["Mechanic"],
            "RACI Electric": backend.raci["Electric"],
            "RACI Welder": backend.raci["Welder"],
            "FTE Mechanic (raw)": fte_mechanic,
            "FTE Electric (raw)": fte_electric,
            "FTE Welder (raw)": fte_welder,
        },
    }


def aggregate_units(raw_results: List[dict]) -> dict:
    """Jumlahkan nilai RAW (belum dibulatkan) dari seluruh unit/baris,
    BARU dibulatkan SATU KALI per role/kolom -- persis formula
    `P47 = ROUND(SUM(P9:P46), 0)` di sheet 'Final Calculation'.

    `raw_results` adalah list dari output `compute_fte_raw()["raw"]` untuk
    setiap unit yang dihitung.
    """
    sums = {role: {m: 0.0 for m in MONTH_COLS} for role in ROLES}
    for raw in raw_results:
        for role in ROLES:
            for m in MONTH_COLS:
                sums[role][m] += raw[role][m]

    fte_table = {}
    for role in ROLES:
        fte_table[role] = {m: excel_round(sums[role][m]) for m in MONTH_COLS}
        # Tot = SUM(M1:M3) yang SUDAH dibulatkan, persis AH10 = SUM(AE10:AG10)
        fte_table[role]["Tot"] = sum(fte_table[role][m] for m in MONTH_COLS)

    total_row = {m: sum(fte_table[role][m] for role in ROLES) for m in MONTH_COLS}
    total_row["Tot"] = sum(total_row[m] for m in MONTH_COLS)
    fte_table["Total"] = total_row

    cost_table = {}
    for role in ROLES + ["Total"]:
        cost_table[role] = {
            month: fte_table[role][month] * COST_RATE[month] for month in MONTH_COLS
        }
        cost_table[role]["Tot"] = sum(cost_table[role][m] for m in MONTH_COLS)

    return {"fte": fte_table, "cost": cost_table}


def compute_fte(inputs: FTEInput, backend: BackendData) -> dict:
    """Kompatibilitas mundur: hitung SATU unit lalu langsung agregasi
    (setara dengan aggregate_units([raw]) untuk satu unit saja).
    Untuk banyak unit sekaligus, JANGAN panggil fungsi ini per-unit lalu
    dijumlahkan manual -- pakai compute_fte_raw() + aggregate_units() supaya
    skema round-nya benar (round sekali di total, bukan round per-unit).
    """
    result = compute_fte_raw(inputs, backend)
    agg = aggregate_units([result["raw"]])
    agg["intermediate"] = result["intermediate"]
    return agg
