# app.py
"""
FTE Calculator — Redesigned & integrated with BACKEND mapping.
Features:
 - Sidebar general params (Site, Competency Factor, Jarak)
 - Editable units table (sub_category select, jenis_unit manual, jumlah int, PA int)
 - Shows Lost Time & Ratio Shift for selected Site
 - compute_fte_raw per-row (no rounding), aggregate_units to round only once
 - Robust mapping between UI sub_category and sheet original name
"""
import base64
from pathlib import Path
from typing import Dict, Any, List

import pandas as pd
import streamlit as st

from calculator import FTEInput, CalculationError, compute_fte_raw, aggregate_units
from config import ROLES, MONTH_COLS, COST_RATE, SPREADSHEET_ID, BACKEND_SHEET_NAME
from data_loader import load_backend_data, BackendDataError

st.set_page_config(
    page_title="FTE Calculator",
    page_icon="🧮",
    layout="wide",
    initial_sidebar_state="expanded",
)

# -- Load logo as data URI if present --
def _load_logo_data_uri() -> str | None:
    here = Path(__file__).resolve().parent
    for candidate in ("logo_putih.png", "assets/logo_putih.png", "static/logo_putih.png"):
        p = here / candidate
        if p.is_file():
            try:
                b64 = base64.b64encode(p.read_bytes()).decode("ascii")
                return f"data:image/png;base64,{b64}"
            except Exception:
                pass
    return None


_LOGO_DATA_URI = _load_logo_data_uri()
_LOGO_FALLBACK_URL = "https://raw.githubusercontent.com/naviantar-ptdh/202605-centralized/main/logo_putih.png"
LOGO_SRC = _LOGO_DATA_URI or _LOGO_FALLBACK_URL

# Minimal CSS (keperluan tampilan)
CSS = """
<style>
.nav { display:flex; align-items:center; gap:12px; margin-bottom:16px; }
.nav img { height:28px; }
.section-label { font-weight:700; color:#6b7280; margin-top:18px; margin-bottom:6px; font-size:12px; text-transform:uppercase; }
.result-card { background:#fff; padding:12px; border-radius:8px; border:1px solid #eee; margin-bottom:12px; }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

# Header / Nav
st.markdown(
    f'<div class="nav"><img src="{LOGO_SRC}" alt="logo" onerror="this.style.display=\'none\'"/><div><strong>FTE Calculator</strong><div style="font-size:12px;color:#6b7280">PT Dharma Henwa</div></div></div>',
    unsafe_allow_html=True,
)

# Cache backend data
@st.cache_data(ttl=600, show_spinner="Mengambil data referensi dari BACKEND...")
def get_backend():
    return load_backend_data()

# Formatting helpers
def format_number(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")

def format_number_raw(x: float) -> str:
    s = f"{x:,.2f}"
    integer_part, _, decimal_part = s.partition(".")
    return f"{integer_part.replace(',', '.')},{decimal_part}"

def format_currency(x: float) -> str:
    return f"Rp {x:,.0f}".replace(",", ".")

def render_fte_table(fte_table: Dict[str, Dict[str, float]]):
    rows = []
    for role in ROLES + ["Total"]:
        r = fte_table[role]
        rows.append({"FTE": role, "M1": format_number(r["M1"]), "M2": format_number(r["M2"]), "M3": format_number(r["M3"]), "Tot": format_number(r["Tot"])})
    st.dataframe(pd.DataFrame(rows).set_index("FTE"), width="stretch")

def render_fte_table_raw(fte_table: Dict[str, Dict[str, float]]):
    rows = []
    for role in ROLES + ["Total"]:
        r = fte_table[role]
        rows.append({"FTE": role, "M1": format_number_raw(r["M1"]), "M2": format_number_raw(r["M2"]), "M3": format_number_raw(r["M3"]), "Tot": format_number_raw(r["Tot"])})
    st.dataframe(pd.DataFrame(rows).set_index("FTE"), width="stretch")

def render_cost_table(cost_table: Dict[str, Dict[str, float]]):
    rows = []
    for role in ROLES + ["Total"]:
        r = cost_table[role]
        rows.append({"Cost": role, "M1": format_currency(r["M1"]), "M2": format_currency(r["M2"]), "M3": format_currency(r["M3"]), "Tot": format_currency(r["Tot"])})
    st.dataframe(pd.DataFrame(rows).set_index("Cost"), width="stretch")

# initialize seed for editor once to avoid re-seeding on every rerun
if "units_seed" not in st.session_state:
    st.session_state.units_seed = pd.DataFrame([{
        "sub_category": None, "jenis_unit": "", "jumlah_unit": 1, "pa_percent": 85
    }])

def main():
    # Sidebar with general parameters (render early so always visible)
    with st.sidebar:
        st.header("⚙️ General Parameters")
        competency_factor = st.slider("Competency Factor Mechanic", min_value=0.1, max_value=1.0, value=0.6, step=0.01)
        jarak_km = st.number_input("Jarak Rata-rata Area Kerja (KM)", min_value=0.0, value=10.0, step=0.5)
        st.markdown("---")
        st.caption("Isi daftar unit di kanan (bisa paste dari Excel). Setelah selesai, klik Hitung FTE.")

    # Load backend (show error if fails but keep sidebar)
    try:
        backend = get_backend()
    except BackendDataError as exc:
        st.error("Gagal memuat data BACKEND: " + str(exc))
        st.stop()

    sub_opts = backend.sub_categories or []
    sites = backend.sites or []

    # Site selector (placed below header so it's prominent)
    site = st.selectbox("Site", options=sites if sites else ["-"])

    # Show dynamic metrics for selected Site
    lost_time_site = backend.lost_time.get(site, float("nan"))
    ratio_shift_site = backend.ratio_shift.get(site, float("nan"))
    c1, c2, c3 = st.columns([2, 2, 2])
    c1.metric("Lost Time (site)", f"{lost_time_site:.2f} jam")
    c2.metric("Ratio Shift (site)", f"{ratio_shift_site:.2f}")
    c3.metric("Competency Factor", f"{competency_factor:.2f}")

    st.markdown('<div class="section-label">Unit Entries</div>', unsafe_allow_html=True)
    st.caption("Gunakan dropdown Sub Category (dari BACKEND) — Jenis Unit diisi manual. Jumlah Unit integer. PA% 1-100.")

    # Data editor (use st.data_editor / st.experimental_data_editor depending on version)
    try:
        # prefer st.data_editor if available
        edited = st.data_editor(
            st.session_state.units_seed,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "sub_category": st.column_config.SelectboxColumn("Sub Category", options=sub_opts, required=True),
                "jenis_unit": st.column_config.TextColumn("Jenis Unit / Model"),
                "jumlah_unit": st.column_config.NumberColumn("Jumlah Unit", min_value=1, step=1),
                "pa_percent": st.column_config.NumberColumn("PA %", min_value=1, max_value=100, step=1),
            },
            key="units_editor",
        )
    except Exception:
        # fallback for older streamlit versions
        edited = st.experimental_data_editor(st.session_state.units_seed, num_rows="dynamic", key="units_editor_fallback", use_container_width=True)

    # Provide a small derived preview table (read-only) showing site-derived columns (helpful UX)
    df_preview = edited.copy()
    df_preview["Site"] = site
    df_preview["Lost Time (site)"] = lost_time_site
    df_preview["Ratio Shift (site)"] = ratio_shift_site
    df_preview["Competency Factor"] = competency_factor
    df_preview["Jarak (KM)"] = jarak_km
    st.markdown("Preview (derived values per row)")
    st.dataframe(df_preview, use_container_width=True)

    # Compute button
    if st.button("Hitung FTE", type="primary"):
        # validation: site must have ratio_shift and lost_time
        if site not in backend.ratio_shift or site not in backend.lost_time:
            st.error(f"Site '{site}' tidak lengkap datanya di BACKEND (Ratio Shift / Lost Time). Periksa sheet BACKEND.")
            return

        df_exec = edited.copy()
        # ensure required columns
        for col in ("sub_category", "jenis_unit", "jumlah_unit", "pa_percent"):
            if col not in df_exec.columns:
                st.error(f"Kolom '{col}' tidak ditemukan di tabel input. Pastikan tabel berformat benar.")
                return
        df_exec = df_exec.dropna(subset=["sub_category"])
        if df_exec.empty:
            st.error("Tidak ada baris Sub Category valid. Isi minimal 1 baris.")
            return

        per_row_results: List[Dict[str, Any]] = []
        raw_list = []

        # iterate rows and compute raw per unit
        for idx, row in df_exec.iterrows():
            # map UI sub_category to original sheet name
            sc_ui = row["sub_category"]
            orig_sc = backend.original_sub_name(sc_ui) or sc_ui

            # build inputs (ensure types)
            try:
                inputs = FTEInput(
                    site=site,
                    competency_factor=float(competency_factor),
                    jarak_km=float(jarak_km),
                    sub_category=orig_sc,
                    jenis_unit=str(row.get("jenis_unit", "")),
                    pa_percent=float(row.get("pa_percent", 85)),
                    populasi=float(row.get("jumlah_unit", 1)),
                )
            except Exception as e:
                st.error(f"Baris {idx + 1}: kesalahan nilai input - {e}")
                return

            try:
                res = compute_fte_raw(inputs, backend)
            except CalculationError as exc:
                st.error(f"Baris {idx + 1} (Sub Category '{sc_ui}'): {exc}")
                return
            per_row_results.append((row.to_dict(), res))
            raw_list.append(res["raw"])

        # aggregate (ROUND once)
        agg = aggregate_units(raw_list)

        # Display per-row raw results
        st.markdown('<div class="section-label">Hasil Per-Unit (belum dibulatkan)</div>', unsafe_allow_html=True)
        for i, (row_def, res) in enumerate(per_row_results, start=1):
            st.markdown(f'<div class="result-card"><strong>Unit #{i} — {row_def.get("sub_category")} / {row_def.get("jenis_unit")} (x{row_def.get("jumlah_unit")})</strong></div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                render_fte_table_raw(res["raw"])
            with c2:
                # compute raw cost per month columns
                cost_raw = {}
                for role in ROLES + ["Total"]:
                    cost_raw[role] = {m: res["raw"][role][m] * COST_RATE[m] for m in MONTH_COLS}
                    cost_raw[role]["Tot"] = sum(cost_raw[role][m] for m in MONTH_COLS)
                render_cost_table(cost_raw)

        # Display aggregated rounded totals and costs
        st.markdown('<div class="section-label">Total Agregat (dibulatkan sekali)</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            render_fte_table(agg["fte"])
        with c2:
            render_cost_table(agg["cost"])

        # Optionally show intermediate debug (comment out in production)
        with st.expander("🔍 Intermediate / Debug"):
            st.write("Per-row intermediate values:")
            for i, (_, res) in enumerate(per_row_results, start=1):
                st.write(f"Unit #{i} intermediate:", res.get("intermediate", {}))

if __name__ == "__main__":
    main()
