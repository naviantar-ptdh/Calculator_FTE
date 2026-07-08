"""
Data loader untuk sheet BACKEND (Google Spreadsheet).
Versi Final: Pemindaian berbasis indeks dinamis dengan isolasi penuh antar seksi.
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


def _clean_str(val) -> str:
    if pd.isna(val):
        return ""
    return str(val).strip().lower()


def parse_backend(raw: pd.DataFrame) -> BackendData:
    max_rows = raw.shape[0]

    # --- 1. Ambil Blok 'Load Factor' ---
    lf_idx = None
    for r in range(max_rows):
        if "load factor" in _clean_str(raw.iloc[r, 0]):
            lf_idx = r
            break
    if lf_idx is None:
        raise BackendDataError("Section 'Load Factor' tidak ditemukan di kolom A.")

    lf_rows_list = []
    # Data dimulai dari lf_idx + 2 (melewati judul dan header)
    curr = lf_idx + 2
    while curr < max_rows:
        val_a = raw.iloc[curr, 0]
        if pd.isna(val_a) or str(val_a).strip() == "" or "ratio shift" in _clean_str(val_a):
            break
        lf_rows_list.append([
            str(val_a).strip(),
            raw.iloc[curr, 1],
            _to_float(raw.iloc[curr, 2]),
            _to_float(raw.iloc[curr, 3]),
            _to_float(raw.iloc[curr, 4])
        ])
        curr += 1
    
    lf_df = pd.DataFrame(lf_rows_list, columns=["Sub Category", "Attribute", "Load Mechanic", "Load Electrican", "Load Welder"])
    lf_final = lf_df.dropna(subset=["Sub Category"]).set_index("Sub Category")

    # --- 2. Ambil Blok 'Ratio Shift' ---
    rs_idx = None
    for r in range(max_rows):
        if "ratio shift" in _clean_str(raw.iloc[r, 0]):
            rs_idx = r
            break
    if rs_idx is None:
        raise BackendDataError("Section 'Ratio Shift' tidak ditemukan di kolom A.")

    ratio_shift = {}
    curr = rs_idx + 2
    while curr < max_rows:
        val_a = raw.iloc[curr, 0]
        if pd.isna(val_a) or str(val_a).strip() == "" or "raci" in _clean_str(val_a):
            break
        ratio_shift[str(val_a).strip()] = _to_float(raw.iloc[curr, 1])
        curr += 1

    # --- 3. Ambil Blok 'RACI' ---
    raci_idx = None
    for r in range(max_rows):
        if _clean_str(raw.iloc[r, 0]) == "raci":
            raci_idx = r
            break
    if raci_idx is None:
        raise BackendDataError("Section 'RACI' tidak ditemukan di kolom A.")

    # Ambil nilai berdasarkan posisi baris relatif setelah judul RACI
    raci = {
        "Mechanic": _to_float(raw.iloc[raci_idx + 1, 1]),   # Baris tepat di bawah tulisan RACI
        "Electric": _to_float(raw.iloc[raci_idx + 2, 1]),   # Baris kedua bawah RACI
        "Welder": _to_float(raw.iloc[raci_idx + 3, 1])      # Baris ketiga bawah RACI
    }

    # Area pencarian Split Ratio dibatasi HANYA setelah baris RACI selesai (+4)
    split_search_start = raci_idx + 4

    # --- 4. Ambil Blok 'Split Ratio Mechanic' ---
    m_idx = None
    for r in range(split_search_start, max_rows):
        if _clean_str(raw.iloc[r, 0]) == "mechanic":
            m_idx = r
            break
    if m_idx is None:
        raise BackendDataError("Judul Split Ratio 'Mechanic' tidak ditemukan setelah tabel RACI.")
    split_mechanic = (
        _to_float(raw.iloc[m_idx + 1, 0], 0.0),
        _to_float(raw.iloc[m_idx + 1, 1], 0.0),
        _to_float(raw.iloc[m_idx + 1, 2], 0.0)
    )

    # --- 5. Ambil Blok 'Split Ratio Welder' ---
    w_idx = None
    for r in range(m_idx + 2, max_rows):
        if _clean_str(raw.iloc[r, 0]) == "welder":
            w_idx = r
            break
    if w_idx is None:
        raise BackendDataError("Judul Split Ratio 'Welder' tidak ditemukan.")
    split_welder = (
        _to_float(raw.iloc[w_idx + 1, 0], 0.0),
        _to_float(raw.iloc[w_idx + 1, 1], 0.0)
    )

    # --- 6. Ambil Blok 'Split Ratio Electrician' ---
    e_idx = None
    for r in range(w_idx + 2, max_rows):
        if _clean_str(raw.iloc[r, 0]) == "electrician":
            e_idx = r
            break
    if e_idx is None:
        raise BackendDataError("Judul Split Ratio 'Electrician' tidak ditemukan.")
    split_electrician = (
        _to_float(raw.iloc[e_idx + 1, 0], 0.0),
        _to_float(raw.iloc[e_idx + 1, 1], 0.0)
    )

    # --- 7. Ambil Blok 'Lost Time' ---
    lt_idx = None
    for r in range(max_rows):
        if "lost time" in _clean_str(raw.iloc[r, 0]):
            lt_idx = r
            break
    if lt_idx is None:
        raise BackendDataError("Section 'Lost Time' tidak ditemukan.")

    lost_time = {}
    curr = lt_idx + 2
    while curr < max_rows:
        val_a = raw.iloc[curr, 0]
        if pd.isna(val_a) or str(val_a).strip() == "":
            break
        lost_time[str(val_a).strip()] = _to_float(raw.iloc[curr, 1])
        current_row = curr
        curr += 1

    # Validasi Integritas Data Akhir
    if not ratio_shift or not lost_time:
        raise BackendDataError("Tabel Ratio Shift atau Lost Time terdeteksi kosong.")
    if any(v is None for v in raci.values()):
        raise BackendDataError(f"Nilai Proporsi RACI tidak lengkap. Hasil baca: {raci}")

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
