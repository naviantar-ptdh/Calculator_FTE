"""
Data loader untuk sheet BACKEND (Google Spreadsheet).
Versi adaptif aman dari kesalahan substring matching pada section Split Ratio.
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


def _cell(raw: pd.DataFrame, row: int, col: int):
    """Ambil nilai sel dengan proteksi out-of-bounds dan string kosong."""
    if row < 0 or row >= raw.shape[0] or col < 0 or col >= raw.shape[1]:
        return None
    val = raw.iloc[row, col]
    if pd.isna(val) or str(val).strip() == "":
        return None
    return val


def _find_exact_label_row(raw: pd.DataFrame, label: str, start: int = 0) -> int:
    """
    Mencari baris yang benar-benar merupakan JUDUL SECTION (Exact Match).
    Menghindari bug salah tangkap kata 'Mechanic' di dalam tabel RACI.
    """
    target = label.strip().lower()
    for r in range(start, raw.shape[0]):
        val_a = _cell(raw, r, 0)
        val_b = _cell(raw, r, 1)
        
        # Cek apakah kolom A berisi persis nama label
        if val_a is not None and str(val_a).strip().lower() == target:
            # Judul section murni biasanya kolom B-nya kosong atau None
            if val_b is None:
                return r
                
        # Fallback jika judul tergeser ke kolom B akibat merged cell visual
        if val_b is not None and str(val_b).strip().lower() == target:
            if val_a is None:
                return r
                
    raise BackendDataError(f"Section Title '{label}' tidak ditemukan di Sheet BACKEND.")


def _read_block(raw: pd.DataFrame, start_row: int, ncols: int) -> pd.DataFrame:
    """Membaca tabel ke bawah sampai menemukan baris yang benar-benar kosong."""
    rows = []
    r = start_row
    while r < raw.shape[0]:
        row_data = [_cell(raw, r, c) for c in range(ncols)]
        if all(x is None for x in row_data):
            break
        rows.append(row_data)
        r += 1
    return pd.DataFrame(rows)


def parse_backend(raw: pd.DataFrame) -> BackendData:
    # 1. --- Load Factor table ---
    lf_title_row = _find_exact_label_row(raw, "Load Factor", start=0)
    lf_block = _read_block(raw, lf_title_row + 2, 5)
    if lf_block.empty:
        raise BackendDataError("Tabel Load Factor kosong atau salah format.")
    lf_block.columns = ["Sub Category", "Attribute", "Load Mechanic", "Load Electrican", "Load Welder"]
    lf_block = lf_block.dropna(subset=["Sub Category"])
    for col in ["Load Mechanic", "Load Electrican", "Load Welder"]:
        lf_block[col] = lf_block[col].apply(_to_float)
    lf_rows = lf_block.set_index("Sub Category")

    # 2. --- Ratio Shift table ---
    rs_title_row = _find_exact_label_row(raw, "Ratio Shift", start=0)
    rs_block = _read_block(raw, rs_title_row + 2, 2)
    ratio_shift = {}
    if not rs_block.empty:
        rs_block.columns = ["Site", "Ratio"]
        ratio_shift = {str(r["Site"]).strip(): _to_float(r["Ratio"]) for _, r in rs_block.iterrows() if r["Site"] is not None}

    # 3. --- RACI proportion ---
    raci_title_row = _find_exact_label_row(raw, "RACI", start=0)
    raci_block = _read_block(raw, raci_title_row + 2, 4)
    if raci_block.empty:
        raise BackendDataError("Data nilai RACI kosong.")
    
    # Ambil nilai baris pertama dari tabel RACI secara dinamis
    raci = {
        "Mechanic": _to_float(raci_block.iloc[0, 1]),   # Kolom nilai pertama setelah label peran
        "Electric": _to_float(raci_block.iloc[1, 1]),   # Baris kedua (Electrician)
        "Welder": _to_float(raci_block.iloc[2, 1]),     # Baris ketiga (Welder)
    }

    # 4. --- Split ratio Mechanic (M1, M2, M3) ---
    # Mulai pencarian setelah tabel RACI agar tidak bentrok
    m_title_row = _find_exact_label_row(raw, "Mechanic", start=raci_title_row + 4)
    split_mechanic = tuple(_to_float(_cell(raw, m_title_row + 1, c), 0.0) for c in range(3))

    # 5. --- Split ratio Welder (M1, M2) ---
    w_title_row = _find_exact_label_row(raw, "Welder", start=m_title_row + 2)
    split_welder = tuple(_to_float(_cell(raw, w_title_row + 1, c), 0.0) for c in range(2))

    # 6. --- Split ratio Electrician (M1, M2) ---
    e_title_row = _find_exact_label_row(raw, "Electrician", start=w_title_row + 2)
    split_electrician = tuple(_to_float(_cell(raw, e_title_row + 1, c), 0.0) for c in range(2))

    # 7. --- Lost Time table ---
    lt_title_row = _find_exact_label_row(raw, "Lost Time", start=0)
    lt_block = _read_block(raw, lt_title_row + 2, 2)
    lost_time = {}
    if not lt_block.empty:
        lt_block.columns = ["Site", "Lost Time"]
        lost_time = {str(r["Site"]).strip(): _to_float(r["Lost Time"]) for _, r in lt_block.iterrows() if r["Site"] is not None}

    # Validasi Akhir Data
    if not ratio_shift or not lost_time:
        raise BackendDataError("Tabel Ratio Shift atau Lost Time kosong.")
        
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
    raw = _fetch_raw_csv(sheet_name=sheet_name, spreadsheet_id=spreadsheet_id)
    return parse_backend(raw)
