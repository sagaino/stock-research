# PostgreSQL Docker

Mengikuti contoh `be-golang-app`: image resmi `postgres:16-alpine` dan named
volume. Project Go tidak diubah. Stack Stockbit memiliki container/volume
sendiri dan port **127.0.0.1:5433**, bukan port 5432 milik contoh Go.
pgAdmin tersedia untuk preview database di **127.0.0.1:5051**. Tidak menambahkan
Redis, MinIO, atau ORM; driver Python menggunakan `psycopg` langsung.
Image PostgreSQL yang dijalankan saat verifikasi melaporkan
versi 16.15.

## Mulai

```bash
uv sync --locked
docker compose up -d --wait
docker compose ps
```

Default lokal: host `127.0.0.1`, port `5433`, database `stockbit_ws`, user
`stockbit`. Password default di Compose adalah credential **development lokal**,
bukan untuk server publik. Port hanya di-bind ke localhost.

Rekam data satu symbol dengan session Stockbit aktif:

```bash
uv run python index.py BMRI --record postgres --duration 1800
```

`--record` tanpa nilai juga memilih PostgreSQL. Tanpa opsi `--record`, client
tetap hanya menampilkan data, tidak menyimpannya. Schema dibuat otomatis saat
recording/demo pertama; replay tidak membuat atau mengubah schema.

## Preview melalui pgAdmin

Jalankan `docker compose up -d --wait`, lalu buka
[pgAdmin lokal](http://127.0.0.1:5051).

Login default **development lokal**:

- Email: `admin@example.com`
- Password pgAdmin: `stockbit_admin_local`

Di sidebar, buka grup `Stockbit → Stockbit Local`. Koneksi sudah didaftarkan
otomatis. Ketika diminta password database, gunakan `stockbit_local` (atau nilai
`PG_PASSWORD` Anda), bukan password login pgAdmin.

Buka `Databases → stockbit_ws → Schemas → stockbit_ws → Tables`, kemudian klik
kanan tabel `sessions` atau `events` → **View/Edit Data → First 100 Rows**.
`events.payload` berisi data pasar JSONB. Data demo bertanda `SYNTHETIC`, bukan
transaksi live. Menu pgAdmin juga bisa mengubah data; untuk preview gunakan
SELECT atau View Data saja.

Contoh query read-only untuk Query Tool:

```sql
SELECT id, symbol, started_at, ended_at, status, source
FROM stockbit_ws.sessions ORDER BY run_no DESC LIMIT 20;

SELECT session_id, seq, received_at, kind, payload
FROM stockbit_ws.events ORDER BY received_at DESC, seq DESC LIMIT 100;
```

pgAdmin memakai host Docker `postgres` dan port internal `5432`; jangan mengisi
`127.0.0.1:5433` pada koneksi di dalam container. Jika user/database PG diubah,
sesuaikan **Properties → Connection** di pgAdmin. File definisi default
`docker/pgadmin-servers.json` hanya diimpor pada inisialisasi volume pgAdmin
pertama, sehingga perubahan koneksi yang Anda buat tidak ditimpa saat restart.

Port/login pgAdmin dapat diubah lewat `PGADMIN_PORT`, `PGADMIN_EMAIL`, dan
`PGADMIN_PASSWORD` pada `.env.postgres`, lalu gunakan Compose dengan
`--env-file .env.postgres`. Password awal hanya dipakai saat akun pertama
dibuat; untuk akun yang sudah ada, ganti password lewat UI pgAdmin.
Volume `stockbit-ws_pgadmin_data` menyimpan pengaturan pgAdmin, terpisah dari
volume rekaman PostgreSQL. Kedua port hanya di-bind ke localhost.

## Replay tanpa Stockbit

```bash
uv run python index.py --replay postgres --sessions
uv run python index.py --replay postgres
uv run python index.py --replay postgres --session SESSION_ID --speed 10
```

`--replay` tanpa nilai memilih PostgreSQL. Replay membuka koneksi **database**
read-only, bukan WebSocket Stockbit. Ia hanya memakai konfigurasi PostgreSQL;
tidak membaca file `.env` Stockbit atau memakai frame login. Sesi terakhir
dipilih secara default, termasuk demo jika demo adalah run terakhir—pilih
ID sesi LIVE yang benar saat melakukan analisis.

Uji tanpa session pasar:

```bash
uv run python tools/demo_recording.py --output postgres
uv run python index.py --replay postgres
```

Demo diberi label `SYNTHETIC`, berisi 9 event, 2 Done unik dan 1 duplikat.

## Konfigurasi sendiri

Default bekerja tanpa file tambahan. Bila perlu mengubah port/user/password,
buat `.env.postgres` mengikuti `.env.postgres.example` (jangan menimpa file yang
sudah ada). Python membaca file ini dari folder aktif, lalu menimpa nilainya
dengan variabel `PG_*` proses bila tersedia. Jalankan Compose dengan file yang sama:

```bash
docker compose --env-file .env.postgres up -d --wait
```

File `.env.postgres` diabaikan Git dan terpisah dari `.env` Stockbit. Jangan
menaruh password dalam argumen command line/URL atau menempelkan isi file ke
chat. `PG_HOST` dipakai Python; service di dalam container tetap memakai 5432.
Hindari mendefinisikan `PG_*` lain di `.env` Stockbit agar konfigurasi Compose
dan Python tidak berbeda secara tak sengaja.

User/database/password dari environment image dipakai ketika volume pertama
kali diinisialisasi. Mengubah `.env.postgres` **tidak** otomatis mengubah user
atau password database yang sudah ada. Jangan menghapus volume untuk sekadar
mengganti password; ubah credential di PostgreSQL dan konfigurasi client secara
terkoordinasi.

## Data dan persistensi

- Volume: `stockbit-ws_postgres_data`; restart/recreate container mempertahankan
  data selama volume tidak dihapus. Jangan gunakan `docker compose down -v`
  bila ingin mempertahankan rekaman.
- Tabel di schema `stockbit_ws`: `meta` untuk versi schema, `sessions` untuk
  metadata run, `events` untuk event berurutan. Payload memakai `JSONB`;
  timestamp memakai `timestamptz`; trade ID uint64 tetap utuh di payload JSON.
- Running Trade `--all` memakai sesi dengan `symbol = '*'`; kode saham sebenarnya
  berada pada setiap elemen `events.payload.trades`. Bentuk tabel tetap sama.
- Normalisasi, redaksi credential, deduplikasi, kualitas data, dan state replay
  memakai kontrak event yang tervalidasi. Tidak ada raw frame login atau
  body teks server yang disimpan.
- Tiap event di-commit sebelum state diubah. Jika database gagal/terputus,
  client berhenti dengan error. Tidak ada fallback ke penyimpanan lain.
- Replay mengambil halaman kecil dengan batas sequence awal; tidak memuat
  seluruh hari ke memori atau mengikuti sesi OPEN tanpa akhir. Sesi terbuka
  tetap ditandai belum selesai.
- Tidak ada retensi/penghapusan otomatis atau migrasi data lama otomatis.
  Recording/replay hanya menerima PostgreSQL, bukan path file.

Hentikan PostgreSQL tanpa menghapus data:

```bash
docker compose stop postgres
```

## Verifikasi

Tes recording/replay membutuhkan PostgreSQL; tanpa `STOCKBIT_TEST_POSTGRES=1`,
tes tersebut di-skip. Tes decoder/parity tetap dapat berjalan tanpa database.

```bash
STOCKBIT_TEST_POSTGRES=1 uv run python -m unittest discover -s tests -q
npm test
```

Hasil verifikasi perubahan ini: **105 tes Python lulus** dengan PostgreSQL
aktif. Termasuk write/read nyata, replay state/kualitas, JSONB uint64, pagination,
dan penolakan write dari koneksi reader. Test integrasi hanya menghapus sesi
SYNTHETIC dengan ID yang dibuat oleh test itu sendiri; tidak mereset tabel atau
volume. Tanpa flag `STOCKBIT_TEST_POSTGRES=1`, satu test integrasi PostgreSQL
di-skip sehingga suite tetap bisa berjalan tanpa Docker.

Demo sudah direkam, container direstart/recreate, lalu sesi yang sama berhasil
direplay dengan 9 event utuh. Ini menguji database, bukan validasi pasar aktif.

Referensi: [official PostgreSQL image](https://hub.docker.com/_/postgres) dan
[transaksi psycopg](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
