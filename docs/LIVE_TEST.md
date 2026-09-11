# Persiapan tes live Senin — recorder, kualitas, replay

Validasi JS hari Jumat menjadi acuan. Implementasi berikutnya disiapkan secara
offline; pengujian pasar aktif Python dilanjutkan Senin menggunakan session
Stockbit yang masih berlaku. Tidak ada order jual/beli, mesin sinyal, atau
pengambilan credential otomatis dalam perubahan ini.

## Yang sudah tersedia

- Rekaman PostgreSQL Docker saja, append sesi baru setiap run, dengan versi schema 1.
- Event Order Book dan Done yang sudah dinormalisasi; timestamp penerimaan UTC
  dan urutan waktu monotonic. Waktu event order book dari server belum tersedia;
  jangan menyamakan waktu penerimaan dengan waktu kejadian di bursa.
- Metadata pesan (jenis dan ukuran saja) serta koneksi CONNECTING/CONNECTED/
  DISCONNECTED. Unknown binary dan body teks tidak disimpan.
- Duplikasi Done tetap disimpan sebelum pembatasan state tampilan 100 record.
- Pemeriksaan kualitas berkala saat pesan berhenti, dan replay database read-only tanpa
  koneksi Stockbit atau `.env` Stockbit.

Credential, frame keluar, raw frame masuk, dan field tidak dikenal tidak masuk
ke database. Ini disengaja: rekaman dipakai untuk menguji pengolahan state dan
calon fitur analisis. Pengujian decoder binary tetap memakai fixture sintetis
dan test parity, bukan database ini.

## Tes offline sekarang

Checkpoint setelah PostgreSQL: **105 tes Python (dengan test PostgreSQL aktif) dan 16 tes JavaScript lulus**.
Checkpoint mode Running Trade `--all`: **112 tes Python dengan PostgreSQL aktif
dan 16 tes JavaScript lulus**. Pembentukan frame dari `.env` lokal lolos pemeriksaan
offline; belum ada validasi subscription wildcard di server atau uji beban pasar.
Termasuk alur WebSocket lokal → decoder → rekaman → replay, kesetaraan state
dan hitungan kualitas, serta kegagalan penyimpanan. Demo CLI juga sudah
dijalankan dengan hasil yang diharapkan. Ini tidak menggantikan tes pasar
aktif Senin. PostgreSQL menggunakan driver `psycopg`; tidak ada ORM. Konfigurasi Docker dan batasannya ada di [panduan PostgreSQL](POSTGRES.md).

```bash
uv sync --locked
docker compose up -d --wait postgres
STOCKBIT_TEST_POSTGRES=1 uv run python -m unittest discover -s tests -q
npm test
uv run python tools/demo_recording.py
uv run python index.py --replay postgres --speed 10
```

Demo berlabel **SYNTHETIC**, dibuat tanpa Stockbit. Isinya BID/OFFER, Done
berulang, Done baru, jeda panjang, lalu disconnect. Harapannya ada dua trade
unik dan satu duplikat; data menjadi STALE saat jeda walaupun kemudian ada
pesan binary metadata. Status akhir DISCONNECTED. Demo bukan bukti feed live.

## Jalankan Senin

1. Pastikan tiga frame `.env` berasal dari sesi aktif milik Anda. Jangan kirim
   isi frame ke chat atau log. Migrasi tidak memperpanjang masa berlaku token.
2. Hentikan client lain sebelum tes agar pembandingan sesi lebih mudah.
3. Periksa struktur offline:

   ```bash
   uv run python index.py BMRI --check
   ```

4. Rekam satu symbol selama 30 menit (atau Ctrl+C untuk berhenti lebih awal):

   ```bash
   uv run python index.py BMRI --record postgres --duration 1800
   ```

5. Cocokkan dengan UI Stockbit pada symbol/waktu yang sama: harga terbaik,
   lot, BID/OFFER, serta harga/lot/waktu dan trade ID Done bila tersedia.
   Perbedaan snapshot karena waktu pengamatan berbeda perlu dibedakan dari
   kesalahan decoder.
6. Amati apakah timestamp/trade ID Done bertambah setelah snapshot awal.
   Catat periode tanpa data dan peringatan kualitas. Ukuran pesan saja bukan
   dasar menentukan makna pesan server atau keberhasilan authentication.
7. Setelah client berhenti, replay sesi yang tersimpan:

   ```bash
   uv run python index.py --replay postgres --sessions
   uv run python index.py --replay postgres
   uv run python index.py --replay postgres --speed 10
   ```

Daftar menampilkan ID, symbol, waktu mulai, status penutupan, dan sumber data.
Gunakan `--session SESSION_ID` untuk memilih run tertentu. Default adalah run
terakhir, bukan penggabungan semua run. `LIVE` berarti sumbernya jalur koneksi
live, **bukan tanda bahwa feed telah tervalidasi**.

## Membaca status kualitas

| Status/check | Makna |
|---|---|
| CONNECTING / DISCONNECTED | Status transport; tidak menyatakan kualitas data |
| WAITING | Belum ada data pasar target yang cukup |
| PARTIAL | Ada sisi/data yang belum tersedia, kosong, atau peringatan lain |
| STALE | Umur salah satu sisi book atau timestamp Done melewati ambang |
| RECENT_OBSERVED | Kedua sisi nonkosong dan Done tampak baru menurut ambang; kelengkapan tetap UNKNOWN |
| DONE_CLOCK_AHEAD | Timestamp Done lebih dari 5 detik di depan jam penerimaan; periksa jam/interpretasi waktu |
| LOCKED_OR_CROSSED_BOOK | Best BID >= best OFFER; perlu konteks sesi/auction, bukan otomatis dianggap korup |

Ambang default 15 detik adalah parameter diagnostik, bukan aturan strategi.
Gunakan `--stale-after 30` pada run live untuk mengubahnya. Replay menggunakan
ambang yang tersimpan agar hasil bisa diulang. Tidak ada jadwal bursa yang
ditanamkan; peringatan STALE juga bisa wajar saat pasar tenang/istirahat.

Umur **penerimaan batch Done** dan umur **timestamp transaksi Done** berbeda.
Batch lama yang dikirim lagi tidak membuat transaksi lama menjadi baru.
Metadata heartbeat/teks juga tidak memperbarui umur BID/OFFER.

Hitungan duplikasi menggunakan trade ID (atau gabungan waktu/harga/volume/side
jika ID tidak ada), dengan cache maksimal 10.000 kunci per sesi. Setelah kunci
terbuang, pengulangan sangat lama bisa dihitung lagi sebagai baru; nilai
`dedupEvictions` mengungkap hal ini. Hitungan `uniqueDoneWindow` bersifat
kumulatif berdasarkan cache tersebut, bukan jumlah unik seumur pasar.
`lateDoneWindow` menandai record baru dalam cache yang timestamp-nya lebih lama
daripada timestamp maksimum **batch sebelumnya**, bukan urutan descending
di dalam snapshot awal. `timestampAfterStartWindow` hanya perbandingan waktu,
bukan bukti tipe snapshot/incremental; `batchKind` selalu `unknown` sampai
semantik protokolnya terkonfirmasi.

## Keandalan dan batasan rekaman

- Event di-commit ke database secara sinkron, sebelum state diubah. Tidak ada
  antrean yang diam-diam membuang event. Jika penulisan gagal, koneksi dihentikan
  dengan error; periksa ruang disk dan izin. Beban I/O saat pasar ramai belum
  diukur, jadi mulai dari satu symbol.
- Redraw terminal dibatasi sekitar 4 kali/detik saat pesan ramai; pembatasan
  tampilan tidak membatasi jumlah event yang direkam.
- `COMPLETED` berarti proses selesai normal (termasuk durasi habis), `STOPPED`
  berarti dihentikan pengguna, `ERROR` berarti gagal, dan `OPEN` berarti belum
  ada penutupan tercatat. Status ini bukan jaminan kelengkapan data.
- Jika proses crash/dipaksa berhenti, transaksi database yang sudah committed
  tetap dapat dibaca; replay memperingatkan sesi OPEN/ERROR. Event sebelum
  commit dan data yang tak pernah sampai ke client tidak bisa direkonstruksi.
- Database tumbuh selama perekaman dan belum memiliki retensi/penghapusan
  otomatis. PostgreSQL memakai named volume Docker; restart container tidak
  menghapus data. Jangan menghapus volume. Recording/replay tidak menerima target file.
- Replay mempertahankan urutan penerimaan dan waktu historis, termasuk jeda.
  `--speed 0` langsung menuju hasil akhir; kecepatan positif menampilkan alur.
  Replay dibatasi pada satu sesi agar state antar-koneksi tidak tercampur.
- Belum ada reconnect/refresh otomatis, deteksi kehilangan berbasis sequence
  number bursa, pengukuran latensi bursa yang pasti, atau bukti kelengkapan feed.

## Kriteria selesai tes Senin

Koneksi/subscription diterima, kedua sisi book cocok pada pengamatan sebanding,
Done bertambah setelah snapshot awal, perekaman berhenti tanpa error, dan replay
mereproduksi state/duplikasi sesi tersebut. Bila ini terpenuhi, pekerjaan
berikutnya adalah evaluasi data rekaman dan rancangan fitur sinyal, bukan
langsung auto buy/sell.

Fallback JavaScript tetap tersedia: hentikan Python lalu `node index.js BMRI`.
Fallback tersebut tidak merekam ke database Python dan tetap membutuhkan
session yang valid. Tidak ada task terjadwal otomatis; perintah tes dijalankan
ketika Anda siap pada sesi aktif.
