"""
FTE Calculator - Redesigned Streamlit App (multi-unit)
- General parameters (Site, competency factor, jarak)
- Dynamic Unit editor (multiple rows)
- Jenis Unit: manual text input
- Jumlah Unit: integer (1..)
- PA: integer 1..100
- Uses backend.original_sub_name(...) to map UI selection to sheet name
"""
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


# ---- Session state helpers for dynamic rows ----
def _init_session():
    if "unit_rows" not in st.session_state:
        st.session_state.unit_rows = [
            {"id": 1, "sub_category": None, "jenis_unit": "", "jumlah_unit": 1, "pa_percent": 85}
        ]
        st.session_state.next_row_id = 2


def add_row(default_sub=None, default_jumlah=1, default_pa=85):
    st.session_state.unit_rows.append({
        "id": st.session_state.next_row_id,
        "sub_category": default_sub,
        "jenis_unit": "",
        "jumlah_unit": default_jumlah,
        "pa_percent": default_pa,
    })
    st.session_state.next_row_id += 1


def remove_row(row_id: int):
    st.session_state.unit_rows = [r for r in st.session_state.unit_rows if r["id"] != row_id]


# ---- App main ----
def main():
    st.title("🧮 FTE Calculator (Redesigned)")
    # logo (optional)
    try:
        st.image("logo_putih.png", width=180)
    except Exception:
        # ignore if not found
        pass

    st.caption(
        "Kalkulator FTE untuk banyak unit sekaligus. Isi General parameters lalu tambahkan/buat baris unit."
    )

    try:
        backend = get_backend()
    except BackendDataError as exc:
        st.error(str(exc))
        st.info(
            f"Pastikan spreadsheet `{SPREADSHEET_ID}` (sheet `{BACKEND_SHEET_NAME}`) dapat diakses."
        )
        st.stop()

    _init_session()

    with st.sidebar:
        st.header("⚙️ General Parameters")
        sites = getattr(backend, "sites", []) or []
        if not sites:
            st.warning("Daftar Site kosong di BACKEND — silakan periksa sheet BACKEND.")
        site = st.selectbox("Site", options=sites if sites else ["-"])

        competency_factor = st.slider(
            "Competency Factor Mechanic", min_value=0.1, max_value=1.0, value=0.6, step=0.01,
        )

        jarak_km = st.number_input(
            "Jarak Rata-rata Area Kerja (KM)", min_value=0.0, value=10.0, step=0.5,
        )

        st.markdown("---")
        st.header("🧩 Unit Editor (multiple rows)")
        st.caption("Tambah baris untuk menghitung banyak unit sekaligus. Jenis Unit manual.")

        # Render dynamic rows
        sub_opts = getattr(backend, "sub_categories", []) or []
        for row in list(st.session_state.unit_rows):  # iterate on a copy to allow modification
            rid = row["id"]
            with st.expander(f"Unit #{rid}", expanded=True):
                c1, c2, c3, c4, c5 = st.columns([3, 3, 2, 2, 1])
                # Sub Category select (fallback to manual input if backend empty)
                if sub_opts:
                    # Determine index fallback
                    try:
                        idx = sub_opts.index(row["sub_category"]) if row.get("sub_category") in sub_opts else 0
                    except Exception:
                        idx = 0
                    sc = c1.selectbox("Sub Category", options=sub_opts, index=idx, key=f"sc_{rid}")
                else:
                    sc = c1.text_input("Sub Category (manual)", value=row.get("sub_category") or "", key=f"sc_{rid}")

                ju = c2.text_input("Jenis Unit (manual)", value=row.get("jenis_unit", ""), key=f"ju_{rid}")

                # Jumlah Unit integer
                jumlah = c3.number_input(
                    "Jumlah Unit", min_value=1, value=int(row.get("jumlah_unit", 1)), step=1, format="%d",
                    key=f"jumlah_{rid}"
                )

                pa = c4.slider("PA (%)", min_value=1, max_value=100, value=int(row.get("pa_percent", 85)), key=f"pa_{rid}")

                if c5.button("Hapus", key=f"rm_{rid}"):
                    remove_row(rid)
                    st.experimental_rerun()

                # write back
                for r in st.session_state.unit_rows:
                    if r["id"] == rid:
                        r["sub_category"] = sc
                        r["jenis_unit"] = ju
                        r["jumlah_unit"] = int(jumlah)
                        r["pa_percent"] = int(pa)
                        break

        add_col1, add_col2 = st.columns([1, 4])
        if add_col1.button("Tambah Unit"):
            add_row()
            st.experimental_rerun()

        st.markdown("---")
        with st.expander("Pengaturan Lanjutan (opsional)"):
            _ = st.number_input("Default Jumlah Unit untuk baris baru", min_value=1, value=1, step=1)

        submitted = st.button("Hitung FTE", type="primary", use_container_width=True)

    if not submitted:
        st.info("Isi parameter di sidebar, lalu klik Hitung FTE.")
        return

    # Validation: ensure sub_category exists or can be mapped
    missing = []
    for r in st.session_state.unit_rows:
        sc = r["sub_category"]
        if not sc:
            missing.append((r["id"], "Sub Category kosong"))
            continue
        # if backend provides mapping, ensure we can map to original name
        if getattr(backend, "sub_categories", []):
            orig = backend.original_sub_name(sc)
            if orig is None:
                missing.append((r["id"], f"Sub Category '{sc}' tidak ditemukan di BACKEND"))
    if missing:
        for mid, msg in missing:
            st.error(f"Baris {mid}: {msg}")
        return

    # Run compute per row and aggregate
    per_row_results = []
    aggregate_fte = {role: {"M1": 0.0, "M2": 0.0, "M3": 0.0, "Tot": 0.0} for role in ROLES + ["Total"]}
    aggregate_cost = {role: {"M1": 0.0, "M2": 0.0, "M3": 0.0, "Tot": 0.0} for role in ROLES + ["Total"]}
    intermediate_all: List[Dict[str, Any]] = []

    for r in st.session_state.unit_rows:
        sc = r["sub_category"]
        orig_sc = backend.original_sub_name(sc) if getattr(backend, "original_sub_name", None) else sc
        # If original name not found and no backend list, pass UI string (best-effort)
        sub_to_pass = orig_sc or sc

        inputs = FTEInput(
            site=site,
            competency_factor=competency_factor,
            jarak_km=jarak_km,
            sub_category=sub_to_pass,
            jenis_unit=r["jenis_unit"],
            pa_percent=int(r["pa_percent"]),
            populasi=int(r["jumlah_unit"]),
        )

        try:
            result = compute_fte(inputs, backend)
        except CalculationError as exc:
            st.error(f"Perhitungan untuk unit id={r['id']} gagal: {exc}")
            return

        per_row_results.append({"row": r.copy(), "result": result})
        # aggregate
        for role in ROLES + ["Total"]:
            fr = result["fte"][role]
            cr = result["cost"][role]
            aggregate_fte[role]["M1"] += float(fr["M1"])
            aggregate_fte[role]["M2"] += float(fr["M2"])
            aggregate_fte[role]["M3"] += float(fr["M3"])
            aggregate_fte[role]["Tot"] += float(fr["Tot"])

            aggregate_cost[role]["M1"] += float(cr["M1"])
            aggregate_cost[role]["M2"] += float(cr["M2"])
            aggregate_cost[role]["M3"] += float(cr["M3"])
            aggregate_cost[role]["Tot"] += float(cr["Tot"])

        intermediate_all.append({"row_id": r["id"], "intermediate": result.get("intermediate", {})})

    # Display results
    st.header("Hasil Per-Unit")
    for item in per_row_results:
        rr = item["row"]
        st.subheader(f"Unit #{rr['id']} — {rr['sub_category']} / {rr['jenis_unit']} (x{rr['jumlah_unit']})")
        c1, c2 = st.columns(2)
        with c1:
            st.write("FTE (per-role)")
            render_fte_table(item["result"]["fte"])
        with c2:
            st.write("Cost (per-role)")
            render_cost_table(item["result"]["cost"])

    st.header("Total Agregat (semua unit)")
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("📋 Output 1 — Tabel FTE (Agregat)")
        render_fte_table(aggregate_fte)
    with c2:
        st.subheader("💰 Output 2 — Cost Estimation (Agregat)")
        render_cost_table(aggregate_cost)

    with st.expander("🔍 Detail Perhitungan Semua Unit (Intermediate Values)"):
        st.json({"per_row": intermediate_all})


if __name__ == "__main__":
    main()
