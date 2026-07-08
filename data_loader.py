# data_loader.py
"""
Robust BACKEND CSV loader + parser with canonical name mapping.

Provides:
 - BackendData dataclass with: load_factor, ratio_shift, raci, split_*, lost_time,
   sites, sub_categories (display names), units_map (by canonical key)
 - load_backend_data(source=None)
 - parse_backend(raw: pd.DataFrame)
 - Normalization & mapping helpers so selectbox matching is robust.
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Union
import pandas as pd
import math
import logging
import os
import re

logger = logging.getLogger(__name__)


class BackendDataError(Exception):
    pass


@dataclass
class BackendData:
    load_factor: pd.DataFrame
    ratio_shift: Dict[str, float]
    raci: Dict[str, float]
    split_mechanic: List[float]
    split_welder: List[float]
    split_electrician: List[float]
    lost_time: Dict[str, float]
    sites: List[str]
    sub_categories: List[str]          # display/original names in order
    units_map: Dict[str, List[str]]    # keyed by canonical sub_category (normalized)
    _norm_to_orig: Dict[str, str]      # canonical -> original (first seen)

    def first_site(self) -> Optional[str]:
        return self.sites[0] if self.sites else None

    def _normalize(self, s: Optional[str]) -> str:
        if s is None:
            return ""
        s = str(s).strip().lower()
        s = re.sub(r"\s+", " ", s)
        s = re.sub(r"[^\w\s]", "", s)
        return s

    def units_for(self, sub_category_input: Optional[str]) -> List[str]:
        if not sub_category_input:
            return []
        nk = self._normalize(sub_category_input)
        return self.units_map.get(nk, [])

    def original_sub_name(self, sub_category_input: Optional[str]) -> Optional[str]:
        if not sub_category_input:
            return None
        nk = self._normalize(sub_category_input)
        return self._norm_to_orig.get(nk)


# Helpers
def _row_to_text(row: pd.Series) -> str:
    parts = []
    for c in row.tolist():
        if pd.isna(c):
            parts.append("")
        else:
            parts.append(str(c))
    return " ".join(parts).strip().lower()


def _is_blank_row(row: pd.Series) -> bool:
    for c in row.tolist():
        if pd.isna(c):
            continue
        if str(c).strip() != "":
            return False
    return True


def _safe_float(value) -> float:
    if value is None:
        return math.nan
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)
    s = str(value).strip()
    if s == "" or s.lower() in {"nan", "none"}:
        return math.nan
    s = s.replace("%", "").replace(" ", "")
    if "," in s and "." not in s and s.count(",") == 1:
        s = s.replace(",", ".")
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        logger.debug("Safe float parse failed for %r", value)
        return math.nan


def _parse_percent_cell(cell) -> float:
    if cell is None:
        return math.nan
    s = str(cell).strip()
    if s == "":
        return math.nan
    if "%" in s:
        v = _safe_float(s)
        return math.nan if math.isnan(v) else v / 100.0
    v = _safe_float(s)
    if math.isnan(v):
        return math.nan
    return v / 100.0 if v > 1.0 else v


def _unique_preserve(seq):
    seen = set()
    out = []
    for s in seq:
        if s is None:
            continue
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _find_first_row_containing(rows_text: List[str], keyword: str, start: int = 0) -> Optional[int]:
    kw = keyword.strip().lower()
    for i in range(start, len(rows_text)):
        if kw in rows_text[i]:
            return i
    return None


def parse_backend(raw: pd.DataFrame) -> BackendData:
    df = raw.copy().reset_index(drop=True)
    rows_text = [_row_to_text(df.iloc[i]) for i in range(len(df))]
    blank_mask = [_is_blank_row(df.iloc[i]) for i in range(len(df))]

    # LOAD FACTOR
    lf_header_idx = _find_first_row_containing(rows_text, "sub category")
    if lf_header_idx is None:
        lf_header_idx = _find_first_row_containing(rows_text, "load factor")
        if lf_header_idx is not None:
            j = lf_header_idx + 1
            while j < len(df) and blank_mask[j]:
                j += 1
            lf_header_idx = j if j < len(df) else None
    if lf_header_idx is None:
        lf_header_idx = _find_first_row_containing(rows_text, "attribute")  # fallback

    lf_end_idx = None
    if lf_header_idx is not None:
        j = lf_header_idx + 1
        while j < len(df) and not blank_mask[j]:
            if "ratio shift" in rows_text[j] or "proporsi raci" in rows_text[j] or "split ratio" in rows_text[j] or "lost time" in rows_text[j]:
                break
            j += 1
        lf_end_idx = j

    lf_df = pd.DataFrame()
    if lf_header_idx is not None and lf_end_idx is not None and lf_end_idx > lf_header_idx:
        header_row = df.iloc[lf_header_idx].astype(str).tolist()
        col_names = [str(c).strip() for c in header_row]
        lf_rows = df.iloc[lf_header_idx + 1:lf_end_idx].copy()
        if lf_rows.shape[1] != len(col_names):
            col_names = [f"col_{i}" for i in range(lf_rows.shape[1])]
        lf_rows.columns = col_names
        lf_rows.columns = [c if str(c).strip() != "" else f"col_{i}" for i, c in enumerate(lf_rows.columns)]
        lf_df = lf_rows.copy()
        lower_cols = [str(c).strip().lower() for c in lf_df.columns]
        text_idx = set(i for i, c in enumerate(lower_cols) if "sub" in c or "category" in c or "attr" in c)
        if not text_idx:
            text_idx.update({0, 1} if lf_df.shape[1] >= 2 else {0})
        for idx, col in enumerate(lf_df.columns):
            if idx in text_idx:
                lf_df[col] = lf_df[col].apply(lambda v: "" if pd.isna(v) else str(v).strip())
            else:
                lf_df[col] = lf_df[col].apply(lambda v: (_safe_float(v) if isinstance(v, str) or pd.isna(v) else (float(v) if not pd.isna(v) else math.nan)))
    else:
        logger.warning("Load Factor block not found")

    # RATIO SHIFT
    ratio_shift = {}
    rs_title_idx = _find_first_row_containing(rows_text, "ratio shift")
    if rs_title_idx is not None:
        j = rs_title_idx + 1
        while j < len(df) and blank_mask[j]:
            j += 1
        if j < len(df):
            if "site" in rows_text[j] or "ratio" in rows_text[j]:
                j2 = j + 1
                while j2 < len(df) and not blank_mask[j2]:
                    if "proporsi raci" in rows_text[j2] or "raci" in rows_text[j2]:
                        break
                    row_cells = df.iloc[j2].tolist()
                    site = None
                    val = None
                    if len(row_cells) >= 1 and not pd.isna(row_cells[0]) and str(row_cells[0]).strip() != "":
                        site = str(row_cells[0]).strip()
                    if len(row_cells) >= 2 and not pd.isna(row_cells[1]) and str(row_cells[1]).strip() != "":
                        val = _safe_float(row_cells[1])
                    if site:
                        ratio_shift[site] = val if val is not None else math.nan
                    j2 += 1

    # RACI
    raci = {}
    raci_title_idx = _find_first_row_containing(rows_text, "proporsi raci")
    if raci_title_idx is None:
        raci_title_idx = _find_first_row_containing(rows_text, "raci")
    raci_end_idx = raci_title_idx
    if raci_title_idx is not None:
        j = raci_title_idx + 1
        while j < len(df) and not blank_mask[j]:
            txt = rows_text[j]
            for r in ("mechanic", "electric", "electrician", "welder"):
                if r in txt:
                    row_cells = df.iloc[j].tolist()
                    val = None
                    if len(row_cells) >= 2 and not pd.isna(row_cells[1]) and str(row_cells[1]).strip() != "":
                        val = _parse_percent_cell(row_cells[1])
                    else:
                        for c in row_cells[1:]:
                            if not pd.isna(c) and str(c).strip() != "":
                                maybe = _parse_percent_cell(c)
                                if not math.isnan(maybe):
                                    val = maybe
                                    break
                    name = "electrician" if r in ("electric", "electrician") else r
                    raci[name] = val if val is not None else math.nan
                    break
            j += 1
        raci_end_idx = j

    # Split ratios (after raci_end_idx)
    def _extract_split_after(role_keyword: str, after_idx: int) -> List[float]:
        target = None
        for i in range((after_idx or 0) + 1, len(df)):
            rt = rows_text[i]
            if ("split ratio" in rt and role_keyword in rt) or (f"split ratio {role_keyword}" in rt):
                target = i
                break
        if target is None:
            for i in range((after_idx or 0) + 1, len(df)):
                rt = rows_text[i]
                if role_keyword in rt and "split" in rt:
                    target = i
                    break
        if target is None:
            for i in range((after_idx or 0) + 1, len(df)):
                first_cell = str(df.iloc[i, 0]) if df.shape[1] >= 1 else ""
                if first_cell.strip().lower() == role_keyword:
                    target = i
                    break
        if target is None:
            return []
        results = []
        j = target + 1
        while j < len(df) and not blank_mask[j]:
            if "%" in rows_text[j] or any(ch.isdigit() for ch in rows_text[j]):
                row_cells = df.iloc[j].tolist()
                for c in row_cells:
                    if pd.isna(c):
                        continue
                    s = str(c).strip()
                    if s == "":
                        continue
                    v = _parse_percent_cell(s)
                    if math.isnan(v):
                        v = _safe_float(s)
                        if math.isnan(v):
                            continue
                    results.append(v)
            else:
                break
            j += 1
        if not results:
            return []
        normed = [ (math.nan if math.isnan(v) else (v/100.0 if v>1.0 else v)) for v in results ]
        seen = set(); out=[]
        for v in normed:
            if math.isnan(v):
                if "nan" in seen: continue
                seen.add("nan"); out.append(v)
            else:
                if v in seen: continue
                seen.add(v); out.append(v)
        return out

    split_mechanic = _extract_split_after("mechanic", raci_end_idx or 0)
    split_welder = _extract_split_after("welder", raci_end_idx or 0)
    split_electrician = _extract_split_after("electrician", raci_end_idx or 0)
    if not split_electrician:
        split_electrician = _extract_split_after("electric", raci_end_idx or 0)

    # LOST TIME
    lost_time = {}
    lt_idx = _find_first_row_containing(rows_text, "lost time")
    if lt_idx is not None:
        j = lt_idx + 1
        while j < len(df) and blank_mask[j]:
            j += 1
        if j < len(df) and ("site" in rows_text[j] or "lost time" in rows_text[j]):
            start = j + 1
        else:
            start = j
        k = start
        while k < len(df) and not blank_mask[k]:
            row_cells = df.iloc[k].tolist()
            site = None; val=None
            if len(row_cells) >= 1 and not pd.isna(row_cells[0]) and str(row_cells[0]).strip()!="":
                site = str(row_cells[0]).strip()
            if len(row_cells) >= 2 and not pd.isna(row_cells[1]) and str(row_cells[1]).strip()!="":
                val = _safe_float(row_cells[1])
            if site:
                lost_time[site] = val if val is not None else math.nan
            k += 1

    for k in ("mechanic","electrician","welder"):
        raci.setdefault(k, math.nan)

    sites = list(ratio_shift.keys()) if ratio_shift else list(lost_time.keys())

    # Build sub_categories and units_map using normalization mapping
    sub_categories = []
    units_map = {}
    norm_to_orig = {}
    if not lf_df.empty:
        lower_cols = [str(c).strip().lower() for c in lf_df.columns]
        sub_col_idx = None; attr_col_idx = None
        for idx,c in enumerate(lower_cols):
            if "sub" in c or "category" in c:
                sub_col_idx = idx
            if "attr" in c or "attribute" in c or "jenis" in c:
                attr_col_idx = idx
        if sub_col_idx is None:
            sub_col_idx = 0
        if attr_col_idx is None:
            attr_col_idx = 1 if lf_df.shape[1] >=2 else None

        raw_subs = lf_df.iloc[:, sub_col_idx].astype(str).apply(lambda s: s.strip()).tolist()
        raw_attrs = lf_df.iloc[:, attr_col_idx].astype(str).apply(lambda s: s.strip()) if attr_col_idx is not None else pd.Series([""]*len(raw_subs))
        seen = set()
        for i, sub in enumerate(raw_subs):
            if not sub or sub.lower()=="nan":
                continue
            orig = sub
            nk = re.sub(r"\s+", " ", orig.strip().lower())
            nk = re.sub(r"[^\w\s]", "", nk)
            if nk not in seen:
                seen.add(nk)
                sub_categories.append(orig)
                norm_to_orig[nk] = orig
            attr_val = ""
            try:
                attr_val = str(raw_attrs.iloc[i]).strip()
            except Exception:
                attr_val = ""
            if attr_val and attr_val.lower()!="nan":
                units_map.setdefault(nk, []).append(attr_val)
        for k,v in list(units_map.items()):
            out=[]
            s=set()
            for x in v:
                if x not in s:
                    s.add(x); out.append(x)
            units_map[k]=out

    return BackendData(
        load_factor=lf_df,
        ratio_shift=ratio_shift,
        raci=raci,
        split_mechanic=split_mechanic,
        split_welder=split_welder,
        split_electrician=split_electrician,
        lost_time=lost_time,
        sites=sites,
        sub_categories=sub_categories,
        units_map=units_map,
        _norm_to_orig=norm_to_orig,
    )


def load_backend_data(source: Optional[Union[str, pd.DataFrame]] = None) -> BackendData:
    GOOGLE_SHEET_ID = "1YRvXt0AE-dVBVwRvLtsb57Qz8DYd9YbVQlVbRD31C7I"
    GOOGLE_SHEET_GID = "1437049322"
    google_export_url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/export?format=csv&gid={GOOGLE_SHEET_GID}"

    try:
        if isinstance(source, pd.DataFrame):
            raw = source
            return parse_backend(raw)
        if isinstance(source, str):
            raw = pd.read_csv(source, header=None, dtype=str)
            return parse_backend(raw)
        env_path = os.getenv("BACKEND_CSV_PATH")
        if env_path and os.path.exists(env_path):
            raw = pd.read_csv(env_path, header=None, dtype=str)
            return parse_backend(raw)
        env_url = os.getenv("BACKEND_CSV_URL")
        if env_url:
            raw = pd.read_csv(env_url, header=None, dtype=str)
            return parse_backend(raw)
        default_fname = "FTE - BACKEND (2).csv"
        if os.path.exists(default_fname):
            raw = pd.read_csv(default_fname, header=None, dtype=str)
            return parse_backend(raw)
        raw = pd.read_csv(google_export_url, header=None, dtype=str)
        return parse_backend(raw)
    except Exception as e:
        logger.exception("Failed to load backend data")
        raise BackendDataError("Failed to load backend data") from e
