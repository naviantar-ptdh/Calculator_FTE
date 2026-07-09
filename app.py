# app.py
"""
FTE Calculator — PT Dharma Henwa
Desain diselaraskan dengan HR Recruitment Portal (naviantar-ptdh/202605-centralized).
"""
import streamlit as st
import pandas as pd
from typing import Dict
from calculator import FTEInput, CalculationError, compute_fte
from config import ROLES
from data_loader import load_backend_data, BackendDataError

st.set_page_config(
    page_title="FTE Calculator",
    page_icon="🧮",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── Sumber logo ──
# Prioritas 1: baca file lokal "logo_putih.png" dari root repo dan embed sebagai
# base64 (data URI). Ini paling tahan banting -- TIDAK butuh koneksi internet
# sama sekali saat render, jadi tidak akan gagal walau raw.githubusercontent.com
# diblokir firewall/jaringan kantor (penyebab paling umum logo tak muncul).
# Prioritas 2 (fallback kalau file lokal belum ter-commit): URL GitHub raw.
import base64
from pathlib import Path


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

# ── Design tokens (selaras dengan HR Portal) ──
OR = "#E8440A"
OR_L = "#FFF0EB"
OR_M = "#FFD0BD"
BK = "#111111"
GY1 = "#FAFAFA"
GY2 = "#F4F4F5"
GY3 = "#E4E4E7"
GY4 = "#A1A1AA"
TX = "#18181B"
TX2 = "#52525B"
GR = "#16A34A"
GR_L = "#F0FDF4"
RD = "#DC2626"
RD_L = "#FEF2F2"

CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

*, *::before, *::after {{ box-sizing: border-box; }}
html, body, .stApp {{
    font-family: 'Inter', -apple-system, sans-serif !important;
    background: {GY1} !important;
    color: {TX} !important;
}}
#MainMenu, footer, header, .stDeployButton {{ display: none !important; }}

.nav {{
    height: 60px; background: #fff; border-bottom: 1px solid {GY3};
    display: flex; align-items: center; padding: 0 8px; margin: -1rem -1rem 24px -1rem;
    gap: 12px;
}}
.nav-brand {{ display: flex; align-items: center; gap: 12px; }}
.nav-divider {{ width: 1px; height: 22px; background: {GY3}; }}
.nav-title {{ font-size: 14px; font-weight: 600; color: {TX}; letter-spacing: -0.01em; }}
.nav-sub {{ font-size: 11.5px; color: {GY4}; }}

.page-eyebrow {{
    font-size: 11px; font-weight: 600; letter-spacing: 0.08em;
    text-transform: uppercase; color: {OR}; margin-bottom: 4px;
}}
.page-title {{ font-size: 24px; font-weight: 700; letter-spacing: -0.03em; color: {TX}; margin: 0 0 4px 0; }}
.page-subtitle {{ font-size: 13px; color: {TX2}; margin: 0 0 20px 0; }}

.section-label {{
    font-size: 11px; font-weight: 700; letter-spacing: 0.1em; text-transform: uppercase;
    color: {GY4}; margin: 28px 0 12px; display: flex; align-items: center; gap: 10px;
}}
.section-label::after {{ content: ''; flex: 1; height: 1px; background: {GY3}; }}

section[data-testid="stSidebar"] {{ background: #fff !important; border-right: 1px solid {GY3} !important; }}
section[data-testid="stSidebar"] h2 {{ font-size: 13px !important; font-weight: 700 !important; color: {TX} !important; text-transform: uppercase; letter-spacing: 0.06em; }}

div[data-testid="stMetric"] {{
    background: #fff !important; border: 1px solid {GY3} !important;
    border-radius: 10px !important; padding: 14px 16px !important;
}}
div[data-testid="stMetric"] label {{ color: {GY4} !important; font-size: 10.5px !important; font-weight: 600 !important; text-transform: uppercase; letter-spacing: 0.06em; }}

button[kind="primary"] {{
    background: {OR} !important; border: none !important; color: #fff !important;
    font-weight: 600 !important; border-radius: 8px !important; letter-spacing: -0.01em !important;
}}
button[kind="primary"]:hover {{ opacity: 0.88 !important; }}

div[data-testid="stDataFrame"], div[data-testid="stDataEditor"] {{
    border-radius: 10px !important; border: 1px solid {GY3} !important; overflow: hidden !important;
}}

.result-card {{
    background: #fff; border: 1px solid {GY3}; border-radius: 12px;
    padding: 18px 20px; margin-bottom: 14px;
}}
.result-card-title {{ font-size: 13.5px; font-weight: 700; color: {TX}; margin-bottom: 10px; }}

div[data-testid="stExpander"] {{ border: 1px solid {GY3} !important; border-radius: 10px !important; background: #fff !important; }}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

st.markdown(f"""
<div class="nav">
    <div class="nav-brand">
        <img src="{LOGO_SRC}" style="height:28px;width:auto;"
             onerror="this.style.display='none';" alt="PTDH Logo"/>
        <div class="nav-divider"></div>
        <div>
            <div class="nav-title">FTE Calculator</div>
            <div class="nav-sub">PT Dharma Henwa — Plant &amp; Maintenance</div>
        </div>
    </div>
</div>
""", unsafe_allow_html=True)

if not _LOGO_DATA_URI:
    st.info(
        "ℹ️ File **logo_putih.png** belum ditemukan di root repo ini, jadi logo sementara "
        "dimuat dari URL GitHub eksternal (bisa gagal kalau diblokir jaringan). "
        "Untuk hasil paling stabil: commit file `logo_putih.png` ke root repo `Calculator_FTE` Anda.",
        icon="🖼️",
    )


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
    st.dataframe(pd.DataFrame(rows).set_index("FTE"), width="stretch")


def render_cost_table(cost_table: Dict[str, Dict[str, float]]):
    rows = []
    for role in ROLES + ["Total"]:
        r = cost_table[role]
        rows.append({"Cost": role, "M1": format_currency(r["M1"]), "M2": format_currency(r["M2"]),
                     "M3": format_currency(r["M3"]), "Tot": format_currency(r["Tot"])})
    st.dataframe(pd.DataFrame(rows).set_index("Cost"), width="stretch")


# ─────────────────────────────────────────────────────────────
# STATE MANAGEMENT — PENTING soal bug "harus input dua kali":
# st.data_editor dengan `key=` SUDAH otomatis persist state-nya sendiri di
# st.session_state["units_editor"]. Sebelumnya kode ini membuat SUMBER GANDA
# (session_state.units_df yang di-copy() lalu dilempar balik jadi `data=` di
# render berikutnya) — setiap kali objek DataFrame baru (hasil .copy()) dikirim
# sebagai `data`, Streamlit bisa menganggapnya dataset baru dan sebagian edit
# yang baru saja di-commit di frontend belum sempat "nempel", sehingga user
# harus mengetik ulang. Fix: seed HANYA SEKALI, lalu biarkan `key=` yang
# mengelola state sepenuhnya — jangan pernah menulis ulang ke seed itu.
# ─────────────────────────────────────────────────────────────
if "units_seed" not in st.session_state:
    st.session_state.units_seed = pd.DataFrame([{
        "sub_category": None, "jenis_unit": "", "jumlah_unit": 1, "pa_percent": 85
    }])


def main():
    # Sidebar dirender DULUAN, sebelum backend di-load — supaya field manual/statis
    # (Competency Factor, Jarak KM) TETAP TAMPIL walau fetch BACKEND gagal.
    # Sebelumnya sidebar baru muncul setelah backend sukses, jadi begitu BACKEND
    # error, seluruh sidebar (termasuk field ini) ikut lenyap dari layar.
    with st.sidebar:
        st.header("General Parameters")
        competency_factor = st.slider("Competency Factor Mechanic", 0.1, 1.0, 0.6, 0.01)
        jarak_km = st.number_input("Jarak Rata-rata Area Kerja (KM)", min_value=0.0, value=10.0, step=0.5)
        site_placeholder = st.empty()
        st.markdown("---")
        st.caption(
            "💡 Anda bisa **copy-paste** langsung dari Excel/Sheets ke tabel di kanan "
            "(blok sel di Excel → Ctrl+C → klik sel pertama tabel → Ctrl+V). "
            "Setelah mengetik di sebuah sel, tekan **Enter/Tab** dulu untuk commit "
            "sebelum klik 'Hitung FTE'."
        )

    try:
        backend = get_backend()
    except BackendDataError as exc:
        with site_placeholder:
            st.text_input("Site", value="", disabled=True, help="Menunggu BACKEND berhasil dimuat...")
        st.error("Gagal memuat data BACKEND — detail diagnosa di bawah:")
        st.code(str(exc))
        st.stop()

    sub_opts = backend.sub_categories or []
    sites = backend.sites or []
    with site_placeholder:
        site = st.selectbox("Site", options=sites if sites else ["-"])

    with st.expander("🔧 Debug BACKEND (buka jika ada error 'Sub Category tidak ditemukan')"):
        st.write("Jumlah Sub Category terbaca:", len(sub_opts))
        st.code("\n".join(repr(x) for x in backend.load_factor.index.tolist()))
        st.write("RACI:", backend.raci, "| Sites:", backend.sites)
        if st.button("🔄 Clear cache & reload BACKEND"):
            st.cache_data.clear()
            st.rerun()

    st.markdown('<div class="page-eyebrow">Perhitungan</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-title">FTE &amp; Cost Estimator</div>', unsafe_allow_html=True)
    st.markdown('<div class="page-subtitle">Isi daftar unit di bawah, lalu klik Hitung FTE untuk melihat estimasi Mechanic / Electric / Welder per shift.</div>', unsafe_allow_html=True)

    st.markdown('<div class="section-label">Parameter (D3:D6 di sheet Final Calculation)</div>', unsafe_allow_html=True)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Competency Factor", f"{competency_factor:.2f}")
    m2.metric("Jarak Area Kerja", f"{jarak_km:.1f} km")
    m3.metric("Lost Time (auto, Site)", f"{backend.lost_time.get(site, float('nan')):.2f}")
    m4.metric("Ratio Shift (auto, Site)", f"{backend.ratio_shift.get(site, float('nan')):.2f}")

    st.markdown('<div class="section-label">Unit Entries</div>', unsafe_allow_html=True)

    # `data` HANYA dari seed statis di session_state (tidak pernah ditimpa ulang
    # dari hasil edit) — `key="units_editor"` yang menyimpan & mempertahankan
    # seluruh perubahan pengguna secara otomatis antar-rerun.
    edited = st.data_editor(
        st.session_state.units_seed,
        num_rows="dynamic",
        width="stretch",
        column_config={
            "sub_category": st.column_config.SelectboxColumn(
                "Sub Category", options=sub_opts, required=True,
            ),
            "jenis_unit": st.column_config.TextColumn("Unit / Model (mis. R9200)"),
            "jumlah_unit": st.column_config.NumberColumn("Jumlah Unit", min_value=1, step=1),
            "pa_percent": st.column_config.NumberColumn("PA %", min_value=1, max_value=100, step=1),
        },
        key="units_editor",
    )

    if st.button("Hitung FTE", type="primary"):
        df_exec = edited.dropna(subset=["sub_category"])
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

        st.markdown('<div class="section-label">Hasil Per-Unit</div>', unsafe_allow_html=True)
        for i, (row_def, res) in enumerate(per_row_results, start=1):
            st.markdown(f'<div class="result-card"><div class="result-card-title">'
                        f'Unit #{i} — {row_def.get("sub_category")} / {row_def.get("jenis_unit")} '
                        f'(x{row_def.get("jumlah_unit")})</div></div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            with c1:
                render_fte_table(res["fte"])
            with c2:
                render_cost_table(res["cost"])

        st.markdown('<div class="section-label">Total Agregat</div>', unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        with c1:
            render_fte_table(agg_fte)
        with c2:
            render_cost_table(agg_cost)


if __name__ == "__main__":
    main()
