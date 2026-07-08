"""
Data loader untuk sheet BACKEND (Google Spreadsheet).

Sheet BACKEND memiliki beberapa tabel lookup: "Load Factor", "Ratio Shift",
"RACI", "Mechanic" (split), "Welder" (split), "Electrician" (split), dan
"Lost Time".

PENTING: Versi sebelumnya membaca tabel-tabel ini berdasarkan NOMOR BARIS
TETAP (mis. _ELECTRICIAN_SPLIT_ROW = 37). Ini rapuh -- begitu ada baris yang
disisipkan/dihapus/digeser di Google Sheets (hal yang wajar terjadi saat
sheet terus di-update), nomor baris jadi salah dan menyebabkan
`IndexError: single positional indexer is out-of-bounds`.

Versi ini mencari setiap section berdasarkan LABEL TEKS-nya (mis. sel di
kolom A yang isinya "Load Factor", "RACI", dst), lalu membaca data secara
relatif dari situ. Dengan begini, parser tetap jalan walau ada baris kosong
tambahan/berkurang, asalkan urutan & label section tidak berubah.
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


def _cell(raw: pd.DataFrame, row: int, col: int):
    """Ambil nilai sel dengan aman menggunakan iloc."""
    if row < 0 or row >= raw.shape[0] or col < 0 or col >= raw.shape[1]:
        return None
    val = raw.iloc[row, col]
    return None if pd.isna(val) or str(val).strip() == "" else val


def _norm(val) -> str:
    return str(val).strip().lower() if val is not None else ""


def _find_label_row(raw: pd.DataFrame, label: str, col: int = 0, start: int = 0,
                    match_other_cols_empty: bool = False) -> int:
    """Cari baris pertama (mulai dari start) yang mengandung teks label secara case-insensitive."""
    target = label.strip().lower()
    
    for r in range(start, raw.shape[0]):
        # Ambil nilai sel di kolom utama dengan aman
        val_main = raw.iloc[r, col] if col < raw.shape[1] else None
        if pd.notna(val_main) and target in str(val_main).strip().lower():
            if match_other_cols_empty:
                # Pastikan kolom sebelahnya kosong (untuk membedakan judul section dengan header)
                val_next = raw.iloc[r, col + 1] if (col + 1) < raw.shape[1] else None
                if pd.notna(val_next) and str(val_next).strip() != "":
                    continue
            return r
            
        # Pengecekan cadangan di kolom B (indeks 1) jika kolom A di-merge
        if col == 0 and raw.shape[1] > 1:
            val_sub = raw.iloc[r, 1]
            if pd.notna(val_sub) and target in str(val_sub).strip().lower():
                if match_other_cols_empty:
                    val_next = raw.iloc[r, 2] if raw.shape[1] > 2 else None
                    if pd.notna(val_next) and str(val_next).strip() != "":
                        continue
                return r
                
    raise BackendDataError(
        f"Section '{label}' tidak ditemukan pada sheet BACKEND. "
        f"Pastikan label section ini masih ada di kolom A atau B."
    )


def _read_block(raw: pd.DataFrame, start_row: int, ncols: int) -> pd.DataFrame:
    """Baca baris berurutan mulai dari start_row hingga menemukan baris yang benar-benar kosong."""
    rows = []
    r = start_row
    while r < raw.shape[0]:
        row_data = [_cell(raw, r, c) for c in range(ncols)]
        
        # Jika semua kolom yang diminta di baris ini kosong (None), artinya tabel sudah selesai
        if all(x is None for x in row_data):
            break
            
        rows.append(row_data)
        r += 1
    return pd.DataFrame(rows)


def parse_backend(raw: pd.DataFrame) -> BackendData:
    # --- Load Factor table ---
    lf_title_row = _find_label_row(raw, "Load Factor")
    lf_header_row = lf_title_row + 1
    lf_block = _read_block(raw, lf_header_row + 1, 5)
    if lf_block.empty:
        raise BackendDataError("Tabel Load Factor pada BACKEND tidak ditemukan / kosong.")
    lf_block.columns = ["Sub Category", "Attribute", "Load Mechanic", "Load Electrican", "Load Welder"]
    lf_block = lf_block.dropna(subset=["Sub Category"])
    lf_block["Load Mechanic"] = lf_block["Load Mechanic"].apply(_to_float)
    lf_block["Load Electrican"] = lf_block["Load Electrican"].apply(_to_float)
    lf_block["Load Welder"] = lf_block["Load Welder"].apply(_to_float)
    lf_rows = lf_block.set_index("Sub Category")

    if lf_rows.empty:
        raise BackendDataError("Tabel Load Factor pada BACKEND tidak ditemukan / kosong.")

    # --- Ratio Shift table (Site -> Ratio) ---
    rs_title_row = _find_label_row(raw, "Ratio Shift", start=lf_header_row)
    rs_header_row = rs_title_row + 1
    rs_block = _read_block(raw, rs_header_row + 1, 2)
    rs_block.columns = ["Site", "Ratio"] if not rs_block.empty else rs_block.columns
    if not rs_block.empty:
        rs_block = rs_block.dropna(subset=["Site"])
    ratio_shift = {
        str(r["Site"]).strip(): _to_float(r["Ratio"])
        for _, r in rs_block.iterrows()
    } if not rs_block.empty else {}

    # --- RACI proportion (Mechanic, Electrician, Welder) ---
    raci_title_row = _find_label_row(raw, "RACI", start=rs_header_row)
    raci_header_row = raci_title_row + 1
    raci_data_row = raci_header_row + 1
    raci = {
        "Mechanic": _to_float(_cell(raw, raci_data_row, 0)),
        "Electric": _to_float(_cell(raw, raci_data_row, 1)),
        "Welder": _to_float(_cell(raw, raci_data_row, 2)),
    }

    # --- Split ratio Mechanic (M1, M2, M3) ---
    m_title_row = _find_label_row(raw, "Mechanic", start=raci_data_row, match_other_cols_empty=True)
    m_data_row = m_title_row + 1
    split_mechanic = tuple(
        _to_float(_cell(raw, m_data_row, c), 0.0) for c in range(3)
    )

    # --- Split ratio Welder (M1, M2) ---
    w_title_row = _find_label_row(raw, "Welder", start=m_data_row, match_other_cols_empty=True)
    w_data_row = w_title_row + 1
    split_welder = tuple(
        _to_float(_cell(raw, w_data_row, c), 0.0) for c in range(2)
    )

    # --- Split ratio Electrician (M1, M2) ---
    e_title_row = _find_label_row(raw, "Electrician", start=w_data_row, match_other_cols_empty=True)
    e_data_row = e_title_row + 1
    split_electrician = tuple(
        _to_float(_cell(raw, e_data_row, c), 0.0) for c in range(2)
    )

    # --- Lost Time table (Site -> Lost Time) ---
    lt_title_row = _find_label_row(raw, "Lost Time", start=e_data_row)
    # Ada kemungkinan baris kosong sebelum data mulai
    lt_start = lt_title_row + 1
    while lt_start < len(raw) and _cell(raw, lt_start, 0) is None:
        lt_start += 1
    lt_block = _read_block(raw, lt_start, 2)
    lt_block.columns = ["Site", "Lost Time"] if not lt_block.empty else lt_block.columns
    if not lt_block.empty:
        lt_block = lt_block.dropna(subset=["Site"])
    lost_time = {
        str(r["Site"]).strip(): _to_float(r["Lost Time"])
        for _, r in lt_block.iterrows()
    } if not lt_block.empty else {}

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
