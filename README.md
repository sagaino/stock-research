# Stockbit WebSocket CLI — Pure Python

Client lokal **read-only** untuk Order Book (BID/OFFER) dan Recent Done. Project ini murni berbasis Python, dilengkapi radar riset pasar dan simulasi paper sniper; tidak pernah mengirim order jual/beli ke broker.

Protocol mengikuti capture session Anda, bukan API resmi Stockbit. Gunakan hanya data/session yang memang boleh Anda akses. Client tidak mengambil credential browser, memperbarui session, atau melewati authentication.

## Jalankan Python

Persyaratan: Python 3.11+ dan `uv`. Keduanya sudah tersedia pada laptop tempat migrasi ini dikerjakan.

Dari folder project:

```bash
uv sync --locked
uv run python index.py BMRI --check
uv run python index.py BMRI
```

`--check` hanya memvalidasi tiga frame dan penggantian symbol secara offline; bukan pemeriksaan masa berlaku session. Default symbol adalah `COCO`. Contoh lain:

```bash
uv run python index.py COCO
uv run python index.py BBRI --duration 30 --debug
```

`--duration` menutup koneksi setelah batas detik, termasuk waktu connecting. Tanpa opsi tersebut, hentikan dengan Ctrl+C. Alternatif setelah `uv sync`: `.venv/bin/python index.py BMRI`, `uv run stockbit-ws BMRI`, atau `uv run python -m stockbit_ws BMRI`.

Tidak menggunakan `uv`? Buat virtual environment kemudian instal project:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
.venv/bin/python index.py BMRI
```

Instalasi `pip` mengikuti rentang dependency; `uv sync --locked` memakai versi terkunci untuk hasil yang dapat diulang.

## Konfigurasi

**Gunakan `.env` yang sudah ada; tidak perlu mengisinya ulang atau menimpanya untuk migrasi.** Pada instalasi baru saja, buat `.env` mengikuti `.env.example` dan isi tiga frame Base64 hasil capture session Anda sendiri. Jika session sudah kedaluwarsa, capture baru tetap diperlukan:

```dotenv
STOCKBIT_FRAME_1=<base64 frame 1>
STOCKBIT_FRAME_2=<base64 frame 2>
STOCKBIT_FRAME_3=<base64 frame 3>
DEBUG_WS=false
```

Variabel lingkungan proses memiliki prioritas di atas `.env`. Python membaca file di folder aktif, tanpa ekspansi `${...}`. Gunakan `--env-file /path/to/.env` bila lokasinya berbeda.

`.env` diabaikan Git. Jangan menempelkan frame, JWT, atau session key ke source, log, maupun percakapan. Mode `--debug` hanya menampilkan ukuran/jenis pesan dan metadata decoder; isi frame keluar serta teks/error mentah server tidak dicetak.

## Tampilan dan batas data

- **Order Book:** BID dan OFFER disimpan terpisah; update satu sisi mempertahankan sisi lain. `lot = shares / 100`.
- **Recent Done:** timestamp, harga, lot, side, perubahan, nilai transaksi, dan trade ID. Tampil maksimal **20** baris, dengan maksimal **100** record terbaru di memori.
- Angka 20 adalah batas tampilan, **bukan batas record per pesan WebSocket**. Semua record valid dalam batch diproses sebelum deduplikasi dan pembatasan memori.
- `HAKA/BUY` dan `HAKI/SELL` adalah interpretasi side berdasarkan capture, bukan nama field resmi Stockbit.
- Waktu tampil dalam WIB. `Updated` adalah waktu penerimaan update order book oleh client; bukan waktu eksekusi transaksi. Timestamp Done berasal dari record.
- Snapshot lama dapat muncul saat terhubung. Menerima snapshot belum membuktikan seluruh transaksi baru dikirim tanpa jeda atau kehilangan.

State dashboard tetap di memori dan direset ketika memulai proses/sesi baru. Penyimpanan permanen **opsional** kini tersedia melalui `--record` (lihat bagian berikut). Belum ada histori pasar lengkap, backfill, refresh token, atau jaminan kelengkapan feed. Sidecar L2 mencoba reconnect saat koneksi terputus; koneksi feed utama belum memiliki retry loop. Mode Running Trade semua saham tersedia secara eksperimental lewat `--all`.

## Rekam, cek kualitas, dan replay

### Running Trade semua saham (eksperimental)

```bash
docker compose up -d --wait
uv run python index.py --all --check
uv run python index.py --all --record
```

`--all` memakai tiga frame dari `.env` yang sama, mempertahankan byte autentikasi,
mengosongkan command subscription pada frame awal, lalu mengganti command pada
frame terakhir menjadi Protobuf `field 2 → field 5 = "*"` (`12 03 2A 01 2A`).
Struktur command mengikuti temuan chat **WebSocket Binary Terenkripsi**;
urutan initialization dan penerimaan feed/format decoder masih perlu validasi
live. `--check` hanya memvalidasi pembentukan frame, bukan penerimaan server
atau masa berlaku token. Tidak mengubah `.env` dan tidak meminta wildcard Order Book.

Tampilan: **Time, Code, Price, Lot, Side, Change, Value, Trade ID**. Maksimal
20 baris ditampilkan, 100 transaksi terbaru disimpan di state; seluruh batch
Done yang berhasil didecode/valid tetap direkam, termasuk duplikat. Deduplikasi
memakai gabungan symbol dan trade ID, bukan trade ID saja. Pesan binary yang
tidak dikenali tidak menjadi transaksi; metadata pesan saja disimpan.

Sesi database menggunakan `symbol = '*'`, sedangkan setiap transaksi di
`events.payload.trades` menyimpan kode saham sebenarnya. Tidak memerlukan
penghapusan/migrasi tabel; sesi per-saham lama tetap dapat direplay. Gunakan
versi client ini untuk membaca sesi wildcard (client lama belum mendukungnya).

```bash
uv run python index.py --replay --sessions
uv run python index.py --replay --session SESSION_ID --speed 1
```

Replay otomatis memilih tampilan semua saham bila sesi bertanda `*`.
`--all --replay --session SESSION_ID` juga bisa digunakan untuk memastikan sesi
yang dipilih memang wildcard. `--all` tidak dapat digabung dengan positional
symbol. Mode per-saham `BMRI --record` tetap seperti sebelumnya.

**Batasan:** health wildcard adalah kesehatan feed gabungan, bukan kesegaran
setiap saham; `RECENT_OBSERVED` tidak membuktikan semua saham/transaksi sudah
diterima. Hitungan `lateDoneWindow` membandingkan timestamp lintas batch feed,
bukan urutan transaksi masing-masing saham. Tidak ada deteksi kelengkapan bursa,
reconnect, backfill, atau filter replay per-saham dalam sesi wildcard.
Penulisan masih sinkron per-event; belum ada jaminan kapasitas untuk seluruh
pasar saat ramai. Tes sintetis multi-saham memverifikasi state/record/replay,
bukan throughput puncak atau penerimaan server. Hentikan dengan Ctrl+C.

### Mode per saham

PostgreSQL Docker kini menjadi satu-satunya backend recording/replay, mengikuti contoh project Go. Container dan volume dipisah dari project Go. Jalankan `docker compose up -d --wait` untuk database + pgAdmin, lalu buka [pgAdmin lokal](http://127.0.0.1:5051) untuk preview. Login dan langkah membuka tabel tersedia di [panduan PostgreSQL/pgAdmin](docs/POSTGRES.md).

Untuk tes sesi aktif Senin, mulai satu symbol dengan rekaman 30 menit:

```bash
docker compose up -d --wait postgres
uv run python index.py BMRI --record postgres --duration 1800
```

`--record` tanpa nilai memilih PostgreSQL; tanpa flag itu client tidak merekam. Target file tidak lagi didukung. Setiap run menambahkan sesi baru, tidak menimpa sesi sebelumnya. Rekaman menyimpan event pasar yang sudah didecode, timestamp penerimaan, urutan monotonic, metadata ukuran/jenis pesan, serta perubahan status koneksi. Frame login, raw binary, body teks server, `.env`, dan field unknown tidak disimpan. Event Done duplikat tetap ada dalam rekaman; deduplikasi dilakukan pada state tampilan/analisis.

Bagian `FEED` menampilkan status, umur BID/OFFER terpisah, umur timestamp Done, serta hitungan duplikasi. Pemeriksaan berjalan juga saat tidak ada pesan masuk. Default ambang umur data adalah 15 detik; ubah dengan `--stale-after 30` bila sesuai kebutuhan tes. Data lama atau pasar tenang dapat memicu `STALE`; status itu **bukan bukti kehilangan data**. `RECENT_OBSERVED` juga bukan jaminan kelengkapan atau sinyal transaksi.

Setelah rekaman selesai:

```bash
uv run python index.py --replay postgres --sessions
uv run python index.py --replay postgres
uv run python index.py --replay postgres --speed 10
```

Default replay memilih sesi terakhir dan langsung menampilkan hasil akhir (`--speed 0`). `--speed 1` mengikuti jeda rekaman; `--speed 10` mempercepat 10x. Pilih sesi lain dengan `--session SESSION_ID` dari daftar. Replay memakai symbol, ambang kualitas, dan waktu historis sesi tersebut; tidak membaca `.env` Stockbit atau membuka WebSocket. Replay PostgreSQL hanya membuka koneksi database dan membaca `.env.postgres` bila tersedia. Replay menguji **state setelah decoding**, bukan mengulang decoder binary.

Demo yang bisa dicoba tanpa sesi Stockbit:

```bash
uv run python tools/demo_recording.py
uv run python index.py --replay postgres --speed 10
```

Demo ditandai `SYNTHETIC`, bukan data live. Petunjuk lengkap, arti status, dan checklist pembandingan Senin tersedia di [panduan tes live](docs/LIVE_TEST.md).

### REST API Sesi dan Event

Tersedia REST API read-only untuk mengakses daftar sesi rekaman, ringkasan metrik, dan event pasar tanpa mengganggu proses recording yang sedang berjalan:

```bash
uv run stockbit-api
# atau dengan opsi port/host:
uv run stockbit-api --host 127.0.0.1 --port 8000
```

Dokumentasi interaktif Swagger UI tersedia di [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

Endpoint yang tersedia:
- `GET /api/sessions`: Daftar sesi terurut terbaru dengan total event (filter: `?symbol=BUMI`, `?status=OPEN`, `?source=LIVE`, `?limit=50`).
- `GET /api/sessions/{session_id}`: Detail sesi, breakdown jenis event (`message`, `book`, `done`, `connection`), serta timestamp data awal dan akhir.
- `GET /api/sessions/{session_id}/events`: Stream event terpaginasi (filter: `?seq_gt=0`, `?limit=100`, `?kind=done`).
- `GET /api/sessions/{session_id}/report`: Laporan kualitas rekaman (dedup, throughput, komparasi wildcard) dalam JSON & Markdown.
- `GET /api/sessions/{session_id}/intervals`: Bar interval teragregasi (1s, 5s, 30s) dengan metrik OHLC, volume, nilai, HAKA/HAKI net flow, velocity, dan order book imbalance. Parameter `symbol` wajib untuk sesi wildcard agar saham tidak tercampur.
- `GET /api/sessions/{session_id}/radar`: Hasil pemindaian anomali pasar (Breakout Momentum, Squeeze Blitz, Heavy Absorption) dalam JSON & Markdown.
- `GET /health`: Pemeriksaan kesehatan koneksi database (read-only mode).

### Laporan Kualitas Rekaman, Interval, & Radar Anomali Pasar

Tersedia CLI terstandar untuk audit rekaman, analisis interval, dan radar pemindai anomali pasar:

```bash
# 1. Audit kualitas rekaman (uniqueness, throughput, latensi, gap komparasi)
uv run stockbit-report SESSION_ID
uv run stockbit-report --compare DEDICATED_SESSION_ID WILDCARD_SESSION_ID SYMBOL

# 2. Analisis pola aktivitas per interval (1s, 5s, 30s)
uv run stockbit-intervals SESSION_ID --all-intervals
uv run stockbit-intervals SESSION_ID --output reports/intervals_SESSION.md

# 3. Market Radar pemindai anomali pasar (Breakout Momentum, Squeeze Blitz, Absorption)
# Mode Replay historis dari database:
uv run stockbit-radar SESSION_ID
uv run stockbit-radar SESSION_ID --output reports/radar_SESSION.md

# Mode Live Streaming (berjalan bersamaan dengan perekaman wildcard):
uv run python index.py --all --radar
uv run python index.py --all --record --radar

# 4. Scout & Sniper Architecture (Radar + Pemantauan Taktis 5 Slot):
# Mode Live Streaming dengan Sniper 5 slot terintegrasi:
uv run python index.py --all --record --sniper
# Kandidat paper yang sudah diuji (Breakout delta minimal 1%):
uv run python index.py --all --record --sniper --min-delta-pct 1.0
# Mode order book penuh: Watchlist Pullback L2 (maks. 5), SL support, TP resistance/refill
uv run python index.py --all --record --sniper --orderbook-exit-mode full

# Mode Replay Visual Dashboard bersama Radar & Sniper 5 Slot:
uv run python index.py --replay --session SESSION_ID --speed 5 --sniper
# Replay dengan ambang Radar yang sama seperti kandidat paper:
uv run python index.py --replay --session SESSION_ID --speed 5 --sniper --min-delta-pct 1.0

# Laporan paper backtest konservatif (fee + 1 tick slippage adverse per sisi):
uv run stockbit-sniper SESSION_ID --orderbook --orderbook-exit-mode full --paper-slippage-ticks 1 --output reports/paper_SESSION.md
```

Mode `--orderbook-exit-mode full` otomatis membaca event L2 (flag `--orderbook`
tetap boleh ditulis) dan menjadikan alert `BREAKOUT_MOMENTUM` sebagai Watchlist
L2 maksimal lima slot, bukan entry langsung. Kandidat bertahan selama ada DONE;
yang sepi lima menit atau bid support-nya jebol dilepas agar slot Sidecar tersedia.
Entry paper hanya terjadi saat bid support kuat diserap lalu refill dua kali, diikuti
dua HAKA berurutan dalam lima detik pada harga maksimal satu tick di atas support.
Support menjadi acuan CL; resistance offer yang direfill dua siklus dipakai untuk TP.
Resistance yang jebol dan berubah menjadi bid menjadi support baru. L2 stale memblokir
entry dan koneksi terputus setelah posisi masuk menjalankan emergency exit. Mode ini
tetap paper-only dan belum memodelkan antrean, partial fill, market impact, reject,
serta latency broker.

Return dari `stockbit-sniper` adalah estimasi paper. Ia belum memodelkan antrean, partial fill, market impact, reject, dan latency broker, sehingga tidak boleh dibaca sebagai saldo atau profit riil.

## Koneksi dan pergantian symbol

Python mempertahankan endpoint `wss://wss-trading.stockbit.com/ws`, Origin `https://stockbit.com`, subprotocol `web`, serta urutan tiga frame sekitar 0/180/400 ms setelah terhubung. Batas incoming message 10 MiB. PONG protokol ditangani library; tidak ada heartbeat aplikasi baru atau retry loop.

Transformer memvalidasi nested subscription field 2/6/7/9 dan optional 5 sebelum mengganti symbol. Authentication serta field yang tidak diubah dipertahankan byte-for-byte. Capture ambigu atau format baru ditolak sebelum pengiriman; tidak menebak protocol.

TLS tetap memverifikasi sertifikat dan nama host. Bundle CA `certifi` ditambahkan karena instalasi Python macOS tertentu tidak memiliki default CA. Tidak ada opsi menonaktifkan verifikasi. Dasarnya: [Python SSL context](https://docs.python.org/3/library/ssl.html#ssl.create_default_context) dan [bundle CA certifi](https://github.com/certifi/python-certifi). Koneksi memakai API [websockets asyncio client](https://websockets.readthedocs.io/en/stable/reference/asyncio/client.html) dan tidak memakai proxy otomatis.

## Inspector aman

Berikan **nama variabel**, bukan Base64 mentah:

```bash
uv run stockbit-inspect STOCKBIT_FRAME_3
uv run python tools/inspect_frame.py STOCKBIT_FRAME_3
```

Inspector Python menampilkan nomor field, wire type, ukuran, dan symbol yang dikenali. Nilai account/JWT/session serta nilai lain disamarkan. Rekursi dan jumlah field dibatasi.

## Pengujian

```bash
uv run python -m unittest discover -s tests -v
```

Test Python memakai data sintetis dan server WebSocket lokal; tidak membaca `.env` asli atau menghubungi Stockbit. Tes recording/replay memerlukan PostgreSQL dan di-skip tanpa opsi tersebut. Untuk menjalankan seluruh tes termasuk PostgreSQL nyata, jalankan `STOCKBIT_TEST_POSTGRES=1 uv run python -m unittest discover -s tests -q` setelah database Docker healthy.

## Troubleshooting

- `STOCKBIT_FRAME_* belum diisi`: periksa folder aktif/file konfigurasi dan tiga variabelnya.
- `bukan Base64 yang valid`: isi Base64 capture tanpa prefix `data:` atau spasi di tengah.
- `Struktur subscription ... ambigu`: jangan memaksa rewrite; format capture perlu ditinjau kembali.
- TLS gagal: pastikan `uv sync --locked` berhasil serta jaringan/jam perangkat benar. Jangan mematikan validasi TLS.
- HTTP ditolak atau koneksi ditutup: session dapat kedaluwarsa; `--check` tidak bisa menentukan hal ini. Client tidak mengambil session pengganti secara otomatis.
- Terhubung tetapi belum ada data: lihat metadata `--debug`. Jangan menganggap koneksi terbuka berarti authentication/subscription sudah diterima.

Urutan rollout, perbedaan yang disengaja, dan hasil verifikasi tercatat di [panduan migrasi](docs/MIGRATION.md).

---

## 🏛️ Smart Money & Bandarmologi Intelligence Suite

Suite analisis heuristik dari data broker dan running-trade Stockbit (Exodus API & Running Trade L2):

```text
┌──────────────────────────────────────────────────────────────────────────┐
│                   SUITE INTELIJEN PASAR & BANDARMOLOGI                   │
└──────────────────────────────────────────────────────────────────────────┘
  1. Ingestion Layer:
     • stockbit-exodus     : Sedot Rangkuman EOD Top Broker & Portofolio
     • stockbit-l2         : Sedot Running Trade L2 Detik-per-Detik (Heavy Duty)
  
  2. Analytics & Forensics Layer:
     • stockbit-phase3     : Forensik Rekonstruksi Intraday (Iceberg, Absorpsi, Sweep)
  
  3. Actionable Signal Generators:
     • stockbit-confluence : Mesin Sinyal BPJU / Scalping Pagi (5 Pilar Confluence)
     • stockbit-swing      : Mesin Sinyal Swing Multi-Day (Targeted L2 Sniper Funnel)
```

### 1. Ingestion Data Exodus & L2

#### A. Rangkuman Broker EOD (`stockbit-exodus`)
Menyedot ranking broker dan aktivitas saham dari broker teratas yang dikembalikan API:
```bash
uv run stockbit-exodus                    # Menarik data hari bursa terakhir
uv run stockbit-exodus --date 2026-09-11  # Menarik EOD pada tanggal tertentu
```
`--date` adalah tanggal audit tunggal: ranking top broker dan drill-down
aktivitas dikirim sebagai jendela `from=to=YYYY-MM-DD`, bukan preset periode
relatif. Jalankan ulang tanggal yang sama untuk memperbarui baris secara
idempoten; data lama yang pernah diambil dengan preset relatif perlu di-ingest
ulang sebelum dipakai untuk perbandingan historis.
Baris beli/jual API sama-sama bernilai positif; ingestion mempertahankan sisi
transaksi lalu mengagregasikannya per broker-saham sebelum menghitung net.
Pagination berjalan sampai halaman kosong, sehingga aktivitas broker tidak
dipotong pada batas 500 baris.
*Tabel Database:* `stockbit_ws.broker_top_daily`, `stockbit_ws.broker_stock_activity`, dan marker kelengkapan `stockbit_ws.broker_eod_ingestion`.

#### B. Running Trade L2 Detik-per-Detik (`stockbit-l2`)
Mesin penyedot *Heavy Duty* dilengkapi **Auto-Resume**, **Dynamic Pacing** (1–1,5 detik per halaman), **Smart Backoff** (60 detik saat 503/429), serta penanda scrape lengkap:
```bash
# Mode Targeted (hanya simbol yang dipilih; durasi bergantung jumlah tick):
uv run stockbit-l2 --symbols ANTM,AALI,PTBA --date 2026-09-11

# Mode Wildcard Seluruh Pasar (sekitar 1,9 juta tick; beberapa jam):
uv run stockbit-l2 --wildcard --date 2026-09-11
```
*Tabel Database:* `stockbit_ws.broker_l2_ticks` dan penanda kelengkapan `stockbit_ws.broker_l2_ingestion`.

---

### 2. Forensik Mikrostruktur Saham (`stockbit-phase3`)

Meringkas pola trade-print dan kronologi harga dari jam 09:00 sampai 16:15 sore:
```bash
uv run stockbit-phase3 --symbol MUTU --date 2026-09-11
uv run stockbit-phase3 --symbol VKTR --date 2026-09-11
```

**Fitur Analisis:**
- **[1] Repeated Small-Buy Heuristic:** Menandai buy kecil berulang dari broker yang sama pada harga yang sama; bukan bukti hidden order.
- **[2] Absorption Heuristic:** Menandai broker smart-money terklasifikasi yang mengambil print jual dari kode ritel terklasifikasi.
- **[3] Rapid Multi-Price Buys:** Menandai print buy broker yang sama pada 3+ harga dalam jendela cepat; bukan pembacaan antrean *offer*.
- **[4] Intraday Story Timeline:** Rekonstruksi babak demi babak (Pagi, Siang, Sore) lengkap dengan **Lot**, **Nilai Rp**, **Harga Rata-rata (Avg)**, dan **Rentang Harga [Min-Max]**.
- **[5] Derived Broker Summary:** Ringkasan net broker yang dihitung dari tick L2 yang tersimpan; bukan replika resmi yang telah diverifikasi.

Phase3 hanya membaca hari/simbol yang memiliki marker L2 lengkap (wildcard atau
targeted simbol); keberadaan sebagian tick tidak dianggap selesai.

---

### 3. Sinyal BPJU / Scalping Pagi (`stockbit-confluence`)

Kandidat **Beli Pagi Jual Untung (BPJU)** berbasis lima filter heuristik. Target di bawah adalah skenario, bukan jaminan profit:
```bash
uv run stockbit-confluence                    # Tanggal terbaru
uv run stockbit-confluence --date 2026-09-11  # Tanggal spesifik
```

**Kriteria Seleksi (5 Pilar):**
1. Pembeli utama (*Top 1 Net Buyer*) harus ada dalam daftar broker smart-money terkonfigurasi.
2. Kode ritel terkonfigurasi (`XL, YP, XC, PD, NI`) harus net sell.
3. Harga ditutup di puncak (*Close >= 95% - 100% of High of Day*).
4. Harga closing masih dekat dengan rata-rata beli broker (*Margin < +4%*).
5. Likuiditas sehat (Turnover minimal Rp 5 Miliar).

*Output:* Grade heuristik (termasuk kandidat spekulatif) lengkap dengan **Area Masuk Pagi**, **TP1 (+2.5%)**, **TP2 (+5.0%)**, **Stop Loss** yang dibulatkan ke fraksi harga IDX, dan arsip laporan di `reports/bsjp_confluence_YYYYMMDD.md`.
Scanner ini membutuhkan marker wildcard L2 lengkap pada tanggal target; data
targeted saja tidak cukup untuk menyaring seluruh pasar.
Untuk dataset lama yang Anda yakini sudah selesai tetapi belum punya marker,
gunakan override eksplisit `--trust-existing-l2`; override ini tidak membuat
marker baru dan tetap menampilkan peringatan.

---

### 4. Sinyal Swing Multi-Day (`stockbit-swing`)

Kandidat **Swing Confluence** (+7% s/d +15%) menggabungkan data akumulasi beberapa hari yang tersedia dengan mikrostruktur hari pelatuk. Dilengkapi **Targeted L2 Sniper Funnel**:
```bash
# Menjalankan screening 5 hari bursa (default):
uv run stockbit-swing

# Custom periode dan turnover:
uv run stockbit-swing --days 5 --min-val 10000000000

# Tanpa fetch jaringan; tetap membutuhkan hari L2 yang sudah ditandai lengkap:
uv run stockbit-swing --no-l2

# Offline penuh: jangan fetch EOD maupun L2:
uv run stockbit-swing --no-eod --no-l2

# Baseline EOD sebelum filter L2 (untuk evaluasi, bukan sinyal trading):
uv run stockbit-swing --date 2026-09-04 --macro-only --no-eod
```

**Alur Kerja Otomatis (Targeted L2 Sniper Funnel):**
1. Mesin memastikan marker EOD tersedia untuk maksimal `--days` tanggal bursa; tanggal yang hilang atau belum lengkap di-fetch lewat Exodus. Weekend/holiday yang tidak mengembalikan data dilewati.
2. Mesin menyaring broker smart-money net-buy minimal 4/5 hari dan kode ritel net-sell minimal 3/5 hari, dengan total ritel tetap net-sell; lalu mengambil maksimal **25 kandidat** dengan smart-net terbesar.
3. Jika belum ada penanda scrape L2 lengkap, mesin menyedot tiap kandidat secara targeted; durasi bergantung jumlah tick, bukan angka tetap 30 detik.
4. Menghasilkan *Swing Trading Plan* dengan harga yang dibulatkan ke fraksi IDX dan stop di bawah seluruh area entry.
Gunakan `--macro-only` hanya untuk membandingkan baseline EOD terhadap hasil setelah filter L2; mode ini tidak menghasilkan rencana entry atau sinyal.
*Arsip Laporan:* `reports/swing_confluence_YYYYMMDD.md`.

### 5. Backtest Walk-Forward EOD (`stockbit-swing-backtest`)

Backtest ini **tidak memakai L2**. Setiap Jumat membentuk maksimal 25 kandidat dari akumulasi broker EOD lima hari, kemudian mengukur perubahan *close*, *high*, dan *low* pada lima sesi bursa sesudahnya.

```bash
uv run stockbit-swing-backtest --from 2026-06-29 --to 2026-09-11
```

Tanggal EOD yang belum lengkap akan diambil otomatis dan snapshot harga harian disimpan di `stockbit_ws.market_daily_prices`, sehingga pengulangan berikutnya tidak perlu mengambil harga yang sama. Hasil adalah evaluasi shortlist—bukan simulasi eksekusi atau jaminan profit—karena fee, spread, slippage, likuiditas entry, dan corporate action tidak dimodelkan.
