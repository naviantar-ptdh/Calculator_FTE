"""
FTE Calculator - Streamlit App
Reimplementasi logika sheet "Final Calculation" (Excel) menggunakan BACKEND
(Google Spreadsheet) sebagai satu-satunya sumber data referensi.

Jalankan dengan:
    streamlit run app.py
"""

import pandas as pd
import streamlit as st

from calculator import FTEInput, CalculationError, compute_fte
from config import ROLES, MONTH_COLS, SPREADSHEET_ID, BACKEND_SHEET_NAME
from data_loader import load_backend_data, BackendDataError

st.set_page_config(page_title="FTE Calculator", page_icon="🧮", layout="wide")


@st.cache_data(ttl=600, show_spinner="Mengambil data referensi dari BACKEND...")
def get_backend():
    return load_backend_data()


def format_number(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def format_currency(x: float) -> str:
    return f"Rp {x:,.0f}".replace(",", ".")


def render_fte_table(fte_table: dict):
    rows = []
    for role in ROLES + ["Total"]:
        r = fte_table[role]
        rows.append({
            "FTE": role,
            "M1": format_number(r["M1"]),
            "M2": format_number(r["M2"]),
            "M3": format_number(r["M3"]),
            "Tot": format_number(r["Tot"]),
        })
    df = pd.DataFrame(rows).set_index("FTE")
    st.table(df)


def render_cost_table(cost_table: dict):
    rows = []
    for role in ROLES + ["Total"]:
        r = cost_table[role]
        rows.append({
            "Cost": role,
            "M1": format_currency(r["M1"]),
            "M2": format_currency(r["M2"]),
            "M3": format_currency(r["M3"]),
            "Tot": format_currency(r["Tot"]),
        })
    df = pd.DataFrame(rows).set_index("Cost")
    st.table(df)


def main():
    st.title("🧮 FTE Calculator")
    st.caption(
        "Kalkulator Full Time Equivalent (Mechanic / Electric / Welder) berdasarkan "
        "logika sheet **Final Calculation**, dengan data referensi live dari sheet **BACKEND**."
    )

    try:
        backend = get_backend()
    except BackendDataError as exc:
        st.error(str(exc))
        st.info(
            f"Pastikan spreadsheet dengan ID `{SPREADSHEET_ID}` sudah di-share sebagai "
            f"**Anyone with the link - Viewer**, dan sheet `{BACKEND_SHEET_NAME}` tersedia."
        )
        st.stop()

    with st.sidebar:
        st.header("⚙️ Input Parameter")

        site = st.selectbox("Site", options=backend.sites)

        competency_factor = st.slider(
            "Competency Factor Mechanic", min_value=0.1, max_value=1.0, value=0.6, step=0.01,
        )

        jarak_km = st.number_input(
            "Jarak Rata-rata Area Kerja (KM)", min_value=0.0, value=10.0, step=0.5,
        )

        sub_category = st.selectbox("Sub Category", options=backend.sub_categories)

        unit_options = backend.units_for(sub_category)
        jenis_unit = st.selectbox(
            "Jenis Unit", options=unit_options if unit_options else ["-"],
            help="Klasifikasi ukuran unit (Attribute) sesuai Sub Category, dari BACKEND.",
        )

        pa_percent = st.slider(
            "Target Physical Availability - PA (%)", min_value=1, max_value=100, value=85,
        )

        with st.expander("Pengaturan tambahan"):
            populasi = st.number_input(
                "Jumlah Unit / Equipment Population",
                min_value=1.0, value=1.0, step=1.0,
                help=(
                    "Tidak ada di daftar input awal; formula Final Calculation membutuhkan "
                    "jumlah populasi unit. Default = 1 (perhitungan per unit)."
                ),
            )

        submitted = st.button("Hitung FTE", type="primary", use_container_width=True)

    if not submitted:
        st.info("Isi parameter di sidebar, lalu klik **Hitung FTE**.")
        return

    inputs = FTEInput(
        site=site,
        competency_factor=competency_factor,
        jarak_km=jarak_km,
        sub_category=sub_category,
        jenis_unit=jenis_unit,
        pa_percent=pa_percent,
        populasi=populasi,
    )

    try:
        result = compute_fte(inputs, backend)
    except CalculationError as exc:
        st.error(str(exc))
        return

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📋 Output 1 — Tabel FTE")
        render_fte_table(result["fte"])
    with col2:
        st.subheader("💰 Output 2 — Cost Estimation")
        render_cost_table(result["cost"])

    with st.expander("🔍 Detail Perhitungan (Intermediate Values)"):
        st.json(result["intermediate"])


if __name__ == "__main__":
    main()
