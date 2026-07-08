"""
data_loader.py

Robust parser for the 'BACKEND' sheet exported as CSV into a pandas.DataFrame.

Usage:
    raw = pd.read_csv(csv_path, header=None, dtype=str)  # or however you produce raw
    backend = parse_backend(raw)

The parser:
 - Does NOT use hard-coded row indices.
 - Finds blocks by searching text (case-insensitive, strip).
 - Ensures split-ratio searches start after the end of the RACI block to avoid collisions.
 - Converts numeric strings safely (handles "2,0", "68%", "", NaN, etc).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
import math
import logging

logger = logging.getLogger(__name__)


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
    """
    Join all cells of a row into a single lowercase stripped string for robust searching.
    """
    # Convert NaN -> ''
    parts = []
    for c in row.tolist():
        if pd.isna(c):
            parts.append("")
        else:
            parts.append(str(c))
    joined = " ".join(parts)
    return joined.strip().lower()


def _is_blank_row(row: pd.Series) -> bool:
    """
    True if every cell is NaN/empty/whitespace.
    """
    for c in row.tolist():
        if pd.isna(c):
            continue
        if str(c).strip() != "":
            return False
    return True


def _safe_float(value: Optional[str]) -> float:
    """
    Convert a string like "2,0", "68%", "  ", None -> float.
    Returns math.nan for invalid/empty values.
    """
    if value is None:
        return math.nan
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)
    s = str(value).strip()
    if s == "" or s.lower() in {"nan", "none"}:
        return math.nan
    # remove % and replace comma decimal
    s = s.replace("%", "").replace(" ", "")
    # If European decimal like "1,5" -> convert to "1.5". But be careful about thousands sep.
    # Heuristic: if there is exactly one comma and no dots, treat comma as decimal sep.
    if "," in s and "." not in s and s.count(",") == 1:
        s = s.replace(",", ".")
    # Remove thousands separators if present (commas in 1,234.56 style).
    # After above, dots may remain as decimal sep; remove stray commas.
    s = s.replace(",", "")
    try:
        return float(s)
    except Exception:
        logger.debug("Could not parse float from %r", value)
        return math.nan


def _parse_percent_cell(cell: Optional[str]) -> float:
    """
    Parse a cell that contains a percent like '68%' or ' 68 % ' -> 0.68 or return raw float?
    We'll return absolute fraction (0.68).
    """
    if cell is None:
        return math.nan
    s = str(cell).strip()
    if s == "":
        return math.nan
    # If contains %, parse and divide by 100
    if "%" in s:
        v = _safe_float(s)
        if math.isnan(v):
            return math.nan
        return v / 100.0
    # If looks like decimal >1 (e.g., '68' maybe percent missing) - we cannot be sure.
    # We'll assume values >1 are percents and divide by 100, else return as-is.
    v = _safe_float(s)
    if math.isnan(v):
        return math.nan
    if v > 1.0:
        return v / 100.0
    return v


# -----------------------
# Searching helpers
# -----------------------
def _find_first_row_containing(rows_text: List[str], keyword: str, start: int = 0) -> Optional[int]:
    """
    Returns index of first row where keyword (single word or phrase) occurs in rows_text.
    Case-insensitive; rows_text should already be lowercased strings.
    """
    kw = keyword.strip().lower()
    for i in range(start, len(rows_text)):
        if kw in rows_text[i]:
            return i
    return None


def _find_first_row_matching_any(rows_text: List[str], keywords: List[str], start: int = 0) -> Optional[int]:
    """
    Return first index where any of keywords is found.
    """
    for i in range(start, len(rows_text)):
        for kw in keywords:
            if kw.strip().lower() in rows_text[i]:
                return i
    return None


# -----------------------
# Main parser
# -----------------------
def parse_backend(raw: pd.DataFrame) -> BackendData:
    """
    Parse the BACKEND CSV (loaded into DataFrame raw, header=None or arbitrary).
    Returns BackendData with parsed pieces.

    The function is robust to additional blank lines and small re-orderings,
    and avoids hard-coded row numbers.
    """
    # Defensive copy
    df = raw.copy().reset_index(drop=True)

    # Build helper text lines: joined row string and detect blank rows quickly
    rows_text = [_row_to_text(df.iloc[i]) for i in range(len(df))]
    blank_mask = [_is_blank_row(df.iloc[i]) for i in range(len(df))]

    # ---------------------
    # 1) Load Factor block
    # ---------------------
    # Find header row: prefer the row that contains "sub category" or "subcategory"
    lf_header_idx = _find_first_row_containing(rows_text, "sub category")
    # If not found, try to locate "load factor" then assume header is next nonblank row
    if lf_header_idx is None:
        load_factor_title_idx = _find_first_row_containing(rows_text, "load factor")
        if load_factor_title_idx is not None:
            # header is the next non-blank row after the title
            j = load_factor_title_idx + 1
            while j < len(df) and blank_mask[j]:
                j += 1
            lf_header_idx = j if j < len(df) else None

    if lf_header_idx is None:
        # As a last resort, try to find header row by presence of "load mechanic" or "load electrician"
        lf_header_idx = _find_first_row_matching_any(rows_text, ["load mechanic", "load electrician", "load welder"], start=0)

    # Determine load factor end: next blank row after header or the row containing "ratio shift"
    lf_end_idx = None
    if lf_header_idx is not None:
        j = lf_header_idx + 1
        while j < len(df) and not blank_mask[j]:
            # stop if we hit a likely next-block title
            if "ratio shift" in rows_text[j] or "ratio shift" in rows_text[j]:
                break
            # Also break if a row appears to be the next block title (e.g., contains "ratio shift" or "ratio")
            if "ratio shift" in rows_text[j]:
                break
            j += 1
        lf_end_idx = j

    # Extract load factor DataFrame
    if lf_header_idx is not None and lf_end_idx is not None and lf_end_idx > lf_header_idx:
        # Use the header row to name columns
        header_row = df.iloc[lf_header_idx].astype(str).tolist()
        col_names = [str(c).strip() for c in header_row]
        # slice data rows
        lf_rows = df.iloc[lf_header_idx + 1:lf_end_idx].copy()
        # assign column names (if number mismatch, create generic names)
        if lf_rows.shape[1] != len(col_names):
            # fallback: create generic column names
            col_names = [f"col_{i}" for i in range(lf_rows.shape[1])]
        lf_rows.columns = col_names
        # Clean whitespace-only column names
        lf_rows.columns = [c if str(c).strip() != "" else f"col_{i}" for i, c in enumerate(lf_rows.columns)]
        # Convert numeric-like columns using _safe_float (apply to all columns except first two which are likely categorical)
        lf_df = lf_rows.copy()
        for col in lf_df.columns:
            # Try to parse numbers where possible
            lf_df[col] = lf_df[col].apply(lambda v: (_safe_float(v) if isinstance(v, str) or pd.isna(v) else (float(v) if not pd.isna(v) else math.nan)))
        # Keep original textual columns for first two if they look categorical
        # (we already converted everything to numbers where possible)
    else:
        lf_df = pd.DataFrame()
        logger.warning("Load Factor block not found or empty")

    # ---------------------
    # 2) Ratio Shift block
    # ---------------------
    ratio_shift = {}
    # find "ratio shift" title
    rs_title_idx = _find_first_row_containing(rows_text, "ratio shift")
    if rs_title_idx is not None:
        # find header 'site' row after title
        rs_header_idx = None
        j = rs_title_idx + 1
        while j < len(df) and blank_mask[j]:
            j += 1
        # header likely next non-blank row
        if j < len(df):
            # if the row contains 'site' or 'ratio' treat as header
            if "site" in rows_text[j] or "ratio" in rows_text[j]:
                rs_header_idx = j
                j2 = rs_header_idx + 1
                # collect until blank or next block (proporsi raci)
                while j2 < len(df) and not blank_mask[j2]:
                    # stop if next block title 'proporsi raci' or 'proporsi' or 'raci' found
                    if "proporsi raci" in rows_text[j2] or rows_text[j2].strip().startswith("proporsi") or "raci" in rows_text[j2]:
                        break
                    # append if row looks like 'BCP,"1,51"'
                    row_cells = df.iloc[j2].tolist()
                    # first cell as site, second as value
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
        logger.warning("Ratio Shift title not found")

    # ---------------------
    # 3) RACI block (Proporsi RACI)
    # ---------------------
    raci = {}
    raci_title_idx = _find_first_row_containing(rows_text, "proporsi raci")
    if raci_title_idx is None:
        # try to find "raci" on its own
        raci_title_idx = _find_first_row_containing(rows_text, "raci")
    raci_table_end_idx = raci_title_idx
    if raci_title_idx is not None:
        j = raci_title_idx + 1
        # collect rows while they look like raci lines (contain mechanic/electric/welder or a percent)
        while j < len(df) and not blank_mask[j]:
            txt = rows_text[j]
            # We expect rows like "Mechanic,68%,,,,"
            # Identify role
            roles = ["mechanic", "electric", "welder", "electrician"]
            found_role = None
            for r in roles:
                if r in txt:
                    found_role = r
                    break
            # The second column likely contains percent
            row_cells = df.iloc[j].tolist()
            val = None
            if len(row_cells) >= 2 and not pd.isna(row_cells[1]) and str(row_cells[1]).strip() != "":
                val = _parse_percent_cell(row_cells[1])
            elif found_role:
                # fallback: try to look through other columns for percent
                for c in row_cells[1:]:
                    if not pd.isna(c) and str(c).strip() != "":
                        maybe = _parse_percent_cell(c)
                        if not math.isnan(maybe):
                            val = maybe
                            break
            if found_role:
                # canonicalize name
                name = "electrician" if found_role == "electrician" or found_role == "electric" else found_role
                raci[name] = val if val is not None else math.nan
            j += 1
        raci_table_end_idx = j
    else:
        logger.warning("RACI block not found")

    # ---------------------
    # 4) Split Ratio blocks (Mechanic, Welder, Electrician)
    # Strategy: search for "split ratio" with role or fallback to role keyword
    # But to avoid collision with RACI names, we start searching after raci_table_end_idx.
    # ---------------------
    def _extract_split_after(role_keyword: str, after_idx: int) -> List[float]:
        """
        Find the split ratio section for role_keyword after after_idx.
        Return list of floats (fractions, e.g., 0.2, 0.3, 0.5) or empty list if not found.
        """
        # Find a header row that mentions both 'split' and role OR contains 'split ratio <role>'
        target = None
        for i in range(after_idx + 1, len(df)):
            rt = rows_text[i]
            if ("split ratio" in rt and role_keyword in rt) or (f"split ratio {role_keyword}" in rt):
                target = i
                break
        # fallback: find row that contains role_keyword and 'split' anywhere in row text
        if target is None:
            for i in range(after_idx + 1, len(df)):
                rt = rows_text[i]
                if role_keyword in rt and "split" in rt:
                    target = i
                    break
        # fallback 2: find a row where first cell == role_keyword (but ensure index > after_idx)
        if target is None:
            for i in range(after_idx + 1, len(df)):
                first_cell = str(df.iloc[i, 0]) if df.shape[1] >= 1 else ""
                if first_cell.strip().lower() == role_keyword:
                    target = i
                    break

        if target is None:
            logger.debug("Split ratio header for %s not found after row %s", role_keyword, after_idx)
            return []

        # Now, scan subsequent rows to collect lines starting with M or containing percent numbers
        results = []
        j = target + 1
        while j < len(df) and not blank_mask[j]:
            row0 = str(df.iloc[j, 0]).strip().lower() if df.shape[1] >= 1 else ""
            # if row starts with M1/M2/M3 or contains percent values, use it
            if row0.startswith("m") or "%" in rows_text[j] or any(ch.isdigit() for ch in rows_text[j]):
                # Collect numeric values in this row (from col1 onward preferably, but try all)
                row_cells = df.iloc[j].tolist()
                # prefer numeric cells from col1 onwards
                numeric_found = False
                for c in row_cells[1:]:
                    if pd.isna(c):
                        continue
                    s = str(c).strip()
                    if s == "":
                        continue
                    # attempt percent parse first
                    v = _parse_percent_cell(s)
                    if math.isnan(v):
                        # attempt general float parse
                        v = _safe_float(s)
                        if math.isnan(v):
                            continue
                    results.append(v)
                    numeric_found = True
                # if nothing in col1..n, perhaps the value is in col0 after 'M1,' e.g. "M1,20%,,,,"
                if not numeric_found:
                    # try to scan entire row
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
                # if we parsed numeric values and row looks like a 'M' row, continue to next M row
                j += 1
                # continue collecting as long as rows are M* or contain percent
                continue
            else:
                # if the next row is a block title (like "split ratio welder") or other header, stop
                break
        # Post-process results: deduplicate/truncate where necessary
        if len(results) == 0:
            return []
        # If results appear as raw percents or decimals greater than 1, normalize:
        normed = []
        for v in results:
            if math.isnan(v):
                normed.append(math.nan)
            elif v > 1.0:
                # assume v is percent expressed as e.g. 20 -> 0.2
                normed.append(v / 100.0)
            else:
                normed.append(v)
        # Keep unique while preserving order
        seen = set()
        dedup = []
        for v in normed:
            # treat nan specially: keep only one nan if present
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
    # Some sheets use 'electric' instead of 'electrician'
    if not split_electrician:
        split_electrician = _extract_split_after("electric", after_raci_idx)

    # ---------------------
    # 5) Lost Time block
    # ---------------------
    lost_time = {}
    lt_title_idx = _find_first_row_containing(rows_text, "lost time")
    if lt_title_idx is not None:
        # header likely next non-blank row containing 'site'
        j = lt_title_idx + 1
        while j < len(df) and blank_mask[j]:
            j += 1
        # parse subsequent non-empty rows until blank
        j2 = j + 1
        # If j row is header, then start from j+1; else start from j
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
        logger.info("Lost Time block not present")

    # Final: if raci percentages were parsed as fractions, ensure they are numeric floats (0..1)
    # Already _parse_percent_cell returned fraction (0.68) where possible.
    # Ensure keys are standardized: mechanic, electrician, welder
    # Provide defaults if missing
    for k in ("mechanic", "electrician", "welder"):
        if k not in raci:
            raci[k] = math.nan

    # Return structured object
    return BackendData(
        load_factor=lf_df,
        ratio_shift=ratio_shift,
        raci=raci,
        split_mechanic=split_mechanic,
        split_welder=split_welder,
        split_electrician=split_electrician,
        lost_time=lost_time,
    )
