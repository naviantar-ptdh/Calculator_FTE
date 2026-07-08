# FTE Calculator (Streamlit)

Reimplementasi murni Python/Streamlit dari sheet **Final Calculation** pada
`FTE__2_.xlsx`, dengan **BACKEND** (Google Spreadsheet) sebagai satu-satunya
sumber data referensi. Excel/Spreadsheet **tidak** dipakai sebagai mesin
hitung — hanya sebagai database yang dibaca live via CSV export.

Spreadsheet acuan:
https://docs.google.com/spreadsheets/d/1YRvXt0AE-dVBVwRvLtsb57Qz8DYd9YbVQlVbRD31C7I/edit

## Struktur Project

```
fte_calculator/
├── app.py            # UI Streamlit (input, tampilan tabel FTE & Cost)
├── data_loader.py     # Loader + parser sheet BACKEND (Google Sheets, live)
├── calculator.py      # Mesin hitung FTE & Cost (murni Python, tanpa Excel)
├── config.py          # Konstanta (ID spreadsheet, rate cost, konstanta rumus)
├── requirements.txt
└── README.md
```

## Cara Menjalankan

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Syarat Akses Spreadsheet

Loader menggunakan endpoint publik Google Sheets:

```
https://docs.google.com/spreadsheets/d/<ID>/gviz/tq?tqx=out:csv&sheet=BACKEND
```

Spreadsheet **harus** di-share minimal sebagai **"Anyone with the link -
Viewer"** agar endpoint ini bisa diakses tanpa autentikasi. Bila spreadsheet
bersifat privat/internal organisasi, ganti `data_loader._fetch_raw_csv()`
dengan otentikasi `gspread` + Service Account (lihat komentar di dalam file).

## Alur Perhitungan (ringkas)

Untuk kombinasi Site + Sub Category + Jenis Unit + PA% + Competency Factor +
Jarak yang dipilih user:

1. `Breakdown % (H) = 1 - PA%`
2. `Breakdown Hours (I) = 24 * H`
3. `EMHD (J) = 12 - LostTime(Site) - (Jarak/40)`
4. `FTE_role = ((I/J) * LoadFactor_role(SubCategory) * Populasi * RatioShift(Site)) / CompetencyFactor * RACI_role`
5. FTE role di-split ke M1/M2/M3 berdasarkan rasio dari BACKEND, lalu
   dibulatkan dengan `ROUND` (round-half-up, identik Excel `ROUND()`).
6. Cost = FTE (per bulan) × rate (M1=Rp10.000.000, M2=Rp8.500.000,
   M3=Rp6.500.000).

Formula ini divalidasi identik dengan sheet Excel asli (dibandingkan dengan
nilai `L10/M10/N10` pada sheet Final Calculation, cocok hingga 10 digit
desimal untuk skenario Big Exca @ Site KCP).

### Catatan Penting

- **Equipment Population**: field ini dibutuhkan oleh formula asli namun
  tidak ada pada daftar input awal yang diminta. Ditambahkan sebagai field
  opsional "Jumlah Unit" (default = 1, artinya perhitungan per satu unit
  equipment). Formula bersifat linear terhadap populasi, sehingga hasil
  untuk populasi > 1 tetap identik dengan skala Excel.
- **Jenis Unit**: pada sheet BACKEND, kolom "Attribute" (Big/Medium/Small/-)
  berelasi 1:1 dengan Sub Category, sehingga dropdown ini pada praktiknya
  menampilkan satu opsi konfirmasi ukuran unit sesuai data BACKEND (bukan
  input yang mengubah rumus, karena Attribute memang tidak dipakai dalam
  rumus Final Calculation).
- Ditemukan inkonsistensi penamaan kolom internal pada sheet asli (kolom
  berlabel "Welder" di tengah tabel sebenarnya menghitung data Electrician,
  dan sebaliknya). Tabel akhir "Summary Manpower/Cost" pada sheet tetap
  benar secara semantik, dan itulah yang direplikasi di aplikasi ini.
