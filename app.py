# app.py
import streamlit as st
import pandas as pd
from typing import Dict
from calculator import FTEInput, CalculationError, compute_fte
from config import ROLES
from data_loader import load_backend_data, BackendDataError

st.set_page_config(page_title="FTE Calculator", page_icon="🧮", layout="wide")


@st.cache_data(ttl=600, show_spinner="Mengambil data referensi dari BACKEND...")
def get_backend():
    return load_backend_data()


def format_number(x: float) -> str:
    return f"{x:,.0f}".replace(",", ".")


def format_currency(x: float) -> str:
    return f"Rp {x:,.0f}".replace(",", ".")


def render_fte_table(fte_table: Dict[str, Dict[str, float]]):
    rows = []
    for role in ROLES + ["Total"]:
        r = fte_table[role]
        rows.append({"FTE": role, "M1": format_number(r["M1"]), "M2": format_number(r["M2"]),
                     "M3": format_number(r["M3"]), "Tot": format_number(r["Tot"])})
    st.table(pd.DataFrame(rows).set_index("FTE"))


def render_cost_table(cost_table: Dict[str, Dict[str, float]]):
    rows = []
    for role in ROLES + ["Total"]:
        r = cost_table[role]
        rows.append({"Cost": role, "M1": format_currency(r["M1"]), "M2": format_currency(r["M2"]),
                     "M3": format_currency(r["M3"]), "Tot": format_currency(r["Tot"])})
    st.table(pd.DataFrame(rows).set_index("Cost"))


if "units_df" not in st.session_state:
    st.session_state.units_df = pd.DataFrame([{
        "sub_category": None, "jenis_unit": "", "jumlah_unit": 1, "pa_percent": 85
    }])


def main():
   col1, col2 = st.columns([1, 8], vertical_alignment="center")
   with col1:
        st.image("logo_putih.png", width=70)
   with col2:
        st.title("FTE Calculator")
   try:
        backend = get_backend()
   except BackendDataError as exc:
        st.error("Gagal memuat data BACKEND — detail diagnosa di bawah:")
        st.code(str(exc))
        st.stop()

    sub_opts = backend.sub_categories or []

    with st.expander("🔧 Debug BACKEND (klik untuk buka jika ada error 'Sub Category tidak ditemukan')"):
        st.write("Jumlah Sub Category terbaca:", len(sub_opts))
        st.write("Isi load_factor.index (repr, untuk cek karakter tersembunyi):")
        st.code("\n".join(repr(x) for x in backend.load_factor.index.tolist()))
        st.write("Tipe index:", type(backend.load_factor.index).__name__)
        st.write("RACI:", backend.raci)
        st.write("Sites:", backend.sites)
        if st.button("🔄 Clear cache & reload BACKEND"):
            st.cache_data.clear()
            st.rerun()

    with st.sidebar:
        st.header("General Parameters")
        sites = backend.sites or []
        site = st.selectbox("Site", options=sites if sites else ["-"])
        competency_factor = st.slider("Competency Factor Mechanic", 0.1, 1.0, 0.6, 0.01)
        jarak_km = st.number_input("Jarak (KM)", min_value=0.0, value=10.0, step=0.5)
        st.markdown("---")
        st.caption("Tambah/hapus baris langsung di tabel (tombol + di baris terakhir tabel).")

    st.header("Unit Entries")
    df = st.session_state.units_df.copy()
    if "jumlah_unit" in df.columns:
        df["jumlah_unit"] = df["jumlah_unit"].fillna(1).astype(int)

    # st.data_editor (API stabil sejak Streamlit 1.23+, menggantikan
    # st.experimental_data_editor yang sudah dihapus di versi >=1.24)
    edited = st.data_editor(
        df,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "sub_category": st.column_config.SelectboxColumn(
                "Sub Category", options=sub_opts, required=True,
            ),
            "jenis_unit": st.column_config.TextColumn("Jenis Unit"),
            "jumlah_unit": st.column_config.NumberColumn("Jumlah Unit", min_value=1, step=1),
            "pa_percent": st.column_config.NumberColumn("PA %", min_value=1, max_value=100, step=1),
        },
        key="units_editor",
    )
    st.session_state.units_df = edited.copy()

    if st.button("Hitung FTE", type="primary"):
        df_exec = st.session_state.units_df.copy()
        df_exec = df_exec.dropna(subset=["sub_category"])
        if df_exec.empty:
            st.error("Tidak ada unit valid untuk dihitung. Pilih Sub Category minimal 1 baris.")
            return

        per_row_results = []
        agg_fte = {role: {"M1": 0.0, "M2": 0.0, "M3": 0.0, "Tot": 0.0} for role in ROLES + ["Total"]}
        agg_cost = {role: {"M1": 0.0, "M2": 0.0, "M3": 0.0, "Tot": 0.0} for role in ROLES + ["Total"]}

        for idx, r in df_exec.iterrows():
            orig_sc = backend.original_sub_name(r["sub_category"]) or r["sub_category"]
            inputs = FTEInput(
                site=site,
                competency_factor=competency_factor,
                jarak_km=jarak_km,
                sub_category=orig_sc,
                jenis_unit=str(r.get("jenis_unit", "")),
                pa_percent=int(r.get("pa_percent", 85)),
                populasi=int(r.get("jumlah_unit", 1)),
            )
            try:
                res = compute_fte(inputs, backend)
            except CalculationError as exc:
                st.error(f"Baris {idx + 1} gagal: {exc}")
                return

            per_row_results.append((r.to_dict(), res))
            for role in ROLES + ["Total"]:
                for m in ("M1", "M2", "M3", "Tot"):
                    agg_fte[role][m] += float(res["fte"][role][m])
                    agg_cost[role][m] += float(res["cost"][role][m])

        st.header("Hasil Per-Unit")
        for i, (row_def, res) in enumerate(per_row_results, start=1):
            st.subheader(f"Unit #{i} — {row_def.get('sub_category')} / {row_def.get('jenis_unit')} (x{row_def.get('jumlah_unit')})")
            c1, c2 = st.columns(2)
            with c1:
                render_fte_table(res["fte"])
            with c2:
                render_cost_table(res["cost"])

        st.header("Total Agregat")
        c1, c2 = st.columns(2)
        with c1:
            render_fte_table(agg_fte)
        with c2:
            render_cost_table(agg_cost)


if __name__ == "__main__":
    main()
