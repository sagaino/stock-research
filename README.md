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
