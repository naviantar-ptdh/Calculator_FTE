# app.py (REPLACE with this redesigned version)
import streamlit as st
import pandas as pd
from typing import List, Dict, Any
from calculator import FTEInput, CalculationError, compute_fte
from config import ROLES, SPREADSHEET_ID, BACKEND_SHEET_NAME
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
        rows.append({
            "FTE": role,
            "M1": format_number(r["M1"]),
            "M2": format_number(r["M2"]),
            "M3": format_number(r["M3"]),
            "Tot": format_number(r["Tot"]),
        })
    df = pd.DataFrame(rows).set_index("FTE")
    st.table(df)

def render_cost_table(cost_table: Dict[str, Dict[str, float]]):
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

# session init
if "units_df" not in st.session_state:
    st.session_state.units_df = pd.DataFrame([{
        "sub_category": None,
        "jenis_unit": "",
        "jumlah_unit": 1,
        "pa_percent": 85
    }])

def add_blank_row():
    df = st.session_state.units_df
    new = pd.DataFrame([{"sub_category": None, "jenis_unit": "", "jumlah_unit": 1, "pa_percent": 85}])
    st.session_state.units_df = pd.concat([df, new], ignore_index=True)

def remove_selected_rows(indices: List[int]):
    df = st.session_state.units_df
    st.session_state.units_df = df.drop(indices).reset_index(drop=True)

def main():
    st.title("🧮 FTE Calculator (Redesigned Table Editor)")

    try:
        backend = get_backend()
    except BackendDataError as exc:
        st.error(str(exc))
        st.stop()

    # Layout: sidebar general, main editor + actions
    with st.sidebar:
        st.header("General Parameters")
        sites = getattr(backend, "sites", []) or []
        site = st.selectbox("Site", options=sites if sites else ["-"])
        competency_factor = st.slider("Competency Factor Mechanic", 0.1, 1.0, 0.6, 0.01)
        jarak_km = st.number_input("Jarak (KM)", min_value=0.0, value=10.0, step=0.5)

        st.markdown("---")
        st.button("Tambah Baris", on_click=add_blank_row)
        st.caption("Isi baris di tabel lalu klik Hitung FTE di bawah.")

    st.header("Unit Entries (editable table)")
    # prepare DataFrame for editor: ensure correct dtypes
    df = st.session_state.units_df.copy()
    # Ensure jumlah_unit int
    if "jumlah_unit" in df.columns:
        df["jumlah_unit"] = df["jumlah_unit"].fillna(1).astype(int)
    else:
        df["jumlah_unit"] = 1

    # provide dropdown options for sub_category via column_config if st.data_editor available
    try:
        # new Streamlit API
        editor_kwargs = {}
        sub_opts = getattr(backend, "sub_categories", []) or []
        if sub_opts:
            # create option mapping; data_editor will show values (but cannot enforce select in older versions)
            # We'll still supply the list in note and allow user to type/paste if needed
            st.caption("Pilih Sub Category dari dropdown (ketik untuk mencari). Jika kosong, isi manual.")
        edited = st.experimental_data_editor(df, num_rows="dynamic", use_container_width=True)
        # experimental_data_editor returns a DataFrame with edits
        st.session_state.units_df = edited.copy()
    except Exception:
        # fallback: simple inputs for each row (older streamlit)
        st.warning("Editor tabel tidak tersedia — menggunakan form fallback.")
        new_rows = []
        sub_opts = getattr(backend, "sub_categories", []) or []
        for i, row in df.iterrows():
            st.markdown(f"**Baris {i+1}**")
            sc = st.selectbox(f"Sub Category #{i+1}", options=sub_opts if sub_opts else ["-"], index=sub_opts.index(row["sub_category"]) if row["sub_category"] in sub_opts else 0, key=f"sc_{i}")
            ju = st.text_input(f"Jenis Unit #{i+1}", value=row.get("jenis_unit", ""), key=f"ju_{i}")
            jumlah = st.number_input(f"Jumlah Unit #{i+1}", min_value=1, value=int(row.get("jumlah_unit",1)), step=1, key=f"jml_{i}")
            pa = st.slider(f"PA #%{i+1}", 1, 100, int(row.get("pa_percent",85)), key=f"pa_{i}")
            new_rows.append({"sub_category": sc, "jenis_unit": ju, "jumlah_unit": int(jumlah), "pa_percent": int(pa)})
        st.session_state.units_df = pd.DataFrame(new_rows)

    # action: compute
    if st.button("Hitung FTE"):
        df_exec = st.session_state.units_df.copy()
        # validate
        if df_exec.empty:
            st.error("Tidak ada unit untuk dihitung.")
            return
        # Normalize missing columns
        for col in ["sub_category","jenis_unit","jumlah_unit","pa_percent"]:
            if col not in df_exec.columns:
                df_exec[col] = "" if col in ("sub_category","jenis_unit") else 1
        # run compute per row
        per_row_results = []
        agg_fte = {role: {"M1":0,"M2":0,"M3":0,"Tot":0} for role in ROLES+["Total"]}
        agg_cost = {role: {"M1":0,"M2":0,"M3":0,"Tot":0} for role in ROLES+["Total"]}

        for idx, r in df_exec.iterrows():
            sc_ui = r["sub_category"]
            orig_sc = backend.original_sub_name(sc_ui) if getattr(backend, "original_sub_name", None) else sc_ui
            sub_to_pass = orig_sc or sc_ui
            inputs = FTEInput(
                site=site,
                competency_factor=competency_factor,
                jarak_km=jarak_km,
                sub_category=sub_to_pass,
                jenis_unit=str(r.get("jenis_unit","")),
                pa_percent=int(r.get("pa_percent",85)),
                populasi=int(r.get("jumlah_unit",1)),
            )
            try:
                res = compute_fte(inputs, backend)
            except CalculationError as exc:
                st.error(f"Baris {idx+1} gagal: {exc}")
                return
            per_row_results.append((r.to_dict(), res))
            for role in ROLES+["Total"]:
                fr = res["fte"][role]
                cr = res["cost"][role]
                agg_fte[role]["M1"] += float(fr["M1"])
                agg_fte[role]["M2"] += float(fr["M2"])
                agg_fte[role]["M3"] += float(fr["M3"])
                agg_fte[role]["Tot"] += float(fr["Tot"])
                agg_cost[role]["M1"] += float(cr["M1"])
                agg_cost[role]["M2"] += float(cr["M2"])
                agg_cost[role]["M3"] += float(cr["M3"])
                agg_cost[role]["Tot"] += float(cr["Tot"])

        # display per-row and aggregate
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
