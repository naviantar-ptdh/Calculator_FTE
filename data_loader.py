# data_loader.py
"""
Robust BACKEND CSV parser for Calculator_FTE.

Provides:
 - BackendData dataclass
 - BackendDataError exception
 - load_backend_data(source)  -> BackendData
 - parse_backend(raw: pd.DataFrame) -> BackendData

Usage examples:
    from data_loader import load_backend_data, BackendDataError
    try:
        backend = load_backend_data("FTE - BACKEND (2).csv")
    except BackendDataError as e:
        # handle error
        raise
"""
from dataclasses import dataclass
from typing import Dict, List, Optional, Union
import pandas as pd
import math
import logging

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
    # treat single comma as decimal separator if no dot present
    if "," in s and "." not in s and s.count(",") == 1:
        s = s.replace(",", ".")
    # remove thousands commas remaining
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


def parse_backend(raw: pd.DataFrame) -> BackendData:
    try:
        df = raw.copy().reset_index(drop=True)
        rows_text = [_row_to_text(df.iloc[i]) for i in range(len(df))]
        blank_mask = [_is_blank_row(df.iloc[i]) for i in range(len(df))]

        # 1) Load Factor
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

        if lf_header_idx is not None and lf_end_idx is not None and lf_end_idx > lf_header_idx:
            header_row = df.iloc[lf_header_idx].astype(str).tolist()
            col_names = [str(c).strip() for c in header_row]
            lf_rows = df.iloc[lf_header_idx + 1:lf_end_idx].copy()
            if lf_rows.shape[1] != len(col_names):
                col_names = [f"col_{i}" for i in range(lf_rows.shape[1])]
            lf_rows.columns = col_names
            lf_rows.columns = [c if str(c).strip() != "" else f"col_{i}" for i, c in enumerate(lf_rows.columns)]
            lf_df = lf_rows.copy()
            for col in lf_df.columns:
                lf_df[col] = lf_df[col].apply(lambda v: (_safe_float(v) if isinstance(v, str) or pd.isna(v) else (float(v) if not pd.isna(v) else math.nan)))
        else:
            lf_df = pd.DataFrame()
            logger.warning("Load Factor block not found or empty")

        # 2) Ratio Shift
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

        # 3) RACI
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

        # 4) Split Ratios (search after raci_table_end_idx to avoid collisions)
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

        # 5) Lost Time
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

        for k in ("mechanic", "electrician", "welder"):
            if k not in raci:
                raci[k] = math.nan

        return BackendData(
            load_factor=lf_df,
            ratio_shift=ratio_shift,
            raci=raci,
            split_mechanic=split_mechanic,
            split_welder=split_welder,
            split_electrician=split_electrician,
            lost_time=lost_time,
        )

    except Exception as e:
        logger.exception("Failed to parse backend data")
        raise BackendDataError("Failed to parse backend data") from e


def load_backend_data(source: Union[str, pd.DataFrame]) -> BackendData:
    """
    Load backend data either from:
     - a file path to CSV (str)
     - a pandas.DataFrame (already loaded)

    The CSV should be the Google Sheets export of the BACKEND tab (no header or arbitrary header).
    """
    try:
        if isinstance(source, pd.DataFrame):
            raw = source
        elif isinstance(source, str):
            # read CSV defensively: no header, all strings
            raw = pd.read_csv(source, header=None, dtype=str)
        else:
            raise BackendDataError("Unsupported source type for load_backend_data")
        return parse_backend(raw)
    except BackendDataError:
        raise
    except Exception as e:
        logger.exception("Error loading backend data from source=%r", source)
        raise BackendDataError("Error loading backend data") from e
