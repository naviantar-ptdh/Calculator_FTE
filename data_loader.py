# data_loader.py
"""
Parser data BACKEND dinamis untuk mencegah pergeseran baris akibat manipulasi spreadsheet.
Memastikan role Mechanic, Electrician, dan Welder terkunci berdasarkan teks string.
"""
import io
from dataclasses import dataclass
from typing import Any
import pandas as pd
import requests
from config import gsheet_csv_url, BACKEND_SHEET_NAME, SPREADSHEET_ID

class BackendDataError(RuntimeError):
    pass

@dataclass
class BackendData:
    load_factor: pd.DataFrame
    ratio_shift: dict
    lost_time: dict
    raci: dict
    split_mechanic: dict
    split_welder: dict
    split_electrician: dict

def _cell(df: pd.DataFrame, r: int, c: int) -> Any:
    if r < 0 or r >= df.shape[0] or c < 0 or c >= df.shape[1]:
        return None
    val = df.iloc[r, c]
    if pd.isna(val):
        return None
    return val

def parse_backend(raw: pd.DataFrame) -> BackendData:
    col_a = raw[0].astype(str).str.strip().str.lower().tolist()

    def find_row_by_label(label: str) -> int:
        for i, val in enumerate(col_a):
            if label.lower() in val:
                return i
        return -1

    # --- 1. Load Factor Block ---
    lf_idx = find_row_by_label("load factor")
    if lf_idx == -1:
        raise BackendDataError("Judul seksi 'Load Factor' tidak ditemukan di Kolom A BACKEND.")
    
    headers = [str(_cell(raw, lf_idx+1, c)).strip() for c in range(5)]
    lf_rows = []
    curr = lf_idx + 2
    while curr < len(raw):
        val_a = _cell(raw, curr, 0)
        if val_a is None or str(val_a).strip() == "":
            break
        lf_rows.append({
            headers[0]: str(_cell(raw, curr, 0)).strip(),
            headers[1]: str(_cell(raw, curr, 1)).strip(),
            headers[2]: float(str(_cell(raw, curr, 2)).replace(",", ".")),
            headers[3]: float(str(_cell(raw, curr, 3)).replace(",", ".")),
            headers[4]: float(str(_cell(raw, curr, 4)).replace(",", ".")),
        })
        curr += 1
    df_lf = pd.DataFrame(lf_rows).set_index(headers[0])

    # --- 2. Ratio Shift Block ---
    rs_idx = find_row_by_label("ratio shift")
    ratio_shift = {}
    if rs_idx != -1:
        curr = rs_idx + 1
        while curr < len(raw):
            k = _cell(raw, curr, 0)
            v = _cell(raw, curr, 1)
            if k is None or str(k).strip() == "":
                break
            ratio_shift[str(k).strip().upper()] = float(str(v).strip().replace(",", "."))
            curr += 1

    # --- 3. RACI Block (Dibuat Aman & Berbasis Teks) ---
    raci_idx = find_row_by_label("proporsi raci")
    raci = {"Mechanic": 1.0, "Electrician": 1.0, "Welder": 1.0}
    if raci_idx != -1:
        curr = raci_idx + 1
        while curr < len(raw):
            role_lbl = _cell(raw, curr, 0)
            val_lbl = _cell(raw, curr, 1)
            if role_lbl is None or str(role_lbl).strip() == "":
                break
            
            role_str = str(role_lbl).strip().lower()
            val_float = float(str(val_lbl).strip().replace(",", "."))
            
            if "mechanic" in role_str:
                raci["Mechanic"] = val_float
            elif "electric" in role_str:
                raci["Electrician"] = val_float
            elif "welder" in role_str:
                raci["Welder"] = val_float
            curr += 1

    # --- 4. Split Ratio Block ---
    def get_vertical_split(label: str) -> dict:
        idx = find_row_by_label(label)
        res = {}
        if idx != -1:
            curr = idx + 1
            while curr < len(raw):
                lvl = _cell(raw, curr, 0)
                val = _cell(raw, curr, 1)
                if lvl is None or str(lvl).strip() == "":
                    break
                res[str(lvl).strip().upper()] = float(str(val).strip().replace(",", "."))
                curr += 1
        return res

    split_m = get_vertical_split("split ratio mechanic")
    split_w = get_vertical_split("split ratio welder")
    split_e = get_vertical_split("split ratio electrician")

    # --- 5. Lost Time Block ---
    lt_idx = find_row_by_label("lost time")
    lost_time = {}
    if lt_idx != -1:
        curr = lt_idx + 1
        while curr < len(raw):
            site = _cell(raw, curr, 0)
            val = _cell(raw, curr, 1)
            if site is None or str(site).strip() == "":
                break
            lost_time[str(site).strip().upper()] = float(str(val).strip().replace(",", "."))
            curr += 1

    return BackendData(
        load_factor=df_lf,
        ratio_shift=ratio_shift,
        lost_time=lost_time,
        raci=raci,
        split_mechanic=split_m,
        split_welder=split_w,
        split_electrician=split_e
    )

def load_backend_data() -> BackendData:
    url = gsheet_csv_url(BACKEND_SHEET_NAME, SPREADSHEET_ID)
    res = requests.get(url, timeout=15)
    if res.status_code != 200:
        raise BackendDataError("Gagal mengambil data dari Google Sheets.")
    raw = pd.read_csv(io.StringIO(res.text), header=None, dtype=str)
    return parse_backend(raw)
