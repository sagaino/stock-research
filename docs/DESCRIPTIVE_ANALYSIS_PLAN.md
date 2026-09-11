# Rencana eksekusi: analisis deskriptif rekaman per saham

Status: rencana, belum diimplementasikan. Dibuat 7 September 2026.

## 1. Tujuan dan batas pekerjaan

Bangun `stockbit-analyze` untuk membaca satu sesi PostgreSQL dan menghasilkan
analisis satu saham dalam interval 1, 5, dan 30 detik. Hasilnya menjadi dasar
penyusunan hipotesis riset, bukan sinyal trading atau estimasi probabilitas profit.

Gunakan sesi dedicated untuk analisis transaksi dan order book. Wildcard boleh
dianalisis setelah difilter ke satu symbol, tetapi hanya menghasilkan metrik
transaksi. Jangan gabungkan kedua sumber untuk menambal transaksi yang hilang.

Tidak termasuk: Redis, perubahan recorder/protokol WS, koneksi live, migrasi DB,
API/dashboard baru, machine learning, backtest eksekusi, dan auto buy/sell.
Tidak perlu dependency baru. Gunakan stdlib dan pola proyek yang sudah ada.

## 2. Instruksi awal untuk model pelaksana

1. Baca AGENTS.md yang berlaku dan instruksi skill coding yang tersedia.
2. Bila graph tersedia, mulai dari `graphify query` untuk alur recording/replay/report.
3. Baca kode yang benar-benar akan digunakan:
   `stockbit_ws/postgres.py`, `recording.py`, `events.py`, `orderbook.py`,
   `report.py`, `tests/test_postgres.py`, `tests/test_report.py`, `pyproject.toml`,
   serta `docs/REPORT.md`.
4. Verifikasi kontrak reader dan payload; bila berbeda dari dokumen ini, ikuti
   kode aktual dan catat penyesuaiannya. Jangan menebak nama field.
5. Jalankan baseline test dan catat pass/fail/skip aktual sebelum mengubah kode.
6. Jangan membaca atau mencetak token `.env`; jangan mengubah data LIVE maupun
   laporan lama. Pertahankan perubahan pengguna/model lain.

## 3. Bentuk implementasi minimum

- Tambahkan `stockbit_ws/analysis.py`: fungsi analisis yang dapat diuji memakai
  iterable event, pembentukan output, dan CLI tipis.
- Tambahkan `tests/test_analysis.py`, mengikuti unittest yang sudah digunakan.
- Tambahkan entry point `stockbit-analyze` di `pyproject.toml`.
- Tambahkan panduan singkat di README; kontrak teknis boleh tetap di dokumen ini.
- Gunakan `PostgresReader` untuk validasi sesi, payload, serta pembacaan berurutan
  dan berpaginasi. Tutup koneksi dalam `finally`/context manager yang sesuai.
- Jangan memakai cache LRU feed untuk deduplikasi analisis seluruh sesi.
- Jangan menyalin asumsi velocity berbasis penerimaan atau spread berbobot update
  dari laporan lama ke metrik baru tanpa penamaan yang jelas.

CLI yang dituju:

```bash
uv run stockbit-analyze SESSION_ID
uv run stockbit-analyze WILDCARD_ID --symbol BUMI
uv run stockbit-analyze SESSION_ID --intervals 1 5 30 --warmup-seconds 60
uv run stockbit-analyze SESSION_ID --output-dir reports/analysis-contoh
```

Default interval: 1, 5, 30 detik. Default warmup: 0, bukan 60 detik.
Batasi interval MVP pada tiga nilai tersebut; hapus duplikasi dan urutkan.
Dedicated menggunakan symbol sesi; `--symbol` yang berbeda ditolak. Wildcard
wajib memiliki `--symbol` valid. Sesi wajib memiliki akhir dan berstatus
STOPPED atau COMPLETED. Tolak sesi OPEN/ERROR untuk MVP dengan pesan jelas.
Warmup wajib finite, nonnegatif, dan lebih pendek daripada durasi sesi.

## 4. Kontrak waktu dan seleksi data

### Waktu transaksi

- Timestamp transaksi disebut `trade_event_time`; jangan menyatakan jam tersebut
  sudah terbukti tersinkron dengan jam bursa.
- `received_at` adalah waktu lokal penerimaan event. Simpan perbedaan kedua basis
  ini dalam metadata; selisih negatif bukan latensi jaringan negatif.
- Bucket UTC tetap, berjangkar epoch: `[start, end)`. Hitung batas dengan integer
  waktu, bukan pembagian float yang dapat salah di tepi bucket.
- Rentang analisis adalah `[session.started_at + warmup, session.ended_at)`.
  Hanya transaksi dengan waktu transaksi DAN waktu penerimaan dalam rentang itu
  yang masuk agregat. Laporkan jumlah yang dikecualikan.
- Batas sesi menggunakan jam lokal yang belum dikoreksi offset; selalu beri
  peringatan bahwa transaksi dekat batas dapat terpengaruh perbedaan jam.
- Urutan OHLC: `(trade_event_time, seq, index_transaksi_dalam_batch)`.
  Selesaikan pengurutan secara offline; jangan menganggap urutan datang selalu
  sama dengan urutan waktu transaksi.

### Deduplikasi dan rekonsiliasi

Filter symbol dahulu. Untuk seluruh sesi terpilih, identitas utama adalah
`(symbol, tradeId)`; jangan membatasi jumlah identitas ke ukuran cache dashboard.
Tanpa ID, gunakan fallback proyek `(symbol, timestamp, price, shares, sideCode)`
dan tandai hasil sebagai deduplikasi perkiraan.

Deduplikasi dilakukan SEBELUM filter waktu/warmup, dengan salinan pertama menurut
`seq` dan posisi batch. Ini mencegah salinan snapshot yang muncul ulang dianggap
transaksi baru sesudah warmup.

Jika ID sama memiliki perbedaan timestamp, price, shares, atau sideCode, hentikan
analisis dengan error konflik. Jangan memilih salah satunya diam-diam. Perubahan
field tambahan boleh dicatat tanpa mengubah salinan pertama.

Untuk transaksi canonical, gunakan alasan eksklusi berurutan agar tidak double count:

1. Waktu transaksi sebelum awal sesi: `historical_before_session`.
2. Waktu transaksi pada/setelah akhir sesi: `event_time_after_session`.
3. Waktu penerimaan di luar batas sesi: `received_outside_session`.
4. Waktu transaksi atau penerimaan sebelum akhir warmup: `warmup_excluded`.
5. Sisanya: `included`.

Output harus memenuhi `raw_selected = duplicate_copies + canonical_count` dan
`canonical_count = included + sum(exclusion_counts)`.
Jumlah tanpa ID merupakan penanda terpisah, bukan alasan eksklusi.

`batchKind` yang tidak diketahui tidak membuktikan snapshot/live. Default warmup
0 mempertahankan data yang lolos aturan waktu, tetapi keluarkan peringatan bahwa
snapshot dalam rentang sesi belum dapat dipisahkan. Warmup hanya heuristik yang
bisa dikonfigurasi, bukan jaminan telah menghapus seluruh snapshot.

## 5. Metrik transaksi setiap interval

Keluarkan semua bucket yang beririsan rentang analisis, termasuk bucket kosong.
Simpan `observed_seconds` dan `partial_window` untuk bucket pertama/terakhir.
Rate menggunakan durasi irisan, bukan selalu panjang interval nominal.

| Field | Definisi |
| --- | --- |
| trade_count | Jumlah transaksi canonical yang masuk bucket |
| shares, lot | Total shares; lot = shares / 100 |
| value | Jumlah price × shares |
| buy_value, sell_value | Nilai menurut sideCode yang sudah dinormalisasi |
| net_aggression_value | buy_value − sell_value |
| buy_value_ratio | buy_value / value; null jika value nol |
| trades_per_second | trade_count / observed_seconds |
| lots_per_second | lot / observed_seconds |
| open, high, low, close | Harga dari urutan waktu transaksi yang ditentukan |
| vwap | value / shares; null jika shares nol |
| return_bps | (close / open − 1) × 10000; null jika tidak terdefinisi |

Bucket kosong: count/volume/value/rate nol, OHLC/VWAP/return/ratio null.
Transaksi tunggal: OHLC sama, return nol. Jangan carry-forward harga dan
menyajikannya sebagai transaksi baru.

Gunakan shares integer dan Decimal dari string untuk perhitungan uang/harga.
Dalam JSON, decimal sebagai string, count sebagai integer, missing sebagai null;
jangan mengeluarkan NaN/Infinity. Dokumentasikan pembulatan, misalnya maksimal
8 angka desimal dengan ROUND_HALF_EVEN hanya saat serialisasi rasio/rate.

HAKA/HAKI mengikuti pemetaan decoder saat ini, bukan identitas investor. Net
aggression bukan arus uang bersih pasar dan bukan bukti akumulasi/distribusi.

## 6. Order book: snapshot akhir bucket, basis penerimaan

MVP tidak menghitung spread rata-rata berbobot waktu atau mendeteksi spoofing.
Keluarkan bagian `book_receive_time_windows` TERPISAH dari transaksi event-time.
Tidak ada penggabungan keduanya yang diklaim sebagai keadaan kausal saat trade.

Untuk tiap bucket, ambil state setelah semua event dengan `received_at < end`
diproses menurut seq. Pada bucket terakhir gunakan akhir rentang analisis.
Proses event sebelum warmup untuk membangun state, tetapi jangan memakai event
dari masa depan. Timestamp tepat di batas menjadi bagian bucket berikutnya.

State valid hanya bila koneksi diketahui connected, kedua sisi tersedia dan
tidak kosong, serta usia masing-masing sisi pada batas pengamatan tidak melebihi
`session.stale_after`. Disconnect menginvalidasi kedua sisi; setelah reconnect
tunggu update baru masing-masing sisi. Gunakan perilaku replacement/update
book sesuai kontrak decoder aktual, bukan asumsi akumulasi level.

Jika `received_at` mundur dalam urutan seq, nonaktifkan metrik book untuk sesi
tersebut dengan alasan `non_monotonic_received_at`; metrik transaksi tetap dapat
dihasilkan. Jangan diam-diam mengurutkan ulang event untuk memperbaiki jam lokal.

Field: best_bid, best_offer, spread_points, spread_bps terhadap midpoint,
bid_shares_top1, offer_shares_top1, imbalance_top1 = (bid−offer)/(bid+offer),
bid_age_ms, offer_age_ms, valid, invalid_reason, locked, crossed.
Urutkan bid descending dan offer ascending sebelum memilih level terbaik.
Locked adalah spread nol; crossed adalah spread negatif. Crossed ditandai
invalid dan spread/imbalance analitis null; harga mentah boleh tetap ditampilkan.
Untuk stale/missing/disconnected, metrik analitis null dengan alasan eksplisit.
Usia sisi dinilai hanya dari update sisi, bukan dari pesan WS lain.

Wildcard: bagian book tidak tersedia, berikan alasan `trades_only_feed`; jangan
menghasilkan angka nol yang terlihat seperti book valid. Ringkasan coverage hanya
proporsi snapshot akhir bucket yang valid, BUKAN proporsi durasi valid.

## 7. Output

Hasil per invocation: `analysis.json` lengkap dan `summary.md` ringkas di folder
baru. Default boleh `reports/analysis_<session_id>_<symbol>`; tolak target file
yang sudah ada dan minta output-dir berbeda. Jangan menimpa laporan sebelumnya.
Hitung/validasi hasil sebelum menulis; gunakan penulisan atomik per file.

JSON memuat schema_version, session_id, symbol, source LIVE/SYNTHETIC, status,
batas sesi/analisis, max_seq yang terbaca, parameter, basis waktu, rekonsiliasi,
warning kualitas, serta seluruh baris per interval. Jangan memasukkan jam saat
eksekusi dalam payload deterministik. Sesi identik dan parameter identik harus
menghasilkan payload identik.

Markdown memuat total, eksklusi, warning, dan preview maksimal 20 bucket tiap
interval. Nyatakan bahwa JSON tidak dipotong. Tidak perlu CSV, chart, atau UI.

Jangan mengeluarkan verdict “100% lengkap”, “server pasti drop”, “storage aman”,
atau “probabilitas profit tinggi”. Selisih wildcard/dedicated yang diketahui
merupakan observasi kecocokan dua rekaman, bukan bukti sumber kehilangan data.

## 8. Urutan implementasi dan pengujian

### Tahap A — agregasi transaksi murni

Implementasikan validasi parameter, dedup, eksklusi, bucketing, dan metrik.
Uji dengan event sintetis tanpa DB. Fixture minimum dalam satu detik:
price 100/shares 1000/BUY dan price 102/shares 2000/SELL menghasilkan 30 lot,
value 304000, buy 100000, sell 204000, net −104000, VWAP 101.33333333,
open 100, close 102, return 200 bps, count 2.

Sertakan kasus batas detik, tie timestamp, arrival tidak berurutan, bucket kosong
dan parsial, ID sama beda symbol, duplikat identik, konflik ID, tanpa ID,
historical awal sesi, warmup, dan duplikat snapshot muncul ulang sesudah warmup.
Verifikasi total tiap interval sama dengan total transaksi included.

### Tahap B — snapshot order book

Uji update satu sisi, level tidak terurut, sisi kosong, batas stale, disconnect/
reconnect, locked, crossed, jam penerimaan mundur, wildcard tanpa book, dan
event tepat di batas bucket. Pastikan tidak memakai update masa depan.

### Tahap C — CLI dan output

Hubungkan reader readonly, tambahkan script, JSON/Markdown, serta dokumentasi.
Uji invalid symbol/session/interval/warmup, target output sudah ada, determinisme
dua kali, dan pesan kegagalan tanpa bocoran connection string/token.
Gunakan test integration PostgreSQL yang sudah ada dengan sesi SYNTHETIC milik
tes; cleanup hanya ID yang dibuat tes itu sendiri. Jangan truncate tabel.

Jalankan suite sesuai baseline proyek, misalnya:

```bash
uv run python -m unittest discover -s tests
STOCKBIT_TEST_POSTGRES=1 uv run python -m unittest discover -s tests
npm test
```

Verifikasi script npm aktual sebelum menjalankannya. Laporkan skip secara jujur;
tes yang dilewati bukan pass. Setelah perubahan kode, perbarui graph sesuai
AGENTS.md. Jangan memperbarui dependency hanya karena ada warning versi.

### Tahap D — uji rekaman yang sudah ada

Verifikasi ID berikut masih ada sebelum dipakai, kemudian analisis readonly:

| Sesi | ID |
| --- | --- |
| BUMI | f8cf7cf9ff794499bb9cda8f8d646b03 |
| PTRO | 2b7935ca680047818e52085e2893bc7b |
| IMPC | b50e20c2d68047d39b184e7c259a3cbc |
| Wildcard | eaf9a059184f4b0192aa4be7a2908209 |

Analisis dedicated BUMI/PTRO/IMPC, lalu wildcard dengan filter BUMI dan PTRO,
masing-masing terpisah. Jalankan ulang satu kasus dengan parameter sama dan
bandingkan payload penuh. Jalankan warmup 60 sebagai sensitivity check terpisah,
bukan penggantian hasil default.

Jumlah included tidak wajib sama dengan angka laporan lama karena ada eksklusi
waktu/dedup yang eksplisit. Rekonsiliasikan selisih; jangan memaksa angka cocok.
Catat durasi analisis dan keterbatasan memori. Deduplikasi exact memerlukan memori
sebanding jumlah identitas terpilih; jangan memakai LRU yang mengubah hasil.
Optimasi baru dibutuhkan jika pengukuran menunjukkan masalah pada rekaman nyata.

## 9. Kriteria selesai dan handoff

- CLI berjalan untuk dedicated dan filter wildcard dengan tiga interval.
- Definisi waktu, snapshot, dedup, stale, dan missing tercermin di output serta tes.
- Seluruh count dapat direkonsiliasi; interval tidak mengubah total included.
- Hasil deterministik; tidak ada regresi suite yang sebelumnya lulus.
- Data sesi/event LIVE, recorder, dan laporan lama tidak diubah.
- Tidak ada dependency/infrastruktur baru atau koneksi Stockbit saat analisis.
- Serahkan daftar file berubah, perintah penggunaan, hasil test termasuk skip,
  lokasi laporan nyata, dan keterbatasan yang masih tersisa.

Sesudah tahap ini selesai, langkah berikutnya adalah mendefinisikan kandidat
hipotesis sinyal dan menguji pada hari/saham berbeda, dengan biaya transaksi,
spread, slippage, serta pemisahan data pengembangan dan evaluasi. Itu pekerjaan
terpisah; jangan mengimplementasikannya dalam tugas ini.

## Prompt untuk model pelaksana

> Baca docs/DESCRIPTIVE_ANALYSIS_PLAN.md dan implementasikan tahap A sampai D
> sesuai kontrak serta kriteria selesai. Periksa kode aktual terlebih dahulu dan
> gunakan helper yang sudah ada. Jangan mengubah data LIVE, membuka koneksi
> Stockbit, menambah Redis, atau membuat sinyal/auto-order. Jalankan tes, buat
> laporan analisis readonly dari rekaman yang tersedia, lalu laporkan hasil dan
> keterbatasannya. Bila ada ketidaksesuaian kontrak penting yang tidak dapat
> diselesaikan dalam scope, jelaskan sebelum memperluas pekerjaan.
