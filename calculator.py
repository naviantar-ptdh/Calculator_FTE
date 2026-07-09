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
                    except Exception:
                        continue
    # fallback: scan numeric columns
    for c in row.index:
        try:
            return float(row[c])
        except Exception:
            continue
    return 0.0

def compute_fte_raw(inputs: FTEInput, backend: Any) -> dict:
    """
    Compute unrounded FTE per-role per-month for a single unit row.
    Returns dict with keys:
      - "raw": { role: {M1:.., M2:.., M3:.., Tot:..}, ... }
      - "intermediate": debug values
    """
    # site lookups (case-insensitive)
    ratio_shift = _lookup_site_value(getattr(backend, "ratio_shift", {}), inputs.site)
    lost_time = _lookup_site_value(getattr(backend, "lost_time", {}), inputs.site)
    if ratio_shift is None or lost_time is None:
        raise CalculationError(f"Data untuk Site '{inputs.site}' tidak lengkap (ratio_shift/lost_time).")

    # find load factor row: determine sub-category column
    lf_df = getattr(backend, "load_factor", None)
    if lf_df is None or lf_df.empty:
        raise CalculationError("Tabel Load Factor kosong di BACKEND.")
    # detect sub-category column by header keywords
    sub_col = None
    for c in lf_df.columns:
        cn = str(c).strip().lower()
        if "sub" in cn or "category" in cn:
            sub_col = c
            break
    if sub_col is None:
        sub_col = lf_df.columns[0]

    # map UI sub_category to original sheet name if backend provides mapping
    target_sub = inputs.sub_category
    if hasattr(backend, "original_sub_name"):
        mapped = backend.original_sub_name(target_sub)
        if mapped:
            target_sub = mapped

    # find matching row
    lf_row = None
    for _, r in lf_df.iterrows():
        val = r.get(sub_col, "")
        if _norm(val) == _norm(target_sub):
            lf_row = r
            break
    if lf_row is None:
        raise CalculationError(f"Sub Category '{inputs.sub_category}' tidak ditemukan di Load Factor.")

    # extract loads
    load_mechanic = _get_load_from_row(lf_row, ["load mechanic", "mechanic"])
    load_electrician = _get_load_from_row(lf_row, ["load electrician", "electrican", "electrician", "electric"])
    load_welder = _get_load_from_row(lf_row, ["load welder", "welder"])

    # compute breakdown hours & EMHD
    g_pa = float(inputs.pa_percent) / 100.0
    h_breakdown_pct = 1.0 - g_pa
    i_breakdown_hours = 24.0 * h_breakdown_pct

    j_emhd = 12.0 - float(lost_time) - (float(inputs.jarak_km) / 40.0)
    if j_emhd <= 0:
        raise CalculationError("Jam kerja efektif (EMHD) <= 0. Periksa Lost Time atau Jarak.")

    base_factor = (i_breakdown_hours / j_emhd) * float(inputs.populasi) * float(ratio_shift)
    cf = float(inputs.competency_factor) if inputs.competency_factor and inputs.competency_factor != 0 else 1.0

    # raci (backend may store lowercase keys)
    raci_dict = getattr(backend, "raci", {}) or {}
    def _get_raci(k):
        for kk, vv in raci_dict.items():
            if _norm(kk) == _norm(k):
                try:
                    return float(vv)
                except Exception:
                    return vv
        return 0.0
    raci_m = _get_raci("mechanic")
    raci_e = _get_raci("electrician") or _get_raci("electric")
    raci_w = _get_raci("welder")

    # normalize raci to fraction if >1
    def _norm_frac(x):
        try:
            xv = float(x)
            return xv/100.0 if xv > 1.0 else xv
        except Exception:
            return 0.0
    raci_m = _norm_frac(raci_m)
    raci_e = _norm_frac(raci_e)
    raci_w = _norm_frac(raci_w)

    # total FTE per role before split
    fte_m_total = (base_factor * load_mechanic / cf) * raci_m
    fte_e_total = (base_factor * load_electrician / cf) * raci_e
    fte_w_total = (base_factor * load_welder / cf) * raci_w

    # split dictionaries
    split_m = _ensure_split_dict(getattr(backend, "split_mechanic", None))
    split_e = _ensure_split_dict(getattr(backend, "split_electrician", None))
    split_w = _ensure_split_dict(getattr(backend, "split_welder", None))

    # raw per role per month (unrounded)
    raw = {}
    raw["Mechanic"] = {
        "M1": fte_m_total * split_m.get("M1", 0.0),
        "M2": fte_m_total * split_m.get("M2", 0.0),
        "M3": fte_m_total * split_m.get("M3", 0.0),
    }
    raw["Electric"] = {
        "M1": fte_e_total * split_e.get("M1", 0.0),
        "M2": fte_e_total * split_e.get("M2", 0.0),
        "M3": fte_e_total * split_e.get("M3", 0.0),
    }
    raw["Welder"] = {
        "M1": fte_w_total * split_w.get("M1", 0.0),
        "M2": fte_w_total * split_w.get("M2", 0.0),
        "M3": fte_w_total * split_w.get("M3", 0.0),
    }

    # Totals (unrounded)
    for role in ["Mechanic", "Electric", "Welder"]:
        raw[role]["Tot"] = sum(raw[role].get(m, 0.0) for m in MONTH_COLS)

    intermediate = {
        "base_factor": base_factor,
        "cf": cf,
        "load_mechanic": load_mechanic,
        "load_electrician": load_electrician,
        "load_welder": load_welder,
        "raci": {"m": raci_m, "e": raci_e, "w": raci_w},
        "split_m": split_m,
        "split_e": split_e,
        "split_w": split_w,
    }

    return {"raw": raw, "intermediate": intermediate}

def aggregate_units(raw_results: List[dict]) -> dict:
    """
    Accepts raw_results: list of per-row raw dicts (each is like compute_fte_raw(... )['raw']).
    Implements ROW-BY-ROW rounding (Excel style): for each row, round each role/month with excel_round,
    THEN aggregate across rows. Finally compute Tot and Cost.
    Returns {"fte": fte_table, "cost": cost_table}
    """
    # initialize accumulator for roles
    fte_table: Dict[str, Dict[str, float]] = {}
    for role in ROLES:
        fte_table[role] = {m: 0.0 for m in MONTH_COLS}
        fte_table[role]["Tot"] = 0.0

    # for each raw row, round per-role/month and add
    for row_raw in raw_results:
        # row_raw is expected to be dict like {"Mechanic":{M1..}, "Electric":..., "Welder":...}
        for role in ROLES:
            role_raw = row_raw.get(role, {})
            # round each month for this row
            for m in MONTH_COLS:
                val = float(role_raw.get(m, 0.0))
                rval = excel_round(val, 2)
                fte_table[role][m] += rval

    # compute Tot per role
    for role in ROLES:
        fte_table[role]["Tot"] = sum(fte_table[role][m] for m in MONTH_COLS)

    # compute overall Total row (sum across roles)
    total_row: Dict[str, float] = {}
    for m in MONTH_COLS:
        total_row[m] = sum(fte_table[role][m] for role in ROLES)
    total_row["Tot"] = sum(total_row[m] for m in MONTH_COLS)
    fte_table["Total"] = total_row

    # compute cost table using COST_RATE (expected dict keyed by month col)
    cost_table: Dict[str, Dict[str, float]] = {}
    for role in list(ROLES) + ["Total"]:
        cost_table[role] = {}
        for m in MONTH_COLS:
            rate = COST_RATE.get(m, 0.0) if isinstance(COST_RATE, dict) else 0.0
            cost_table[role][m] = fte_table[role][m] * rate
        cost_table[role]["Tot"] = sum(cost_table[role][m] for m in MONTH_COLS)

    return {"fte": fte_table, "cost": cost_table}
