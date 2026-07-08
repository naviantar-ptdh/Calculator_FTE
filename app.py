# app.py (REPLACE your existing app.py with this or merge accordingly)
"""
FTE Calculator - Streamlit App (redesigned)
- General inputs (Site, Competency Factor, Jarak)
- Dynamic Units editor (multiple rows)
- Jenis Unit = manual text input
- Jumlah Unit = integer input
- PA = integer (1-100)
- Compute per-row (call existing compute_fte) and aggregate results
"""

import streamlit as st
import pandas as pd
from typing import List, Dict
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


# Helpers for session state management of rows
def _init_session():
    if "unit_rows" not in st.session_state:
        # default one row
        st.session_state.unit_rows = [
            {"id": 1, "sub_category": None, "jenis_unit": "", "jumlah_unit": 1, "pa_percent": 85}
        ]
        st.session_state.next_row_id = 2


def add_row():
    st.session_state.unit_rows.append({
        "id": st.session_state.next_row_id,
        "sub_category": None,
        "jenis_unit": "",
        "jumlah_unit": 1,
        "pa_percent": 85,
    })
    st.session_state.next_row_id += 1


def remove_row(row_id: int):
    st.session_state.unit_rows = [r for r in st.session_state.unit_rows if r["id"] != row_id]


def main():
    st.title("🧮 FTE Calculator (Redesigned)")

    try:
        backend = get_backend()
    except BackendDataError as exc:
        st.error(str(exc))
        st.info(
            f"Pastikan spreadsheet dengan ID `{SPREADSHEET_ID}` sudah di-share sebagai "
            f"**Anyone with the link - Viewer**, dan sheet `{BACKEND_SHEET_NAME}` tersedia."
        )
        st.stop()

    _init_session()

    with st.sidebar:
        st.header("⚙️ General Parameters")
        # Sites: validate exists
        sites = getattr(backend, "sites", []) or []
        if not sites:
            st.warning("Daftar Site kosong di BACKEND — fungsi ratio_shift/lost_time mungkin tidak tersedia.")
        site = st.selectbox("Site", options=sites if sites else ["-"])

        competency_factor = st.slider(
            "Competency Factor Mechanic", min_value=0.1, max_value=1.0, value=0.6, step=0.01,
        )

        jarak_km = st.number_input(
            "Jarak Rata-rata Area Kerja (KM)", min_value=0.0, value=10.0, step=0.5,
        )

        st.markdown("---")
        st.header("🧩 Edit Unit(s) (multiple rows)")
        st.caption("Tambahkan baris unit sebanyak yang diinginkan. Jenis Unit diisi manual.")

        # Render dynamic rows
        for row in list(st.session_state.unit_rows):  # copy to allow mutation
            rid = row["id"]
            with st.expander(f"Unit #{rid}", expanded=True):
                cols = st.columns([3, 3, 2, 2, 1])
                # Sub Category select (loaded from backend.sub_categories)
                sub_opts = getattr(backend, "sub_categories", []) or []
                sc = cols[0].selectbox(
                    "Sub Category",
                    options=sub_opts if sub_opts else ["-"],
                    index=sub_opts.index(row["sub_category"]) if row.get("sub_category") in sub_opts else 0,
                    key=f"sc_{rid}"
                )
                # Jenis Unit = manual
                ju = cols[1].text_input(
                    "Jenis Unit (manual)",
                    value=row.get("jenis_unit", ""),
                    placeholder="mis. Big, Medium, Small",
                    key=f"ju_{rid}"
                )
                # Jumlah Unit = integer
                jumlah = cols[2].number_input(
                    "Jumlah Unit",
                    min_value=1, value=int(row.get("jumlah_unit", 1)), step=1,
                    format="%d",
                    key=f"jumlah_{rid}"
                )
                # PA percent
                pa = cols[3].slider(
                    "PA (%)",
                    min_value=1, max_value=100, value=int(row.get("pa_percent", 85)),
                    key=f"pa_{rid}"
                )
                # remove button
                if cols[4].button("Hapus", key=f"rm_{rid}"):
                    remove_row(rid)
                    st.experimental_rerun()

                # write back to session_state list element
                # find and update
                for r in st.session_state.unit_rows:
                    if r["id"] == rid:
                        r["sub_category"] = sc
                        r["jenis_unit"] = ju
                        r["jumlah_unit"] = int(jumlah)
                        r["pa_percent"] = int(pa)
                        break

        cols_add = st.columns([1, 4])
        if cols_add[0].button("Tambah Unit"):
            add_row()
            st.experimental_rerun()

        st.markdown("---")
        st.markdown("Pengaturan lanjutan (opsional)")
        with st.expander("Pengaturan tambahan"):
            # Default per-row population input already present; show global default if needed
            default_pop = st.number_input(
                "Default Jumlah Unit untuk baris baru (integer)", min_value=1, value=1, step=1
            )

        submitted = st.button("Hitung FTE", type="primary", use_container_width=True)

    # If not submitted, show info
    if not submitted:
        st.info("Isi parameter dan unit di sidebar, lalu klik **Hitung FTE**.")
        return

    # Validation: ensure each sub_category exists in backend
    missing_subs = [r["sub_category"] for r in st.session_state.unit_rows if r["sub_category"] not in getattr(backend, "sub_categories", [])]
    if any(s == "-" or s is None for s in missing_subs):
        st.error("Ada baris unit dengan Sub Category kosong atau belum tersedia di BACKEND. Periksa kembali.")
        return

    # For each unit row, build FTEInput and call compute_fte; then aggregate
    per_row_results = []
    aggregate_fte = {role: {"M1": 0.0, "M2": 0.0, "M3": 0.0, "Tot": 0.0} for role in ROLES + ["Total"]}
    aggregate_cost = {role: {"M1": 0.0, "M2": 0.0, "M3": 0.0, "Tot": 0.0} for role in ROLES + ["Total"]}
    intermediate_all = []

    for row in st.session_state.unit_rows:
        # Build input
        inputs = FTEInput(
            site=site,
            competency_factor=competency_factor,
            jarak_km=jarak_km,
            sub_category=row["sub_category"],
            jenis_unit=row["jenis_unit"],
            pa_percent=row["pa_percent"],
            populasi=int(row["jumlah_unit"]),
        )
        # Run compute
        try:
            result = compute_fte(inputs, backend)
        except CalculationError as exc:
            st.error(f"Perhitungan untuk unit id={row['id']} gagal: {exc}")
            return

        per_row_results.append({"row": row, "result": result})
        # Aggregate FTE: assumes result['fte'] structure same as before
        for role in ROLES + ["Total"]:
            r = result["fte"][role]
            aggregate_fte[role]["M1"] += float(r["M1"])
            aggregate_fte[role]["M2"] += float(r["M2"])
            aggregate_fte[role]["M3"] += float(r["M3"])
            aggregate_fte[role]["Tot"] += float(r["Tot"])
        # Aggregate cost
        for role in ROLES + ["Total"]:
            r = result["cost"][role]
            aggregate_cost[role]["M1"] += float(r["M1"])
            aggregate_cost[role]["M2"] += float(r["M2"])
            aggregate_cost[role]["M3"] += float(r["M3"])
            aggregate_cost[role]["Tot"] += float(r["Tot"])

        # collect intermediate for debug
        intermediate_all.append({"row_id": row["id"], "intermediate": result.get("intermediate", {})})

    # Show per-row results and totals
    st.header("Hasil Per-Unit")
    for item in per_row_results:
        r = item["row"]
        st.subheader(f"Unit #{r['id']} — {r['sub_category']} / {r['jenis_unit']} (x{r['jumlah_unit']})")
        cols = st.columns(2)
        with cols[0]:
            st.write("FTE (per-role)")
            render_fte_table(item["result"]["fte"])
        with cols[1]:
            st.write("Cost (per-role)")
            render_cost_table(item["result"]["cost"])

    st.header("Total Agregat (semua unit)")
    cols = st.columns(2)
    with cols[0]:
        st.subheader("📋 Output 1 — Tabel FTE (Agregat)")
        render_fte_table(aggregate_fte)
    with cols[1]:
        st.subheader("💰 Output 2 — Cost Estimation (Agregat)")
        render_cost_table(aggregate_cost)

    with st.expander("🔍 Detail Perhitungan Semua Unit (Intermediate Values)"):
        st.json({"per_row": intermediate_all})


if __name__ == "__main__":
    main()
