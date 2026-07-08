# data_loader.py
"""
Robust BACKEND CSV loader + parser for Calculator_FTE.

Perubahan penting:
 - BackendData now includes `sites`, `sub_categories`, and `units_map`.
 - BackendData provides method `units_for(sub_category)`.
 - Load Factor parsing preserves textual columns (first two) and converts numeric columns only.
 - load_backend_data(source=None) masih mendukung pemanggilan tanpa argumen.

Usage:
    from data_loader import load_backend_data, BackendDataError
    backend = load_backend_data()
    backend.sub_categories
    backend.units_for("Big Exca")
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Union
import pandas as pd
import math
import logging
import os

logger = logging.getLogger(__name__)


class BackendDataError(Exception):
    """Raised when backend data cannot be loaded or parsed cleanly."""
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
    sub_categories: List[str]
    units_map: Dict[str, List[str]]

    def first_site(self) -> Optional[str]:
        return self.sites[0] if self.sites else None

    def units_for(self, sub_category: str) -> List[str]:
        """
        Return list of Attributes / jenis unit for given sub_category.
        If sub_category not found, return empty list.
        """
        if sub_category is None:
            return []
        return self.units_map.get(sub_category, [])


# -----------------------
# Helper utilities
# -----------------------
def _row_to_text(row: pd.Series) -> str:
    parts = []
    for c in row.tolist():
        if pd.isna(c):
            parts.append("")
        else:
            parts.append(str(c))
    joined = " ".join(parts)
    return joined.strip().lower()


def _is_blank_row(row: pd.Series) -> bool:
    for c in row.tolist():
        if pd.isna(c):
            continue
        if str(c).strip() != "":
            return False
    return True


def _safe_float(value: Optional[Union[str, float, int]]) -> float:
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
        logger.debug("Could not parse float from %r", value)
        return math.nan


def _parse_percent_cell(cell: Optional[Union[str, float, int]]) -> float:
    if cell is None:
        return math.nan
    s = str(cell).strip()
    if s == "":
        return math.nan
    if "%" in s:
        v = _safe_float(s)
        if math.isnan(v):
            return math.nan
        return v / 100.0
    v = _safe_float(s)
    if math.isnan(v):
        return math.nan
    if v > 1.0:
        return v / 100.0
    return v


def _find_first_row_containing(rows_text: List[str], keyword: str, start: int = 0) -> Optional[int]:
    kw = keyword.strip().lower()
    for i in range(start, len(rows_text)):
        if kw in rows_text[i]:
            return i
    return None


def _find_first_row_matching_any(rows_text: List[str], keywords: List[str], start: int = 0) -> Optional[int]:
    for i in range(start, len(rows_text)):
        for kw in keywords:
            if kw.strip().lower() in rows_text[i]:
                return i
    return None


def _unique_preserve(seq: List[str]) -> List[str]:
    seen = set()
    out = []
    for s in seq:
        if s is None:
            continue
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


# -----------------------
# Main parser
# -----------------------
def parse_backend(raw: pd.DataFrame) -> BackendData:
    """
    Parse the BACKEND CSV (raw DataFrame).
    Returns BackendData with added sites, sub_categories, and units_map.
    """
    df = raw.copy().reset_index(drop=True)
    rows_text = [_row_to_text(df.iloc[i]) for i in range(len(df))]
    blank_mask = [_is_blank_row(df.iloc[i]) for i in range(len(df))]

    # ---------------------
    # 1) Load Factor
    # ---------------------
    lf_header_idx = _find_first_row_containing(rows_text, "sub category")
    if lf_header_idx is None:
        load_factor_title_idx = _find_first_row_containing(rows_text, "load factor")
        if load_factor_title_idx is not None:
            j = load_factor_title_idx + 1
            while j < len(df) and blank_mask[j]:
                j += 1
            lf_header_idx = j if j < len(df) else None
    if lf_header_idx is None:
        lf_header_idx = _find_first_row_matching_any(rows_text, ["load mechanic", "load electrician", "load welder"], start=0)

    lf_end_idx = None
    if lf_header_idx is not None:
        j = lf_header_idx + 1
        while j < len(df) and not blank_mask[j]:
            if "ratio shift" in rows_text[j]:
                break
            j += 1
        lf_end_idx = j

    lf_df = pd.DataFrame()
    if lf_header_idx is not None and lf_end_idx is not None and lf_end_idx > lf_header_idx:
        header_row = df.iloc[lf_header_idx].astype(str).tolist()
        col_names = [str(c).strip() for c in header_row]
        lf_rows = df.iloc[lf_header_idx + 1:lf_end_idx].copy()
        # Ensure columns match; if mismatch, create generic headers
        if lf_rows.shape[1] != len(col_names):
            col_names = [f"col_{i}" for i in range(lf_rows.shape[1])]
        lf_rows.columns = col_names
        # Clean empty column names
        lf_rows.columns = [c if str(c).strip() != "" else f"col_{i}" for i, c in enumerate(lf_rows.columns)]

        # Preserve textual columns (first two usually: Sub Category, Attribute)
        lf_df = lf_rows.copy()

        # Detect which columns should be textual: look for names containing 'sub' or 'attribute'
        lower_cols = [str(c).strip().lower() for c in lf_df.columns]
        text_cols_idx = set()
        for idx, cname in enumerate(lower_cols):
            if "sub" in cname or "category" in cname or "attr" in cname:
                text_cols_idx.add(idx)
        # fallback: first two columns textual
        if not text_cols_idx:
            text_cols_idx.update({0, 1} if lf_df.shape[1] >= 2 else {0})

        # Convert numeric columns (those not in text_cols_idx) safely
        for idx, col in enumerate(lf_df.columns):
            if idx in text_cols_idx:
                # ensure string type and strip whitespace
                lf_df[col] = lf_df[col].apply(lambda v: "" if pd.isna(v) else str(v).strip())
            else:
                lf_df[col] = lf_df[col].apply(lambda v: (_safe_float(v) if isinstance(v, str) or pd.isna(v) else (float(v) if not pd.isna(v) else math.nan)))
    else:
        logger.warning("Load Factor block not found or empty")

    # ---------------------
    # 2) Ratio Shift
    # ---------------------
    ratio_shift = {}
    rs_title_idx = _find_first_row_containing(rows_text, "ratio shift")
    if rs_title_idx is not None:
        j = rs_title_idx + 1
        while j < len(df) and blank_mask[j]:
            j += 1
        if j < len(df):
            if "site" in rows_text[j] or "ratio" in rows_text[j]:
                rs_header_idx = j
                j2 = rs_header_idx + 1
                while j2 < len(df) and not blank_mask[j2]:
                    if "proporsi raci" in rows_text[j2] or rows_text[j2].strip().startswith("proporsi") or "raci" in rows_text[j2]:
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
    else:
        logger.debug("Ratio Shift title not found")

    # ---------------------
    # 3) RACI
    # ---------------------
    raci = {}
    raci_title_idx = _find_first_row_containing(rows_text, "proporsi raci")
    if raci_title_idx is None:
        raci_title_idx = _find_first_row_containing(rows_text, "raci")
    raci_table_end_idx = raci_title_idx
    if raci_title_idx is not None:
        j = raci_title_idx + 1
        while j < len(df) and not blank_mask[j]:
            txt = rows_text[j]
            roles = ["mechanic", "electric", "welder", "electrician"]
            found_role = None
            for r in roles:
                if r in txt:
                    found_role = r
                    break
            row_cells = df.iloc[j].tolist()
            val = None
            if len(row_cells) >= 2 and not pd.isna(row_cells[1]) and str(row_cells[1]).strip() != "":
                val = _parse_percent_cell(row_cells[1])
            elif found_role:
                for c in row_cells[1:]:
                    if not pd.isna(c) and str(c).strip() != "":
                        maybe = _parse_percent_cell(c)
                        if not math.isnan(maybe):
                            val = maybe
                            break
            if found_role:
                name = "electrician" if found_role in ("electric", "electrician") else found_role
                raci[name] = val if val is not None else math.nan
            j += 1
        raci_table_end_idx = j
    else:
        logger.debug("RACI block not found")

    # ---------------------
    # 4) Split Ratio blocks
    # ---------------------
    def _extract_split_after(role_keyword: str, after_idx: int) -> List[float]:
        target = None
        for i in range(after_idx + 1, len(df)):
            rt = rows_text[i]
            if ("split ratio" in rt and role_keyword in rt) or (f"split ratio {role_keyword}" in rt):
                target = i
                break
        if target is None:
            for i in range(after_idx + 1, len(df)):
                rt = rows_text[i]
                if role_keyword in rt and "split" in rt:
                    target = i
                    break
        if target is None:
            for i in range(after_idx + 1, len(df)):
                first_cell = str(df.iloc[i, 0]) if df.shape[1] >= 1 else ""
                if first_cell.strip().lower() == role_keyword:
                    target = i
                    break
        if target is None:
            logger.debug("Split ratio header for %s not found after row %s", role_keyword, after_idx)
            return []

        results = []
        j = target + 1
        while j < len(df) and not blank_mask[j]:
            row0 = str(df.iloc[j, 0]).strip().lower() if df.shape[1] >= 1 else ""
            if row0.startswith("m") or "%" in rows_text[j] or any(ch.isdigit() for ch in rows_text[j]):
                row_cells = df.iloc[j].tolist()
                numeric_found = False
                for c in row_cells[1:]:
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
                    numeric_found = True
                if not numeric_found:
                    for c in row_cells:
                        if pd.isna(c):
                            continue
                        s = str(c).strip()
                        if s == "":
                            continue
                        v = _parse_percent_cell(s)
                        if not math.isnan(v):
                            results.append(v)
                            numeric_found = True
                        else:
                            v2 = _safe_float(s)
                            if not math.isnan(v2):
                                results.append(v2)
                                numeric_found = True
                j += 1
                continue
            else:
                break
        if len(results) == 0:
            return []
        normed = []
        for v in results:
            if math.isnan(v):
                normed.append(math.nan)
            elif v > 1.0:
                normed.append(v / 100.0)
            else:
                normed.append(v)
        seen = set()
        dedup = []
        for v in normed:
            if math.isnan(v):
                if "nan" in seen:
                    continue
                seen.add("nan")
                dedup.append(v)
            else:
                if v in seen:
                    continue
                seen.add(v)
                dedup.append(v)
        return dedup

    after_raci_idx = raci_table_end_idx if raci_table_end_idx is not None else 0
    split_mechanic = _extract_split_after("mechanic", after_raci_idx)
    split_welder = _extract_split_after("welder", after_raci_idx)
    split_electrician = _extract_split_after("electrician", after_raci_idx)
    if not split_electrician:
        split_electrician = _extract_split_after("electric", after_raci_idx)

    # ---------------------
    # 5) Lost Time
    # ---------------------
    lost_time = {}
    lt_title_idx = _find_first_row_containing(rows_text, "lost time")
    if lt_title_idx is not None:
        j = lt_title_idx + 1
        while j < len(df) and blank_mask[j]:
            j += 1
        if j < len(df) and ("site" in rows_text[j] or "lost time" in rows_text[j]):
            start_parse = j + 1
        else:
            start_parse = j
        k = start_parse
        while k < len(df) and not blank_mask[k]:
            row_cells = df.iloc[k].tolist()
            site = None
            val = None
            if len(row_cells) >= 1 and not pd.isna(row_cells[0]) and str(row_cells[0]).strip() != "":
                site = str(row_cells[0]).strip()
            if len(row_cells) >= 2 and not pd.isna(row_cells[1]) and str(row_cells[1]).strip() != "":
                val = _safe_float(row_cells[1])
            if site:
                lost_time[site] = val if val is not None else math.nan
            k += 1
    else:
        logger.debug("Lost Time block not present")

    # Ensure raci keys exist
    for k in ("mechanic", "electrician", "welder"):
        if k not in raci:
            raci[k] = math.nan

    # ---------------------
    # Compute sites list & sub_categories & units_map
    # ---------------------
    sites = list(ratio_shift.keys()) if ratio_shift else list(lost_time.keys())

    # Build sub_categories and units_map from lf_df (if present)
    sub_categories = []
    units_map: Dict[str, List[str]] = {}
    if not lf_df.empty:
        # Find which column is sub category and which is attribute
        lower_cols = [str(c).strip().lower() for c in lf_df.columns]
        sub_col = None
        attr_col = None
        for idx, cname in enumerate(lower_cols):
            if "sub" in cname or "category" in cname:
                sub_col = lf_df.columns[idx]
            if "attr" in cname or "attribute" in cname or "jenis" in cname or "jenis unit" in cname:
                attr_col = lf_df.columns[idx]
        # Fallback to first two columns
        if sub_col is None:
            sub_col = lf_df.columns[0] if lf_df.shape[1] >= 1 else None
        if attr_col is None:
            attr_col = lf_df.columns[1] if lf_df.shape[1] >= 2 else None

        if sub_col is not None:
            # Extract values preserving order
            raw_subs = lf_df[sub_col].astype(str).apply(lambda s: s.strip()).tolist()
            # Remove empty/blank
            raw_subs = [s for s in raw_subs if s and s.lower() != "nan"]
            sub_categories = _unique_preserve(raw_subs)

            # Build units_map if attribute column exists
            if attr_col is not None:
                for idx, sub in enumerate(lf_df[sub_col].astype(str).apply(lambda s: s.strip()).tolist()):
                    if not sub or sub.lower() == "nan":
                        continue
                    sub = sub
                    attr_val = ""
                    try:
                        attr_val = str(lf_df.iloc[idx][attr_col]).strip()
                    except Exception:
                        attr_val = ""
                    if not attr_val or attr_val.lower() == "nan":
                        continue
                    units_map.setdefault(sub, []).append(attr_val)
                # Deduplicate preserving order for each list
                for k in list(units_map.keys()):
                    units_map[k] = _unique_preserve(units_map[k])
    else:
        logger.debug("Load Factor DataFrame empty; sub_categories and units_map empty")

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
    )


# -----------------------
# Loader with fallbacks
# -----------------------
def load_backend_data(source: Optional[Union[str, pd.DataFrame]] = None) -> BackendData:
    """
    Load backend data from:
     - pandas.DataFrame (if provided)
     - str path or URL (if provided)
     - None: try env var BACKEND_CSV_PATH, then BACKEND_CSV_URL, then default file name,
             then Google Sheets export URL.

    Returns BackendData or raises BackendDataError.
    """
    GOOGLE_SHEET_ID = "1YRvXt0AE-dVBVwRvLtsb57Qz8DYd9YbVQlVbRD31C7I"
    GOOGLE_SHEET_GID = "1437049322"
    google_export_url = f"https://docs.google.com/spreadsheets/d/{GOOGLE_SHEET_ID}/export?format=csv&gid={GOOGLE_SHEET_GID}"

    try:
        if isinstance(source, pd.DataFrame):
            raw = source
            return parse_backend(raw)

        if isinstance(source, str):
            src = source.strip()
            try:
                raw = pd.read_csv(src, header=None, dtype=str)
            except Exception as e:
                logger.debug("Failed reading source %r via pandas: %s", src, e)
                raise BackendDataError(f"Failed to read CSV from {src}") from e
            return parse_backend(raw)

        # try env var path
        env_path = os.getenv("BACKEND_CSV_PATH")
        if env_path:
            try:
                raw = pd.read_csv(env_path, header=None, dtype=str)
                return parse_backend(raw)
            except Exception as e:
                logger.warning("Failed to read BACKEND_CSV_PATH=%r: %s", env_path, e)

        # try env var URL
        env_url = os.getenv("BACKEND_CSV_URL")
        if env_url:
            try:
                raw = pd.read_csv(env_url, header=None, dtype=str)
                return parse_backend(raw)
            except Exception as e:
                logger.warning("Failed to read BACKEND_CSV_URL=%r: %s", env_url, e)

        # try default local filename
        default_fname = "FTE - BACKEND (2).csv"
        if os.path.exists(default_fname):
            try:
                raw = pd.read_csv(default_fname, header=None, dtype=str)
                return parse_backend(raw)
            except Exception as e:
                logger.warning("Failed to read default CSV %r: %s", default_fname, e)

        # try Google Sheets export URL
        try:
            raw = pd.read_csv(google_export_url, header=None, dtype=str)
            return parse_backend(raw)
        except Exception as e:
            logger.exception("Failed to fetch Google Sheets export CSV from %s", google_export_url)

        raise BackendDataError(
            "Could not load BACKEND CSV: tried BACKEND_CSV_PATH, BACKEND_CSV_URL, "
            f"default file {default_fname}, and Google Sheets export URL."
        )

    except BackendDataError:
        raise
    except Exception as e:
        logger.exception("Unexpected error in load_backend_data")
        raise BackendDataError("Unexpected error loading backend data") from e
