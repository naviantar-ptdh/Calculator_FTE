# calculator.py
"""
Mesin hitung FTE yang sinkron dengan aturan pembulatan baris Excel
Serta dilengkapi pelindung Tipe Data (Safe Type Guard) agar anti-crash 
terhadap segala jenis return dari data_loader.
"""
from dataclasses import dataclass
import math
from typing import List, Dict, Any
import pandas as pd
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
    """Mengikuti logika ROUND() di Excel secara presisi"""
    if math.isnan(val) or math.isinf(val):
        return 0.0
    multiplier = 10 ** decimals
    return math.floor(val * multiplier + 0.5) / multiplier

def safe_extract_split(split_obj: Any, role_default: str) -> dict:
    """
    Fungsi pengaman khusus: Memastikan apa pun bentuk data dari data_loader
    (baik Dict, DataFrame, Series, atau None), akan diubah menjadi Dict M1/M2/M3 yang valid.
    """
    # 1. Jika sudah berupa dictionary, langsung pakai
    if isinstance(split_obj, dict):
        # Pastikan keys dalam huruf besar untuk konsistensi
        return {str(k).strip().upper(): float(v) for k, v in split_obj.items() if v is not None}
    
    # 2. Jika berupa Pandas DataFrame atau Series (efek data_loader lama)
    if isinstance(split_obj, (pd.DataFrame, pd.Series)):
        try:
            res = {}
            for k, v in split_obj.items():
                res[str(k).strip().upper()] = float(v)
            return res
        except:
            pass

    # 3. Fallback jika bernilai None atau gagal di-parse (Rasio Default Resmi Perusahaan)
    if role_default.lower() == "mechanic":
        return {"M1": 0.20, "M2": 0.30, "M3": 0.50}
    elif role_default.lower() == "welder":
        return {"M1": 0.4285714286, "M2": 0.5714285714, "M3": 0.0}
    else:  # Electrician
        # Menyesuaikan rasio default electric di site ACP/KCP/BCP Anda
        return {"M1": 0.4285714286, "M2": 0.5714285714, "M3": 0.0}

def compute_fte_raw(inputs: FTEInput, backend: Any) -> dict:
    site_clean = inputs.site.strip().upper()
    
    # Mengambil ratio_shift & lost_time dari backend dengan proteksi default jika None
    ratio_shift = getattr(backend, 'ratio_shift', {}).get(site_clean, 1.46) if hasattr(backend, 'ratio_shift') else 1.46
    lost_time = getattr(backend, 'lost_time', {}).get(site_clean, 3.54) if hasattr(backend, 'lost_time') else 3.54

    # Ambil tabel load factor
    lf_df = getattr(backend, 'load_factor', None)
    if lf_df is None or not hasattr(lf_df, 'iterrows'):
        raise CalculationError("Tabel Load Factor di BACKEND tidak dapat dibaca.")

    sub_cat_clean = inputs.sub_category.strip()
    lf_row = None
    for idx, row in lf_df.iterrows():
        if str(idx).strip().lower() == sub_cat_clean.lower():
            lf_row = row
            break
            
    if lf_row is None:
        raise CalculationError(f"Sub Category '{inputs.sub_category}' tidak ditemukan di tabel Load Factor.")

    # Ambil nilai load factor per role
    try:
        load_mechanic = float(str(lf_row.get("Load Mechanic", 0)).replace(",", "."))
        load_electrician = float(str(lf_row.get("Load Electrican", lf_row.get("Load Electrician", 0))).replace(",", "."))
        load_welder = float(str(lf_row.get("Load Welder", 0)).replace(",", "."))
    except Exception:
        load_mechanic, load_electrician, load_welder = 0.0, 0.0, 0.0

    # Rumus Jam Kerja Baku
    g_pa = inputs.pa_percent / 100.0
    i_breakdown_hours = 24.0 * (1.0 - g_pa)
    j_emhd = 12.0 - lost_time - (inputs.jarak_km / 40.0)
    
    if j_emhd <= 0:
        j_emhd = 7.0  # Safe fallback agar tidak pembagian dengan nol jika input jarak terlalu ekstrem

    base_factor = (i_breakdown_hours / j_emhd) * inputs.populasi * ratio_shift
    cf = inputs.competency_factor if inputs.competency_factor > 0 else 1.0

    # Mengambil Proporsi RACI dari backend dengan safe fallback
    raci_dict = getattr(backend, 'raci', {}) if hasattr(backend, 'raci') else {}
    raci_m = raci_dict.get("Mechanic", 1.0) if isinstance(raci_dict, dict) else 1.0
    raci_e = (raci_dict.get("Electrician", raci_dict.get("Electric", 1.0))) if isinstance(raci_dict, dict) else 1.0
    raci_w = raci_dict.get("Welder", 1.0) if isinstance(raci_dict, dict) else 1.0

    # Total FTE sebelum di-split level kompetensi
    fte_m_total = (base_factor * load_mechanic / cf) * raci_m
    fte_e_total = (base_factor * load_electrician / cf) * raci_e
    fte_w_total = (base_factor * load_welder / cf) * raci_w

    # --- PROTEKSI UTAMA: Mengamankan objek Split Ratio agar kebal dari AttributeError ---
    split_m = safe_extract_split(getattr(backend, 'split_mechanic', None), "mechanic")
    split_w = safe_extract_split(getattr(backend, 'split_welder', None), "welder")
    split_e = safe_extract_split(getattr(backend, 'split_electrician', None), "electrician")

    # Distribusi porsi split secara aman menggunakan kunci huruf besar (M1, M2, M3)
    res = {
        "Mechanic": {
            "M1": fte_m_total * split_m.get("M1", 0.0),
            "M2": fte_m_total * split_m.get("M2", 0.0),
            "M3": fte_m_total * split_m.get("M3", 0.0),
        },
        "Electric": {
            "M1": fte_e_total * split_e.get("M1", 0.0),
            "M2": fte_e_total * split_e.get("M2", 0.0),
            "M3": fte_e_total * split_e.get("M3", 0.0),
        },
        "Welder": {
            "M1": fte_w_total * split_w.get("M1", 0.0),
            "M2": fte_w_total * split_w.get("M2", 0.0),
            "M3": fte_w_total * split_w.get("M3", 0.0),
        }
    }
    
    # Pembulatan per baris unit langsung di sini (Excel Row-by-Row Style)
    rounded_res = {}
    for role in ["Mechanic", "Electric", "Welder"]:
        rounded_res[role] = {}
        for m in MONTH_COLS:
            rounded_res[role][m] = excel_round(res[role][m], 2)
        rounded_res[role]["Tot"] = sum(rounded_res[role][m] for m in MONTH_COLS)
        
    return rounded_res

def aggregate_units(raw_results: List[dict]) -> dict:
    """Menggabungkan hasil baris unit yang sudah dibulatkan ke Grand Total"""
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

    # Hitung Tabel Estimasi Biaya
    cost_table = {}
    for role in ROLES + ["Total"]:
        cost_table[role] = {}
        for m in MONTH_COLS:
            cost_table[role][m] = fte_table[role][m] * COST_RATE[m]
        cost_table[role]["Tot"] = sum(cost_table[role][m] for m in MONTH_COLS)

    return {"fte": fte_table, "cost": cost_table}
