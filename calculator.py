# calculator.py
"""
Mesin hitung FTE yang sinkron dengan aturan pembulatan baris Excel
serta mengamankan pemetaan data agar tidak tertukar antar role.
"""
from dataclasses import dataclass
import math
from typing import List, Dict, Any
from config import ROLES, MONTH_COLS, COST_RATE

@dataclass
class FTEInput:
    site: str
    competency_factor: float
    jarak_km: float
    sub_category: str
    jenis_unit: str
    pa_percent: float
    populasi: float

class CalculationError(Exception):
    pass

def excel_round(val: float, decimals: int = 2) -> float:
    if math.isnan(val) or math.isinf(val):
        return 0.0
    multiplier = 10 ** decimals
    return math.floor(val * multiplier + 0.5) / multiplier

def compute_fte_raw(inputs: FTEInput, backend: Any) -> dict:
    site_clean = inputs.site.strip().upper()
    ratio_shift = backend.ratio_shift.get(site_clean)
    lost_time = backend.lost_time.get(site_clean)

    if ratio_shift is None or lost_time is None:
        raise CalculationError(f"Data untuk Site '{inputs.site}' tidak ditemukan di BACKEND.")

    sub_cat_clean = inputs.sub_category.strip()
    lf_row = None
    for idx, row in backend.load_factor.iterrows():
        if str(idx).strip().lower() == sub_cat_clean.lower():
            lf_row = row
            break
            
    if lf_row is None:
        raise CalculationError(f"Sub Category '{inputs.sub_category}' tidak ditemukan.")

    load_mechanic = float(lf_row["Load Mechanic"])
    load_electrician = float(lf_row["Load Electrican"])
    load_welder = float(lf_row["Load Welder"])

    # Rumus Jam Kerja
    g_pa = inputs.pa_percent / 100.0
    i_breakdown_hours = 24.0 * (1.0 - g_pa)
    j_emhd = 12.0 - lost_time - (inputs.jarak_km / 40.0)
    
    if j_emhd <= 0:
        raise CalculationError("EMHD <= 0. Periksa nilai Lost Time atau Jarak.")

    base_factor = (i_breakdown_hours / j_emhd) * inputs.populasi * ratio_shift
    cf = inputs.competency_factor

    # Mengambil Proporsi RACI dengan proteksi fallback kunci nama
    raci_m = backend.raci.get("Mechanic", 1.0)
    raci_e = backend.raci.get("Electrician", backend.raci.get("Electric", 1.0))
    raci_w = backend.raci.get("Welder", 1.0)

    fte_m_total = (base_factor * load_mechanic / cf) * raci_m
    fte_e_total = (base_factor * load_electrician / cf) * raci_e
    fte_w_total = (base_factor * load_welder / cf) * raci_w

    # Hitung Split Level
    res = {
        "Mechanic": {
            "M1": fte_m_total * backend.split_mechanic.get("M1", 0.0),
            "M2": fte_m_total * backend.split_mechanic.get("M2", 0.0),
            "M3": fte_m_total * backend.split_mechanic.get("M3", 0.0),
        },
        "Electric": {
            "M1": fte_e_total * backend.split_electrician.get("M1", 0.0),
            "M2": fte_e_total * backend.split_electrician.get("M2", 0.0),
            "M3": fte_e_total * backend.split_electrician.get("M3", 0.0),
        },
        "Welder": {
            "M1": fte_w_total * backend.split_welder.get("M1", 0.0),
            "M2": fte_w_total * backend.split_welder.get("M2", 0.0),
            "M3": fte_w_total * backend.split_welder.get("M3", 0.0),
        }
    }
    
    # Pembulatan per baris unit (Excel Style)
    rounded_res = {}
    for role in ["Mechanic", "Electric", "Welder"]:
        rounded_res[role] = {}
        for m in MONTH_COLS:
            rounded_res[role][m] = excel_round(res[role][m], 2)
        rounded_res[role]["Tot"] = sum(rounded_res[role][m] for m in MONTH_COLS)
        
    return rounded_res

def aggregate_units(raw_results: List[dict]) -> dict:
    fte_table = {}
    for role in ROLES:
        fte_table[role] = {"M1": 0.0, "M2": 0.0, "M3": 0.0, "Tot": 0.0}
        
    for res in raw_results:
        for role in ROLES:
            for m in MONTH_COLS:
                fte_table[role][m] += res[role][m]

    for role in ROLES:
        fte_table[role]["Tot"] = sum(fte_table[role][m] for m in MONTH_COLS)

    total_row = {}
    for m in MONTH_COLS:
        total_row[m] = sum(fte_table[role][m] for role in ROLES)
    total_row["Tot"] = sum(total_row[m] for m in MONTH_COLS)
    fte_table["Total"] = total_row

    cost_table = {}
    for role in ROLES + ["Total"]:
        cost_table[role] = {}
        for m in MONTH_COLS:
            cost_table[role][m] = fte_table[role][m] * COST_RATE[m]
        cost_table[role]["Tot"] = sum(cost_table[role][m] for m in MONTH_COLS)

    return {"fte": fte_table, "cost": cost_table}
