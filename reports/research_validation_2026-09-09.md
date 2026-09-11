# Validasi Paper Strategy — 7–9 September 2026

## Kesimpulan

Konfigurasi saat ini **belum menghasilkan edge yang profitable**. Setelah koreksi urutan waktu, tick IDX, batas risiko, fee broker, slippage adverse satu tick per sisi, dan entry wajib menembus harga referensi, kandidat yang dibekukan menghasilkan sekitar **-Rp28.271**: data pengembangan **-Rp11.048** dan data validasi **-Rp17.222**.

Angka ini adalah simulasi paper, bukan saldo akun. Antrean, partial fill, market impact, reject, dan latency broker belum dimodelkan.

## Verifikasi implementasi

- `STOCKBIT_TEST_POSTGRES=1 uv run python -m unittest discover -s tests -q`: **192 tes lulus**.
- `uv run python -m compileall -q stockbit_ws tests`: **lulus**.
- Replay nyata sesi `5937d21294ad41eba876bd2a15b9c3fd` dengan `--sniper --min-delta-pct 1.0`: **114.009 event selesai, exit 0**.
- `graphify update .`: graph kode berhasil diperbarui setelah perubahan terakhir.
- Tes Node/npm tidak dijalankan karena project ini sekarang pure Python dan tidak memiliki `package.json`.

## Metode

- Data pengembangan: dua sesi wildcard tanggal 7 September 2026.
- Parameter `minimum delta %` diuji hanya pada data pengembangan: 0,75%; 1,0%; 1,5%; dan 2,0%.
- Kandidat 1,0% dipilih sebagai konfigurasi aktif yang masih menghasilkan transaksi, lalu dibekukan.
- Entry pada harga referensi yang sama ditolak; harga harus benar-benar menembus referensi.
- Data validasi: empat sesi wildcard tanggal 8–9 September 2026; parameter tidak diubah setelah hasil validasi terlihat.
- Modal per posisi Rp550.000; fee beli 0,15%; fee jual 0,25%; slippage adverse satu tick per sisi.
- Target 3%; stop 1,5%; minimum harga Rp200; minimum 50 transaksi/5 detik; observasi minimum 4 detik, 15 transaksi, Rp25 juta HAKA, dan 100 lot HAKA.

## Hasil konfigurasi beku (`minimum delta = 1,0%`)

| Kelompok | Sesi | Alert | Posisi | Net positif | Net paper |
|---|---|---:|---:|---:|---:|
| Pengembangan | 2026-09-07 pagi | 2 | 0 | 0 | Rp0 |
| Pengembangan | 2026-09-07 sore | 7 | 2 | 1 | -Rp11.048 |
| Validasi | 2026-09-08 pagi | 7 | 0 | 0 | Rp0 |
| Validasi | 2026-09-08 tengah | 6 | 1 | 0 | -Rp17.222 |
| Validasi | 2026-09-08 sore | 9 | 0 | 0 | Rp0 |
| Validasi | 2026-09-09 pagi | 7 | 0 | 0 | Rp0 |
| **Total** | **6 sesi** | **38** | **3** | **1** | **-Rp28.271** |

## Pembanding konfigurasi default (`minimum delta = 0,75%`)

Konfigurasi default menghasilkan 8 posisi pada enam sesi, hanya satu yang net positif, dengan total sekitar **-Rp87.688**. Filter persentase 1,0% mengurangi overtrading dan kerugian, tetapi belum mengubah strategi menjadi profitable.

## Keputusan riset

Hipotesis entry retest/pullback dan reclaim juga diuji sebagai pembanding sederhana; seluruh kombinasi yang diuji tetap negatif pada data pengembangan dan validasi. Pola Squeeze menghasilkan sekitar -Rp42.240 / -Rp12.175, sedangkan pola Absorption sekitar -Rp153.370 / -Rp236.921 (pengembangan / validasi). Karena itu, mengganti nama pola atau timing entry sederhana belum cukup.

Jangan gunakan strategi ini untuk order riil. Tahap berikutnya adalah merekam fitur pra-entry secara eksplisit—terutama keberlanjutan HAKA/HAKI setelah alert, posisi harga terhadap high window, dan L2 yang segar—lalu menguji satu aturan tambahan pada hari rekaman baru tanpa menyesuaikan parameter terhadap hasil validasi ini.
