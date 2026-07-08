"""
Data loader untuk sheet BACKEND (Google Spreadsheet).

Sheet BACKEND memiliki beberapa tabel lookup yang diposisikan pada baris/kolom
tetap (bukan satu tabel rapi dengan header tunggal), persis seperti file Excel
aslinya:

    Baris 1     : judul "Load Factor"
    Baris 2     : header (Sub Section, Attribute, Load Mechanic,
                  Load Electrican, Load Welder)
    Baris 3-19  : data Load Factor per Sub Category
    Baris 21    : judul "Ratio Shift"
    Baris 22    : header (Site, Ratio)
    Baris 23-25 : data Ratio Shift (BCP, ACP, KCP)
    Baris 27    : judul "RACI"
    Baris 28    : header (Mechanic, Electrician, Welder)
    Baris 29    : proporsi RACI
    Baris 31    : judul "Mechanic" (split M1/M2/M3)
    Baris 32    : nilai split Mechanic (M1, M2, M3)
    Baris 34    : judul "Welder" (split M1/M2)
    Baris 35    : nilai split Welder (M1, M2)
    Baris 37    : judul "Electrician" (split M1/M2)
    Baris 38    : nilai split Electrician (M1, M2)
    Baris 41    : judul "Lost Time"
    Baris 43-45 : data Lost Time per Site (BCP, ACP, KCP)

Fungsi-fungsi di modul ini membaca data tersebut secara live dari Google
Sheets (CSV export) sehingga tidak ada angka referensi yang di-hardcode di
kode aplikasi.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

import pandas as pd
import requests

from config import gsheet_csv_url, BACKEND_SHEET_NAME, SPREADSHEET_ID

# Baris (0-indexed, mengikuti pandas) tempat masing-masing tabel berada.
_LOAD_FACTOR_HEADER_ROW = 1
_LOAD_FACTOR_DATA_ROWS = (2, 19)   # slice [start, end) -> baris Excel 3-19
_RATIO_SHIFT_DATA_ROWS = (22, 25)  # baris Excel 23-25
_RACI_DATA_ROW = 28                # baris Excel 29
_MECHANIC_SPLIT_ROW = 31           # baris Excel 32
_WELDER_SPLIT_ROW = 34             # baris Excel 35
_ELECTRICIAN_SPLIT_ROW = 37        # baris Excel 38
_LOST_TIME_DATA_ROWS = (42, 45)    # baris Excel 43-45


class BackendDataError(RuntimeError):
    """Dilempar bila data BACKEND gagal diambil atau formatnya tidak sesuai."""


@dataclass
class BackendData:
    load_factor: pd.DataFrame          # index: Sub Category, kolom: Attribute, Load Mechanic, Load Electrican, Load Welder
    ratio_shift: dict                  # {site: ratio}
    lost_time: dict                    # {site: lost_time}
    raci: dict                         # {"Mechanic":.., "Electric":.., "Welder":..}
    split_mechanic: tuple              # (m1, m2, m3)
    split_welder: tuple                # (m1, m2)
    split_electrician: tuple           # (m1, m2)

    @property
    def sub_categories(self) -> list:
        return list(self.load_factor.index)

    def units_for(self, sub_category: str) -> list:
        """'Jenis Unit' (Attribute) yang tersedia untuk sebuah Sub Category."""
        if sub_category not in self.load_factor.index:
            return []
        val = self.load_factor.loc[sub_category, "Attribute"]
        return [val] if pd.notna(val) else []

    @property
    def sites(self) -> list:
        return sorted(set(self.ratio_shift) & set(self.lost_time))


def _fetch_raw_csv(sheet_name: str = BACKEND_SHEET_NAME, spreadsheet_id: str = SPREADSHEET_ID) -> pd.DataFrame:
    url = gsheet_csv_url(sheet_name, spreadsheet_id)
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise BackendDataError(
            f"Gagal mengambil data dari Google Sheets ({sheet_name}). "
            f"Pastikan spreadsheet sudah di-share (Anyone with link - Viewer). Detail: {exc}"
        ) from exc

    try:
        df = pd.read_csv(io.StringIO(resp.text), header=None)
    except Exception as exc:  # pandas parser error
        raise BackendDataError(f"Gagal parsing CSV dari sheet {sheet_name}: {exc}") from exc

    if df.empty:
        raise BackendDataError(f"Sheet {sheet_name} kosong atau tidak ditemukan.")
    return df


def _to_float(val, default=None) -> float:
    if pd.isna(val):
        return default
    if isinstance(val, str):
        val = val.strip().replace(",", ".")
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def parse_backend(raw: pd.DataFrame) -> BackendData:
    # --- Load Factor table ---
    start, end = _LOAD_FACTOR_DATA_ROWS
    lf_rows = raw.iloc[start:end, 0:5].copy()
    lf_rows.columns = ["Sub Category", "Attribute", "Load Mechanic", "Load Electrican", "Load Welder"]
    lf_rows = lf_rows.dropna(subset=["Sub Category"])
    lf_rows["Load Mechanic"] = lf_rows["Load Mechanic"].apply(_to_float)
    lf_rows["Load Electrican"] = lf_rows["Load Electrican"].apply(_to_float)
    lf_rows["Load Welder"] = lf_rows["Load Welder"].apply(_to_float)
    lf_rows = lf_rows.set_index("Sub Category")

    if lf_rows.empty:
        raise BackendDataError("Tabel Load Factor pada BACKEND tidak ditemukan / kosong.")

    # --- Ratio Shift table (Site -> Ratio) ---
    start, end = _RATIO_SHIFT_DATA_ROWS
    rs_rows = raw.iloc[start:end, 0:2].copy()
    rs_rows.columns = ["Site", "Ratio"]
    rs_rows = rs_rows.dropna(subset=["Site"])
    ratio_shift = {
        str(r["Site"]).strip(): _to_float(r["Ratio"])
        for _, r in rs_rows.iterrows()
    }

    # --- Lost Time table (Site -> Lost Time), A43:B45 ---
    start, end = _LOST_TIME_DATA_ROWS
    lt_rows = raw.iloc[start:end, 0:2].copy()
    lt_rows.columns = ["Site", "Lost Time"]
    lt_rows = lt_rows.dropna(subset=["Site"])
    lost_time = {
        str(r["Site"]).strip(): _to_float(r["Lost Time"])
        for _, r in lt_rows.iterrows()
    }

    # --- RACI proportion (Mechanic, Electrician, Welder) ---
    raci_row = raw.iloc[_RACI_DATA_ROW, 0:3]
    raci = {
        "Mechanic": _to_float(raci_row.iloc[0]),
        "Electric": _to_float(raci_row.iloc[1]),
        "Welder": _to_float(raci_row.iloc[2]),
    }

    # --- Split ratio Mechanic (M1, M2, M3) ---
    m_row = raw.iloc[_MECHANIC_SPLIT_ROW, 0:3]
    split_mechanic = tuple(_to_float(v, 0.0) for v in m_row)

    # --- Split ratio Welder (M1, M2) ---
    w_row = raw.iloc[_WELDER_SPLIT_ROW, 0:2]
    split_welder = tuple(_to_float(v, 0.0) for v in w_row)

    # --- Split ratio Electrician (M1, M2) ---
    e_row = raw.iloc[_ELECTRICIAN_SPLIT_ROW, 0:2]
    split_electrician = tuple(_to_float(v, 0.0) for v in e_row)

    if not ratio_shift or not lost_time:
        raise BackendDataError("Tabel Ratio Shift / Lost Time pada BACKEND tidak ditemukan / kosong.")
    if any(v is None for v in raci.values()):
        raise BackendDataError("Proporsi RACI pada BACKEND tidak lengkap.")

    return BackendData(
        load_factor=lf_rows,
        ratio_shift=ratio_shift,
        lost_time=lost_time,
        raci=raci,
        split_mechanic=split_mechanic,
        split_welder=split_welder,
        split_electrician=split_electrician,
    )


def load_backend_data(spreadsheet_id: str = SPREADSHEET_ID, sheet_name: str = BACKEND_SHEET_NAME) -> BackendData:
    """Ambil & parse data BACKEND dari Google Sheets (live, tidak di-hardcode)."""
    raw = _fetch_raw_csv(sheet_name=sheet_name, spreadsheet_id=spreadsheet_id)
    return parse_backend(raw)
