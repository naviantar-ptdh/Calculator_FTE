# data_loader.py
"""
BACKEND CSV/XLSX loader + parser — versi dinamis, anti hardcoded-row-index.

Struktur sheet BACKEND (Kolom A berisi judul seksi UNIK, dicari via scanning teks,
bukan nomor baris):

    Blok 1: "Load Factor"
        -> header berikutnya: Sub Category | Attribute | Load Mechanic | Load Electrican | Load Welder
        -> baris data sampai ketemu baris kosong

    Blok 2: "Ratio Shift"
        -> header berikutnya (opsional): Site | Ratio
        -> baris data Site,Ratio sampai baris kosong

    Blok 3: "Proporsi RACI"
        -> baris vertikal langsung di bawah judul: label di Kolom A
           ("Mechanic" / "Electric(ian)" / "Welder"), nilai di Kolom B
        -> sampai baris kosong

    Blok 4: "Split Ratio Mechanic"
        -> baris vertikal (M1/M2/M3, nilai di Kolom B) sampai baris kosong

    Blok 5: "Split Ratio Welder"
        -> baris vertikal (M1/M2, nilai di Kolom B) sampai baris kosong

    Blok 6: "Split Ratio Electrician"
        -> baris vertikal (M1/M2, nilai di Kolom B) sampai baris kosong

    Blok 7: "Lost Time"
        -> baris data Site,Value sampai baris kosong / akhir file

Prinsip desain:
 - TIDAK ADA nomor baris hardcoded di mana pun. Semua seksi dicari dengan
   mencocokkan teks Kolom A (case-insensitive, di-strip) terhadap judul seksi.
 - Pencarian Split Ratio dimulai SETELAH blok RACI selesai (raci_end_idx),
   supaya urut dan tidak pernah salah tabrakan walau ada perubahan sheet di masa depan.
 - `load_factor` diberi index = Sub Category (bukan RangeIndex default!) supaya
   `backend.load_factor.loc[sub_category]` di calculator.py benar-benar bekerja.
 - Key dict `raci` distandardisasi menjadi persis "Mechanic" / "Electric" / "Welder"
   (sesuai config.ROLES dan apa yang dipakai calculator.py) — bukan "mechanic"/"electrician".
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union
import pandas as pd
import math
import logging
import os
import re

logger = logging.getLogger(__name__)


class BackendDataError(Exception):
    """Raised when backend data cannot be loaded or parsed cleanly."""
    pass


@dataclass
class BackendData:
    load_factor: pd.DataFrame                                       # index = Sub Category
    ratio_shift: Dict[str, float]                                    # Site -> ratio
    raci: Dict[str, float]                                           # "Mechanic"/"Electric"/"Welder" -> fraction
    split_mechanic: List[float]                                      # [M1, M2, M3]
    split_welder: List[float]                                        # [M1, M2]
    split_electrician: List[float]                                   # [M1, M2]
    lost_time: Dict[str, float]                                      # Site -> jam
    sites: List[str]
    sub_categories: List[str] = field(default_factory=list)          # untuk dropdown UI
    units_map: Dict[str, List[str]] = field(default_factory=dict)    # canonical sub -> [Attribute,...]
    _norm_to_orig: Dict[str, str] = field(default_factory=dict)      # canonical -> original Sub Category

    def first_site(self) -> Optional[str]:
        return self.sites[0] if self.sites else None

    @staticmethod
    def _normalize(s: Optional[str]) -> str:
        if s is None:
            return ""
        s = str(s).strip().lower()
        s = re.sub(r"\s+", " ", s)
        s = re.sub(r"[^\w\s]", "", s)
        return s

    def units_for(self, sub_category_input: Optional[str]) -> List[str]:
        if not sub_category_input:
            return []
        return self.units_map.get(self._normalize(sub_category_input), [])

    def original_sub_name(self, sub_category_input: Optional[str]) -> Optional[str]:
        """Cocokkan input (bebas huruf besar/kecil, spasi) ke nama asli di load_factor.index."""
        if not sub_category_input:
            return None
        nk = self._normalize(sub_category_input)
        if self._norm_to_orig:
            hit = self._norm_to_orig.get(nk)
            if hit:
                return hit
        for orig in self.sub_categories or []:
            if self._normalize(orig) == nk:
                return orig
        return None


# -----------------------
# Helper utilities
# -----------------------
def _cell(df: pd.DataFrame, r: int, c: int):
    if r < 0 or r >= len(df) or c < 0 or c >= df.shape[1]:
        return None
    v = df.iat[r, c]
    return None if pd.isna(v) else v


def _col_text(df: pd.DataFrame, r: int, c: int = 0) -> str:
    v = _cell(df, r, c)
    return "" if v is None else str(v).strip()


def _is_blank_row(df: pd.DataFrame, r: int) -> bool:
    if r >= len(df):
        return True
    for c in df.iloc[r].tolist():
        if pd.isna(c):
            continue
        if str(c).strip() != "":
            return False
    return True


def _safe_float(value) -> float:
    """Konversi ke float secara aman. Mengembalikan math.nan jika gagal.
    Menerima '1,5', '68%', '  ', None, tipe numerik."""
    if value is None:
        return math.nan
    if isinstance(value, (int, float)) and not pd.isna(value):
        return float(value)
    s = str(value).strip()
    if s == "" or s.lower() in {"nan", "none", "-"}:
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


def _parse_fraction_cell(cell) -> float:
    """Parse sel yang merepresentasikan proporsi/pecahan (mis. RACI, Split Ratio).
    Menerima '68%', '0.68', '68', '1,5' dll. Heuristik: nilai > 1 dianggap persen."""
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


def _find_title_row(df: pd.DataFrame, title: str, start: int = 0) -> Optional[int]:
    """Cari baris yang Kolom A-nya PERSIS sama dengan judul seksi (case/space-insensitive)."""
    t = title.strip().lower()
    for i in range(start, len(df)):
        if _col_text(df, i, 0).strip().lower() == t:
            return i
    return None


def _read_vertical_pairs_safe(df: pd.DataFrame, start_row: int):
    """Baca pasangan (label_kolomA, nilai_kolomB) mulai dari start_row sampai baris kosong.
    Mengembalikan (list_pairs, baris_setelah_blok)."""
    pairs = []
    r = start_row
    while r < len(df) and not _is_blank_row(df, r):
        label = _col_text(df, r, 0)
        val = _cell(df, r, 1)
        if label:
            pairs.append((label, val))
        r += 1
    return pairs, r


# -----------------------
# Main parser
# -----------------------
def parse_backend(raw: pd.DataFrame) -> BackendData:
    df = raw.copy().reset_index(drop=True)

    # =========================================================
    # Blok 1: Load Factor
    # =========================================================
    lf_title_idx = _find_title_row(df, "load factor")
    if lf_title_idx is None:
        raise BackendDataError("Seksi 'Load Factor' tidak ditemukan di Kolom A BACKEND.")

    header_idx = lf_title_idx + 1
    while header_idx < len(df) and _is_blank_row(df, header_idx):
        header_idx += 1
    if header_idx >= len(df):
        raise BackendDataError("Header tabel 'Load Factor' tidak ditemukan.")

    header_cells = [str(x).strip() if not pd.isna(x) else "" for x in df.iloc[header_idx].tolist()]
    header_lower = [h.lower() for h in header_cells]

    def _find_col(*keywords) -> Optional[int]:
        for idx, h in enumerate(header_lower):
            if all(kw in h for kw in keywords):
                return idx
        return None

    col_sub = _find_col("sub")
    col_attr = _find_col("attribute")
    col_mech = _find_col("mechanic")
    col_elec = _find_col("electr")  # menangkap "Electrican"/"Electrician" (typo aman)
    col_weld = _find_col("welder")

    if col_sub is None:
        raise BackendDataError("Kolom 'Sub Category' tidak ditemukan pada header Load Factor.")

    data_start = header_idx + 1
    data_end = data_start
    while data_end < len(df) and not _is_blank_row(df, data_end):
        data_end += 1

    lf_records = []
    for r in range(data_start, data_end):
        sub = _col_text(df, r, col_sub)
        if not sub or sub.lower() == "nan":
            continue
        rec = {
            "Sub Category": sub,
            "Attribute": _col_text(df, r, col_attr) if col_attr is not None else "",
            "Load Mechanic": _safe_float(_cell(df, r, col_mech)) if col_mech is not None else math.nan,
            "Load Electrican": _safe_float(_cell(df, r, col_elec)) if col_elec is not None else math.nan,
            "Load Welder": _safe_float(_cell(df, r, col_weld)) if col_weld is not None else math.nan,
        }
        lf_records.append(rec)

    if not lf_records:
        raise BackendDataError("Tabel 'Load Factor' ditemukan tapi tidak ada baris data.")

    lf_df = pd.DataFrame(lf_records)
    # Buang duplikat Sub Category (pertahankan kemunculan pertama) lalu jadikan index.
    dupes = lf_df["Sub Category"][lf_df["Sub Category"].duplicated()].unique().tolist()
    if dupes:
        logger.warning("Sub Category duplikat di Load Factor (dipertahankan yang pertama): %s", dupes)
    lf_df = lf_df.drop_duplicates(subset="Sub Category", keep="first").set_index("Sub Category")

    sub_categories = lf_df.index.tolist()

    # units_map / norm map (dipakai app.py untuk dropdown & original_sub_name)
    units_map: Dict[str, List[str]] = {}
    norm_to_orig: Dict[str, str] = {}
    for sub, row in lf_df.iterrows():
        nk = BackendData._normalize(sub)
        norm_to_orig.setdefault(nk, sub)
        attr_val = str(row.get("Attribute", "")).strip()
        if attr_val and attr_val.lower() not in ("nan", "-", ""):
            units_map.setdefault(nk, [])
            if attr_val not in units_map[nk]:
                units_map[nk].append(attr_val)

    # =========================================================
    # Blok 2: Ratio Shift
    # =========================================================
    ratio_shift: Dict[str, float] = {}
    rs_title_idx = _find_title_row(df, "ratio shift", start=data_end)
    if rs_title_idx is not None:
        j = rs_title_idx + 1
        while j < len(df) and _is_blank_row(df, j):
            j += 1
        # skip baris header "Site | Ratio" jika ada
        if j < len(df) and "site" in _col_text(df, j, 0).lower():
            j += 1
        pairs, rs_end = _read_vertical_pairs_safe(df, j)
        for site, val in pairs:
            ratio_shift[site] = _safe_float(val)
    else:
        logger.warning("Seksi 'Ratio Shift' tidak ditemukan.")
        rs_end = data_end

    # =========================================================
    # Blok 3: Proporsi RACI (vertikal: label di Kol A, nilai di Kol B)
    # =========================================================
    raci: Dict[str, float] = {}
    raci_title_idx = _find_title_row(df, "proporsi raci", start=rs_end)
    if raci_title_idx is None:
        raci_title_idx = _find_title_row(df, "raci", start=rs_end)

    raci_end_idx = rs_end
    if raci_title_idx is not None:
        pairs, raci_end_idx = _read_vertical_pairs_safe(df, raci_title_idx + 1)
        for label, val in pairs:
            ll = label.strip().lower()
            if ll.startswith("mechanic"):
                key = "Mechanic"
            elif ll.startswith("electr"):
                key = "Electric"
            elif ll.startswith("welder"):
                key = "Welder"
            else:
                continue
            raci[key] = _parse_fraction_cell(val)
    else:
        logger.warning("Seksi 'Proporsi RACI' tidak ditemukan.")

    for key in ("Mechanic", "Electric", "Welder"):
        raci.setdefault(key, math.nan)

    # =========================================================
    # Blok 4-6: Split Ratio Mechanic / Welder / Electrician
    # Pencarian dimulai SETELAH blok RACI selesai (raci_end_idx), sesuai urutan sheet.
    # =========================================================
    def _extract_split(section_title: str, start: int) -> List[float]:
        title_idx = _find_title_row(df, section_title, start=start)
        if title_idx is None:
            logger.warning("Seksi '%s' tidak ditemukan.", section_title)
            return []
        pairs, _end = _read_vertical_pairs_safe(df, title_idx + 1)
        values = []
        for _label, val in pairs:
            v = _parse_fraction_cell(val)
            if not math.isnan(v):
                values.append(v)
        return values

    split_mechanic = _extract_split("split ratio mechanic", raci_end_idx)
    split_welder = _extract_split("split ratio welder", raci_end_idx)
    split_electrician = _extract_split("split ratio electrician", raci_end_idx)

    # =========================================================
    # Blok 7: Lost Time
    # =========================================================
    lost_time: Dict[str, float] = {}
    lt_title_idx = _find_title_row(df, "lost time", start=raci_end_idx)
    if lt_title_idx is not None:
        j = lt_title_idx + 1
        while j < len(df) and _is_blank_row(df, j):
            j += 1
        if j < len(df) and "site" in _col_text(df, j, 0).lower():
            j += 1
        pairs, _end = _read_vertical_pairs_safe(df, j)
        for site, val in pairs:
            lost_time[site] = _safe_float(val)
    else:
        logger.warning("Seksi 'Lost Time' tidak ditemukan.")

    sites = list(ratio_shift.keys()) or list(lost_time.keys())

    bd = BackendData(
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
    return bd


# -----------------------
# Loader dengan fallback sumber
# -----------------------
def load_backend_data(source: Optional[Union[str, pd.DataFrame]] = None) -> BackendData:
    """
    Urutan sumber data:
     1. DataFrame langsung (jika diberikan)
     2. str path/URL (jika diberikan)
     3. env var BACKEND_CSV_PATH
     4. env var BACKEND_CSV_URL
     5. file lokal default "FTE - BACKEND (2).csv"
     6. Google Sheets export URL, dibangun dari config.py (SPREADSHEET_ID + BACKEND_SHEET_NAME)
        via gsheet_csv_url() — supaya SATU sumber kebenaran, tidak ada URL/gid duplikat/hardcoded
        yang bisa berbeda dari config.py.
    """
    try:
        if isinstance(source, pd.DataFrame):
            return parse_backend(source)

        if isinstance(source, str):
            try:
                raw = pd.read_csv(source.strip(), header=None, dtype=str)
            except Exception as e:
                raise BackendDataError(f"Gagal membaca CSV dari {source}") from e
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

        # Sumber Google Sheets — dibangun dari config.py, bukan hardcoded di sini.
        try:
            from config import SPREADSHEET_ID, BACKEND_SHEET_NAME, gsheet_csv_url
            url = gsheet_csv_url(BACKEND_SHEET_NAME, SPREADSHEET_ID)
        except ImportError:
            # fallback terakhir jika config.py tidak tersedia sama sekali
            url = (
                "https://docs.google.com/spreadsheets/d/"
                "1YRvXt0AE-dVBVwRvLtsb57Qz8DYd9YbVQlVbRD31C7I/gviz/tq?tqx=out:csv&sheet=BACKEND"
            )
        raw = pd.read_csv(url, header=None, dtype=str)
        return parse_backend(raw)

    except BackendDataError:
        raise
    except Exception as e:
        logger.exception("Gagal memuat backend data")
        raise BackendDataError("Gagal memuat backend data") from e
