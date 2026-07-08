"""
Konfigurasi global untuk FTE Calculator.
"""

# ID Google Spreadsheet (BACKEND) - sumber data referensi
SPREADSHEET_ID = "1YRvXt0AE-dVBVwRvLtsb57Qz8DYd9YbVQlVbRD31C7I"
BACKEND_SHEET_NAME = "BACKEND"

# Endpoint export CSV publik (spreadsheet harus di-share minimal "Anyone with link - Viewer")
def gsheet_csv_url(sheet_name: str, spreadsheet_id: str = SPREADSHEET_ID) -> str:
    return (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}"
        f"/gviz/tq?tqx=out:csv&sheet={sheet_name}"
    )

# Konstanta rumus (sesuai sheet "Final Calculation")
BASE_MECHANIC_HOURS = 12       # basis jam kerja mekanik/hari sebelum dikurangi Lost Time & travel
HOURS_PER_DAY = 24             # basis 24 jam untuk breakdown hours
TRAVEL_DIVISOR = 40            # pembagi Jarak (KM) -> jam perjalanan (D4/40)

# Cost rate per FTE (Rp) - ditetapkan eksplisit oleh user, bukan dari BACKEND
COST_RATE = {
    "M1": 10_000_000,
    "M2": 8_500_000,
    "M3": 6_500_000,
}

ROLES = ["Mechanic", "Electric", "Welder"]
MONTH_COLS = ["M1", "M2", "M3"]

# Cache TTL untuk data BACKEND (detik)
CACHE_TTL_SECONDS = 600
