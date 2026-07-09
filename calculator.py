# calculator.py
"""
FTE calculation helpers compatible with BackendData from data_loader.parse_backend().

Exports:
 - FTEInput dataclass
 - CalculationError exception
 - excel_round(val, decimals=2)
 - compute_fte_raw(inputs, backend) -> dict { "raw": {...}, "intermediate": {...} }
 - aggregate_units(raw_results) -> dict { "fte": {...}, "cost": {...} }

Notes:
 - compute_fte_raw returns UNROUNDED per-row results ("raw").
 - aggregate_units implements row-by-row Excel-style rounding, then aggregates (Excel behavior).
"""
from dataclasses import dataclass
import math
from typing import List, Dict, Any, Optional
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
    """Round half-up like Excel ROUND(value, decimals)."""
    try:
        if val is None or math.isnan(val) or math.isinf(val):
            return 0.0
    except Exception:
        return 0.0
    multiplier = 10 ** decimals
    return math.floor(val * multiplier + 0.5) / multiplier

# helpers
def _norm(s: Any) -> str:
    if s is None:
        return ""
    return str(s).strip().lower()

def _lookup_site_value(d: Dict[str, float], site: str) -> Optional[float]:
    """Case-insensitive lookup for site-keyed dicts."""
    if not isinstance(d, dict):
        return None
    key = _norm(site)
    for k, v in d.items():
        if _norm(k) == key:
            try:
                return float(v)
            except Exception:
                return v
    return None

def _ensure_split_dict(split_obj: Any) -> Dict[str, float]:
    """
    Normalize split ratios to dict with keys M1,M2,M3.
    Supports list/tuple (len 1..3) or dict keyed by 'M1' etc.
    """
    if split_obj is None:
        return {"M1": 0.0, "M2": 0.0, "M3": 0.0}
    if isinstance(split_obj, dict):
        return {k: float(split_obj.get(k, 0.0) or 0.0) for k in ("M1","M2","M3")}
    # try sequence
    try:
        seq = list(split_obj)
        if len(seq) >= 3:
            return {"M1": float(seq[0] or 0.0), "M2": float(seq[1] or 0.0), "M3": float(seq[2] or 0.0)}
        if len(seq) == 2:
            return {"M1": float(seq[0] or 0.0), "M2": float(seq[1] or 0.0), "M3": 0.0}
        if len(seq) == 1:
            return {"M1": float(seq[0] or 0.0), "M2": 0.0, "M3": 0.0}
    except Exception:
        pass
    return {"M1": 0.0, "M2": 0.0, "M3": 0.0}

def _get_load_from_row(row, keywords: List[str]) -> float:
    """Try to find a numeric load value in row using keywords in column names."""
    for name in row.index:
        lname = str(name).strip().lower()
        for kw in keywords:
            if kw.lower() in lname:
                v = row.get(name)
                try:
                    return float(str(v).replace(",", "."))
                except Exception:
                    try:
                        return float(v)
                    except Exception:***

