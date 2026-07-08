"""
Data loader untuk sheet BACKEND (Google Spreadsheet).

Versi ini sepenuhnya dinamis dan aman dari tabrakan nama (collision-safe).
Mencari seksi data menggunakan kecocokan teks yang fleksibel dan memastikan 
pembacaan tabel RACI serta Split Ratio tidak saling bertabrakan walaupun 
ada penambahan atau pengurangan baris di Google Sheets.
"""

from __future__ import annotations

import io
from dataclasses import dataclass

import pandas as pd
import requests

from config import gsheet_csv_url, BACKEND_SHEET_NAME, SPREADSHEET_ID


class BackendDataError(RuntimeError):
    """Dilempar bila data BACKEND gagal diambil atau formatnya tidak sesuai."""


@dataclass
class BackendData:
    load_factor: pd.DataFrame          # index: Sub Category, kolom: Attribute, Load Mechanic, Load Electrican, Load Welder
    ratio_shift: dict                  # {site: ratio}
    lost_time: dict                    # {site: lost_time}
    raci: dict                         # {role: proporsi}
    split_mechanic: dict               # {M1: x, M2: y, M3: z}
    split_welder: dict                 # {M1: x, M2: y}
    split_electrician: dict            # {M1: x, M2: y}


def _clean_str(val: any) -> str:
    if pd.isna(val):
        return ""
    return str(val).strip().lower()


def _to_float(val: any, default: float = 0.0) -> float:
    if pd.isna(val):
        return default
    s = str(val).strip().replace(",", ".")
    if not s:
        return default
    try:
        return float(s)
    except ValueError:
        return default


def _cell(df: pd.DataFrame, row: int, col: int) -> any:
    if row < 0 or row >= len(df):
        return None
    if col < 0 or col >= len(df.columns):
        return None
    val = df.iloc[row, col]
    return None if pd.isna(val) else val


def _find_row_by_label(df: pd.DataFrame, label: str, start_row: int = 0, exact_col0: bool = False) -> int:
    target = label.strip().lower()
    for r in range(start_row, len(df)):
        val0 = _clean_str(_cell(df, r, 0))
        if exact_col0:
            if val0 == target:
                return r
        else:
            if target in val0:
                return r
            # Periksa kolom lain di baris tersebut jika tidak saklek di kolom 0
            for c in range(1, len(df.columns)):
                if target in _clean_str(_cell(df, r, c)):
                    return r
    raise BackendDataError(f"Label seksi '{label}' tidak ditemukan di sheet BACKEND.")


def _read_block_until_empty(df: pd.DataFrame, start_row: int, num_cols: int) -> pd.DataFrame:
    rows = []
    r = start_row
    while r < len(df):
        # Anggap kosong jika kolom pertama atau semua kolom yang diminta bernilai None/kosong
        all_empty = True
        row_data = []
        for c in range(num_cols):
            val = _cell(df, r, c)
            row_data.append(val)
            if val is not None and str(val).strip() != "":
                all_empty = False
        
        if all_empty:
            break
        rows.append(row_data)
        r += 1
    return pd.DataFrame(rows)


def parse_backend(raw: pd.DataFrame) -> BackendData:
    if raw.empty:
        raise BackendDataError("Data mentah dari Google Sheets kosong.")

    # 1. --- Load Factor Block ---
    lf_title_row = _find_row_by_label(raw, "Load Factor", start_row=0)
    # Cari baris header setelah judul (melewati baris kosong jika ada)
    header_row = lf_title_row + 1
    while header_row < len(raw) and _cell(raw, header_row, 0) is None:
        header_row += 1
        
    lf_df = _read_block_until_empty(raw, header_row + 1, 5)
    if lf_df.empty:
        raise BackendDataError("Tabel Load Factor tidak ditemukan atau kosong.")
        
    lf_df.columns = ["Sub Category", "Attribute", "Load Mechanic", "Load Electrican", "Load Welder"]
    lf_df["Sub Category"] = lf_df["Sub Category"].astype(str).str.strip()
    lf_df = lf_df.dropna(subset=["Sub Category"]).set_index("Sub Category")

    # 2. --- Ratio Shift Block ---
    rs_title_row = _find_row_by_label(raw, "Ratio Shift", start_row=header_row)
    rs_start = rs_title_row + 1
    while rs_start < len(raw) and _cell(raw, rs_start, 0) is None:
        rs_start += 1
    rs_df = _read_block_until_empty(raw, rs_start, 2)
    rs_df.columns = ["Site", "Ratio"] if not rs_df.empty else ["Site", "Ratio"]
    ratio_shift = {str(r["Site"]).strip(): _to_float(r["Ratio"]) for _, r in rs_df.iterrows()} if not rs_df.empty else {}

    # 3. --- RACI Block (Horizontal Mapping) ---
    raci_title_row = _find_row_by_label(raw, "RACI", start_row=rs_title_row)
    raci_header = raci_title_row + 1
    while raci_header < len(raw) and _cell(raw, raci_header, 0) is None:
        raci_header += 1
        
    # Membaca horizontal: Cari nama role di baris header RACI
    raci = {"Mechanic": None, "Electric": None, "Welder": None}
    for c in range(len(raw.columns)):
        col_lbl = _clean_str(_cell(raw, raci_header, c))
        for role in raci.keys():
            if role.lower() in col_lbl:
                # Ambil nilai tepat di baris bawahnya
                raci[role] = _to_float(_cell(raw, raci_header + 1, c))

    # 4. --- Split Ratio Blocks (Collision-Safe) ---
    # Mulai pencarian setelah seksi RACI untuk menghindari tabrakan nama dengan header RACI
    search_split_start = raci_header + 2

    # Helper khusus mencari judul Split Ratio yang asli (Kolom B harus kosong/None untuk membedakan dari seksi lain)
    def find_split_ratio_row(label: str, start: int) -> int:
        target = label.lower()
        for r in range(start, len(raw)):
            val0 = _clean_str(_cell(raw, r, 0))
            val1 = _cell(raw, r, 1)
            if target in val0 and "split" in val0 and val1 is None:
                return r
            # Fallback jika hanya tertulis nama kuncinya saja tapi kolom B kosong
            if val0 == target and val1 is None:
                return r
        # Fallback terakhir menggunakan pencarian teks biasa jika penulisan unik
        return _find_row_by_label(raw, label, start_row=start)

    # Split Mechanic
    sm_row = find_split_ratio_row("mechanic", search_split_start)
    split_mechanic = {
        "M1": _to_float(_cell(raw, sm_row + 1, 0)),
        "M2": _to_float(_cell(raw, sm_row + 1, 1)),
        "M3": _to_float(_cell(raw, sm_row + 1, 2)),
    }

    # Split Welder
    sw_row = find_split_ratio_row("welder", search_split_start)
    split_welder = {
        "M1": _to_float(_cell(raw, sw_row + 1, 0)),
        "M2": _to_float(_cell(raw, sw_row + 1, 1)),
    }

    # Split Electrician
    se_row = find_split_ratio_row("electrician", search_split_start)
    split_electrician = {
        "M1": _to_float(_cell(raw, se_row + 1, 0)),
        "M2": _to_float(_cell(raw, se_row + 1, 1)),
    }

    # 5. --- Lost Time Block ---
    lt_title_row = _find_row_by_label(raw, "Lost Time", start_row=search_split_start)
    lt_start = lt_title_row + 1
    while lt_start < len(raw) and _cell(raw, lt_start, 0) is None:
        lt_start += 1
    lt_df = _read_block_until_empty(raw, lt_start, 2)
    lt_df.columns = ["Site", "Lost Time"] if not lt_df.empty else ["Site", "Lost Time"]
    lost_time = {str(r["Site"]).strip(): _to_float(r["Lost Time"]) for _, r in lt_df.iterrows()} if not lt_df.empty else {}

    # Validasi Akhir
    if not ratio_shift or not lost_time:
        raise BackendDataError("Tabel Ratio Shift / Lost Time pada BACKEND tidak ditemukan atau kosong.")
    if any(v is None for v in raci.values()):
        raise BackendDataError("Proporsi data RACI horizontal pada BACKEND tidak lengkap atau tidak terbaca.")

    return BackendData(
        load_factor=lf_df,
        ratio_shift=ratio_shift,
        lost_time=lost_time,
        raci=raci,
        split_mechanic=split_mechanic,
        split_welder=split_welder,
        split_electrician=split_electrician,
    )


def load_backend_data() -> BackendData:
    """Mengambil data live dari Google Sheets via CSV Export dan mem-parsingnya."""
    url = gsheet_csv_url(sheet_name=BACKEND_SHEET_NAME, spreadsheet_id=SPREADSHEET_ID)
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        raw_df = pd.read_csv(io.StringIO(response.text), header=None)
        return parse_backend(raw_df)
    except Exception as e:
        raise BackendDataError(f"Gagal memuat atau memproses data dari Google Sheets: {e}")
