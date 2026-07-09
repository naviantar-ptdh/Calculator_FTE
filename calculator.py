# calculator.py
"""
Reimplementasi perhitungan FTE yang kompatibel dengan struktur BackendData
yang dikembalikan oleh data_loader.parse_backend().

Perbaikan penting:
 - Cari Sub Category di kolom load_factor (bukan index)
 - Normalisasi site / raci keys / sub category via lowercase/strip
 - Konversi split list -> dict {M1,M2,M3} (fallback jika perlu)
 - Round row-by-row menggunakan excel_round sebelum agregasi
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
    """Round half-up like Excel ROUND()."""
    if val is None or math.isnan(val) or math.isinf(val):
        return 0.0
    multiplier = 10 ** decimals
    return math.floor(val * multiplier + 0.5) / multiplier

# helper: normalize string
def _norm(s: Any) -> str:
    if s is None:
        return ""
    return str(s).strip().lower()

def _lookup_site_value(d: Dict[str, float], site: str) -> Any:
    """Case-insensitive lookup in dict keyed by site names."""
    if not d:
        return None
    key = _norm(site)
    for k, v in d.items():
        if _norm(k) == key:
            return v
    return None

def _ensure_split_dict(split_obj: Any) -> Dict[str, float]:
    """
    Convert backend.split_* (which might be list like [0.2,0.3,0.5] or dict)
    into dict with keys 'M1','M2','M3'. Use sensible fallbacks.
    """
    if split_obj is None:
        return {"M1": 0.0, "M2": 0.0, "M3": 0.0}
    # if it's already a dict with 'M1' keys
    if isinstance(split_obj, dict):
        return {k: float(split_obj.get(k, 0.0) or 0.0) for k in ("M1","M2","M3")}
    # if list/tuple-like
    try:
        seq = list(split_obj)
        if len(seq) >= 3:
            return {"M1": float(seq[0] or 0.0), "M2": float(seq[1] or 0.0), "M3": float(seq[2] or 0.0)}
        # if length 2 -> assume M1,M2 and M3=0
        if len(seq) == 2:
            return {"M1": float(seq[0] or 0.0), "M2": float(seq[1] or 0.0), "M3": 0.0}
        if len(seq) == 1:
            return {"M1": float(seq[0] or 0.0), "M2": 0.0, "M3": 0.0}
    except Exception:
        pass
    # fallback zeroes
    return {"M1": 0.0, "M2": 0.0, "M3": 0.0}

def compute_fte_raw(inputs: FTEInput, backend: Any) -> dict:
    """
    Compute single-unit FTE broken down per role and M1/M2/M3,
    returning rounded-per-row values (as dict like: Role->{'M1':..,'M2':..,'M3':..,'Tot':..})
    """
    # lookup site ratio and lost_time (case-insensitive)
    ratio_shift = _lookup_site_value(getattr(backend, "ratio_shift", {}), inputs.site)
    lost_time = _lookup_site_value(getattr(backend, "lost_time", {}), inputs.site)

    if ratio_shift is None or lost_time is None:
        raise CalculationError(f"Data untuk Site '{inputs.site}' tidak ditemukan di BACKEND (ratio_shift/lost_time).")

    # find load factor row: identify sub-category column name
    lf_df = getattr(backend, "load_factor", None)
    if lf_df is None or lf_df.empty:
        raise CalculationError("Tabel Load Factor kosong pada BACKEND.")

    # detect which column is sub category (by header containing 'sub' or 'category')
    sub_col = None
    for col in lf_df.columns:
        if "sub" in str(col).strip().lower() or "category" in str(col).strip().lower():
            sub_col = col
            break
    if sub_col is None:
        # fallback to first column
        sub_col = lf_df.columns[0]

    # try direct match, else try backend.original_sub_name mapping if available
    target_sub = inputs.sub_category
    # if backend has mapping function original_sub_name, use it to find canonical original name
    if hasattr(backend, "original_sub_name"):
        mapped = backend.original_sub_name(target_sub)
        if mapped:
            target_sub = mapped

    # find row where sub_col equals target_sub (case-insensitive)
    lf_row = None
    for _, row in lf_df.iterrows():
        val = row.get(sub_col, "")
        if _norm(val) == _norm(target_sub):
            lf_row = row
            break
    if lf_row is None:
        raise CalculationError(f"Sub Category '{inputs.sub_category}' tidak ditemukan di tabel Load Factor.")

    # extract load values: try multiple header name variants
    # Common header names might be: "Load Mechanic", "Load Mechanic", "Load Electrican", "Load Welder"
    def _get_load_value(row, possible_names):
        for name in possible_names:
            if name in row.index:
                v = row.get(name)
                try:
                    return float(v) if v is not None and str(v).strip() != "" else 0.0
                except Exception:
                    try:
                        return float(str(v).replace(",","."))
                    except Exception:
                        return 0.0
        # fallback: try numeric columns in row after first two columns (best-effort)
        for c in row.index:
            try:
                vv = float(row[c])
                return vv
            except Exception:
                continue
        return 0.0

    load_mechanic = _get_load_value(lf_row, ["Load Mechanic", "Load mechanic", "load mechanic"])
    load_electrician = _get_load_value(lf_row, ["Load Electrican", "Load Electrican", "Load Electrician", "Load electrician", "load](#)**

