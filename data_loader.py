"""
Data loader untuk sheet BACKEND (Google Spreadsheet).
Versi final: Bebas bug substring matching, kebal spasi gaib, dan adaptif terhadap baris kosong Google Sheets.
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
    load_factor: pd.DataFrame          # index: Sub Category
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
            f"Detail: {exc}"
        ) from exc

    try:
        df = pd.read_csv(io.StringIO(resp.text), header=None)
        # Saring spasi tak terlihat di setiap sel berjenis teks
        df = df.map(lambda x: x.strip() if isinstance(x, str) else x)
    except Exception as exc:
        raise BackendDataError(f"Gagal parsing CSV dari sheet {sheet_name}: {exc}") from exc

    if df.empty:
        raise BackendDataError(f"Sheet {sheet_name} kosong atau tidak ditemukan.")
    return df


def _to_float(val, default=None) -> float:
    if pd.isna(val) or str(val).strip() == "":
        return default
    if isinstance(val, str):
        val = val.strip().replace(",", ".")
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _clean_cell_str(raw: pd.DataFrame, row: int, col: int) -> str:
    """Mengambil string sel dan membersihkannya dari spasi untuk pencocokan judul."""
    if row < 0 or row >= raw.shape[0] or col < 0 or col >= raw.shape[1]:
        return ""
    val = raw.iloc[row, col]
    if pd.isna(val):
        return ""
    return str(val).strip().lower()


def parse_backend(raw: pd.DataFrame) -> BackendData:
    """
    Memecah file DataFrame mentah menjadi blok-blok tabel secara berurutan ke bawah.
    Menggunakan teknik sekuensial agar terhindar dari bentrokan nama kolom/header yang serupa.
    """
    current_row = 0
    max_rows = raw.shape[0]

    # --- 1. Ambil Blok 'Load Factor' ---
    # Cari judul Load Factor dari atas
    while current_row < max_rows and "load factor" not in _clean_cell_str(raw, current_row, 0):
        current_row += 1
        
    if current_row >= max_rows:
        raise BackendDataError("Judul section 'Load Factor' tidak ditemukan di kolom A.")
    
    # Header tabel berada 1 baris di bawah judul, datanya dimulai 2 baris di bawah judul
    current_row += 2 
    lf_rows_list = []
    while current_row < max_rows:
        sub_cat = raw.iloc[current_row, 0]
        # Berhenti jika menemukan baris pembatas kosong atau bertemu tabel berikutnya
        if pd.isna(sub_cat) or str(sub_cat).strip() == "" or "ratio shift" in str(sub_cat).lower():
            break
        
        lf_rows_list.append([
            str(sub_cat).strip(),
            raw.iloc[current_row, 1],
            _to_float(raw.iloc[current_row, 2]),
            _to_float(raw.iloc[current_row, 3]),
            _to_float(raw.iloc[current_row, 4])
        ])
        current_row += 1

    lf_df = pd.DataFrame(lf_rows_list, columns=["Sub Category", "Attribute", "Load Mechanic", "Load Electrican", "Load Welder"])
    lf_df = lf_df.dropna(subset=["Sub Category"])
    lf_final = lf_df.set_index("Sub Category")


    # --- 2. Ambil Blok 'Ratio Shift' ---
    while current_row < max_rows and "ratio shift" not in _clean_cell_str(raw, current_row, 0):
        current_row += 1
        
    if current_row >= max_rows:
        raise BackendDataError("Judul section 'Ratio Shift' tidak ditemukan.")
        
    current_row += 2  # Lewati judul dan header kolom
    ratio_shift = {}
    while current_row < max_rows:
        site_val = raw.iloc[current_row, 0]
        if pd.isna(site_val) or str(site_val).strip() == "" or "raci" in str(site_val).lower():
            break
        ratio_shift[str(site_val).strip()] = _to_float(raw.iloc[current_row, 1])
        current_row += 1


    # --- 3. Ambil Blok 'RACI' ---
    while current_row < max_rows and "raci" not in _clean_cell_str(raw, current_row, 0):
        current_row += 1
        
    if current_row >= max_rows:
        raise BackendDataError("Judul section 'RACI' tidak ditemukan.")
        
    current_row += 2  # Lewati judul 'RACI' dan baris headernya
    
    # Ambil nilai RACI secara berurutan baris demi baris (Mechanic, Electrician, Welder)
    raci = {
        "Mechanic": _to_float(raw.iloc[current_row, 1]),
        "Electric": _to_float(raw.iloc[current_row + 1, 1]),
        "Welder": _to_float(raw.iloc[current_row + 2, 1])
    }
    current_row += 3


    # --- 4. Ambil Blok 'Split Ratio Mechanic' ---
    while current_row < max_rows and "mechanic" not in _clean_cell_str(raw, current_row, 0):
        current_row += 1
        
    if current_row >= max_rows:
        raise BackendDataError("Judul section split ratio 'Mechanic' tidak ditemukan setelah tabel RACI.")
        
    current_row += 1  # Baris data split tepat di bawah judulnya
    split_mechanic = (
        _to_float(raw.iloc[current_row, 0], 0.0),
        _to_float(raw.iloc[current_row, 1], 0.0),
        _to_float(raw.iloc[current_row, 2], 0.0)
    )
    current_row += 1


    # --- 5. Ambil Blok 'Split Ratio Welder' ---
    while current_row < max_rows and "welder" not in _clean_cell_str(raw, current_row, 0):
        current_row += 1
        
    if current_row >= max_rows:
        raise BackendDataError("Judul section split ratio 'Welder' tidak ditemukan.")
        
    current_row += 1
    split_welder = (
        _to_float(raw.iloc[current_row, 0], 0.0),
        _to_float(raw.iloc[current_row, 1], 0.0)
    )
    current_row += 1


    # --- 6. Ambil Blok 'Split Ratio Electrician' ---
    while current_row < max_rows and "electrician" not in _clean_cell_str(raw, current_row, 0):
        current_row += 1
        
    if current_row >= max_rows:
        raise BackendDataError("Judul section split ratio 'Electrician' tidak ditemukan.")
        
    current_row += 1
    split_electrician = (
        _to_float(raw.iloc[current_row, 0], 0.0),
        _to_float(raw.iloc[current_row, 1], 0.0)
    )
    current_row += 1


    # --- 7. Ambil Blok 'Lost Time' ---
    while current_row < max_rows and "lost time" not in _clean_cell_str(raw, current_row, 0):
        current_row += 1
        
    if current_row >= max_rows:
        raise BackendDataError("Judul section 'Lost Time' tidak ditemukan.")
        
    current_row += 2  # Lewati judul dan header kolom
    lost_time = {}
    while current_row < max_rows:
        site_val = raw.iloc[current_row, 0]
        if pd.isna(site_val) or str(site_val).strip() == "":
            break
        lost_time[str(site_val).strip()] = _to_float(raw.iloc[current_row, 1])
        current_row += 1

    # Validasi Akhir Integritas Data
    if not ratio_shift or not lost_time:
        raise BackendDataError("Pemindaian gagal: Tabel Ratio Shift atau Lost Time terdeteksi kosong.")
    if any(v is None for v in raci.values()):
        raise BackendDataError(f"Nilai Proporsi RACI tidak lengkap atau gagal di-parse. Konten: {raci}")

    return BackendData(
        load_factor=lf_final,
        ratio_shift=ratio_shift,
        lost_time=lost_time,
        raci=raci,
        split_mechanic=split_mechanic,
        split_welder=split_welder,
        split_electrician=split_electrician,
    )


def load_backend_data(spreadsheet_id: str = SPREADSHEET_ID, sheet_name: str = BACKEND_SHEET_NAME) -> BackendData:
    raw = _fetch_raw_csv(sheet_name=sheet_name, spreadsheet_id=spreadsheet_id)
    return parse_backend(raw)
