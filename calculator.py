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

Setelah displit, masing-masing nilai M1/M2/M3 dibulatkan dengan ROUND
(round-half-up, sesuai fungsi ROUND() Excel) -- ini identik dengan bagaimana
sheet "Final Calculation" membulatkan P47/Q47/R47/T47/U47/W47/X47 sebelum
ditampilkan pada tabel "Summary Manpower".

Total (Tot) dihitung dari SUM atas nilai M1/M2/M3 yang SUDAH dibulatkan,
persis seperti formula AH10 = SUM(AE10:AG10) pada sheet asli.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

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


def compute_fte(inputs: FTEInput, backend: BackendData) -> dict:
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

    fte_table = {
        "Mechanic": {
            "M1": excel_round(fte_mechanic * m_a),
            "M2": excel_round(fte_mechanic * m_b),
            "M3": excel_round(fte_mechanic * m_c),
        },
        "Electric": {
            "M1": excel_round(fte_electric * e_a),
            "M2": excel_round(fte_electric * e_b),
            "M3": 0.0,
        },
        "Welder": {
            "M1": excel_round(fte_welder * w_a),
            "M2": excel_round(fte_welder * w_b),
            "M3": 0.0,
        },
    }

    for role in ROLES:
        fte_table[role]["Tot"] = sum(fte_table[role][m] for m in MONTH_COLS)

    total_row = {col: sum(fte_table[role][col] for role in ROLES) for col in MONTH_COLS}
    total_row["Tot"] = sum(total_row[m] for m in MONTH_COLS)
    fte_table["Total"] = total_row

    cost_table = {}
    for role in ROLES + ["Total"]:
        cost_table[role] = {
            month: fte_table[role][month] * COST_RATE[month] for month in MONTH_COLS
        }
        cost_table[role]["Tot"] = sum(cost_table[role][m] for m in MONTH_COLS)

    return {
        "fte": fte_table,
        "cost": cost_table,
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
