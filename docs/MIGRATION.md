# Migrasi client Stockbit dari JavaScript ke Python

Migrasi dilakukan bertahap dengan mempertahankan client JavaScript sebagai
pembanding dan jalur kembali. Client Python menyediakan subscription symbol
dinamis, order book BID/OFFER, Recent Done, dan tampilan terminal yang setara
pada data yang sudah diuji. Mesin sinyal scalping belum menjadi bagian migrasi.

## Status dan batas bukti

| Pemeriksaan | Status |
|---|---|
| Suite Python per 6 September 2026 | 77 lulus, termasuk 10 parity dan 8 transport/TLS |
| Test JavaScript yang dipertahankan | 16 lulus |
| Perbandingan Python–JavaScript | 10 test offline lulus dengan fixture sintetis |
| Validasi offline konfigurasi lokal untuk BMRI | Lulus; 9 field symbol diubah di memori |
| Uji koneksi Python setelah perbaikan CA macOS | Handshake berhasil, 3 frame dikirim; dalam 12 detik menerima 2 pesan binary (masing-masing 29 B), tanpa Order Book/Done |
| Pemeriksaan lokal klaim masa berlaku token capture | Nilai `exp` pada ketiga token sudah lewat menurut jam lokal; signature tidak diverifikasi oleh pemeriksaan ini |
| Kontinuitas transaksi Done baru selama sesi aktif | Belum terbukti |
| Kapasitas pemrosesan saat pasar ramai | Belum diukur |

Uji memakai Python 3.14.6, websockets 17.1, python-dotenv 1.2.3, dan certifi
2026.7.22 yang dicatat dalam lockfile. Semua test menggunakan fixture sintetis;
test transport hanya membuka server lokal, bukan koneksi Stockbit.

Hasil koneksi tersebut membuktikan transport TLS/WebSocket dan pengiriman,
bukan keberhasilan authentication/subscription atau validasi decoder live.
Isi dua pesan 29 B tidak diberi makna protokol berdasarkan ukurannya saja.
Untuk melanjutkan uji live, perbarui tiga frame menggunakan sesi Stockbit
Anda yang aktif, tanpa mengirim isi frame ke chat atau log. Migrasi tidak
mengubah `.env` yang ada. Client JavaScript juga tetap bergantung pada masa
berlaku session; beralih bahasa tidak memperpanjangnya.

Validasi offline memeriksa format capture dan perubahan symbol. Validasi ini
tidak memeriksa masa berlaku session atau memastikan server menerima koneksi.
Snapshot Done yang berhasil diterima juga belum membuktikan bahwa transaksi
baru terus mengalir atau bahwa feed memuat seluruh transaksi pasar.

Python minimum yang dideklarasikan adalah 3.11. Pengujian lokal migrasi ini
menggunakan Python 3.14; kompatibilitas pada seluruh versi 3.11 ke atas belum
diuji satu per satu.

## Tahap 1 — Siapkan Python tanpa mengganti client lama

Dari folder project, gunakan `uv` untuk menyiapkan lingkungan dan dependency
sesuai lockfile:

```bash
uv sync --locked
```

File `.env` yang sudah digunakan oleh JavaScript tetap digunakan oleh Python.
Migrasi ini tidak mengubah isinya. Tiga nama frame tetap:

```text
STOCKBIT_FRAME_1
STOCKBIT_FRAME_2
STOCKBIT_FRAME_3
```

Program mengubah symbol pada salinan frame di memori; hasil perubahan tidak
ditulis ke `.env`. Replay tetap menggunakan tiga frame yang telah bekerja di
project, dengan target pengiriman 0, 180, dan 400 milidetik sejak pengiriman
dimulai. Nama frame pada log mengikuti implementasi lama dan tidak menjadi
penetapan resmi atas jenis pesan protokol.

## Tahap 2 — Periksa konfigurasi secara offline

```bash
uv run python index.py BMRI --check
```

Hasil yang diharapkan adalah pesan `Validasi offline OK`. Perintah ini tidak
membuka WebSocket. Untuk melihat jumlah field yang diganti tanpa menampilkan
credential atau isi frame:

```bash
uv run python index.py BMRI --check --debug
```

Jika capture menggunakan symbol COCO dengan bentuk yang telah divalidasi,
perubahan ke BMRI mengganti 9 field pada frame kedua dan ketiga. Jika symbol
tujuan sama dengan symbol capture, tidak diperlukan perubahan byte.

## Tahap 3 — Uji koneksi terbatas

```bash
uv run python index.py BMRI --duration 30 --debug
```

Perintah ini mengakhiri koneksi setelah 30 detik, termasuk waktu koneksi awal.
Periksa keberhasilan koneksi, pengiriman frame, penerimaan BID dan OFFER,
penerimaan batch Done, serta ringkasan saat program berhenti. Metadata debug
tidak mencetak frame mentah, credential, atau isi pesan teks dari server.

Beberapa instalasi Python di macOS tidak memiliki bundle CA default yang
berfungsi. Transport Python menggunakan konteks TLS standar dan menambahkan
root certificate bundle dari `certifi`. Pemeriksaan sertifikat dan hostname
tetap aktif; migrasi tidak mematikan verifikasi TLS.

Ketika bursa tidak aktif, menerima riwayat Done lama merupakan hasil yang
mungkin terjadi. Pemeriksaan berikutnya harus dilakukan selama sesi aktif
untuk mengamati trade ID atau timestamp baru setelah snapshot awal. Catat
apakah data bertambah, apakah terjadi duplikasi, dan bagaimana hasilnya
dibandingkan dengan tampilan Stockbit pada waktu yang sama.

Uji koneksi singkat belum mengukur keterlambatan data, kelengkapan feed,
kehilangan event, atau kemampuan pemrosesan saat volume pesan tinggi.

## Tahap 4 — Gunakan client Python dan pertahankan jalur kembali

Setelah hasil uji koneksi sesuai, jalankan tanpa batas durasi:

```bash
uv run python index.py BMRI
```

Gunakan `Ctrl+C` untuk menghentikan client. Symbol lain dapat digunakan dengan
pola perintah yang sama. Saat ini satu proses mengamati satu symbol.

Tampilan memiliki dua bagian:

- `ORDER BOOK`: state BID dan OFFER yang diperbarui terpisah.
- `RECENT DONE`: transaksi terbaru yang didecode, diurutkan, dan dideduplikasi.

State Recent Done menyimpan maksimal 100 transaksi dan tampilan menampilkan
20 transaksi. Kedua angka ini merupakan batas penyimpanan dan tampilan lokal,
bukan batas jumlah record per message WebSocket. Fixture parity menguji satu
batch berisi 40 record, dengan seluruh record diproses sebelum pembatasan
tampilan. Penyimpanan ini masih berada di memori, bukan jurnal permanen.

Jika perlu kembali ke implementasi sebelumnya, hentikan proses Python lalu
jalankan:

```bash
node index.js BMRI
```

Source JavaScript dan konfigurasi tetap tersedia; rollback tidak memerlukan
konversi frame atau perubahan `.env`.

## Perilaku yang dipertahankan dan perbaikan yang disengaja

Test parity membandingkan nilai hasil decoder, timestamp hingga milidetik,
baris tabel, state order book per symbol, hasil deduplikasi, dan byte frame
subscription pada input yang didukung bersama oleh kedua client. Semua fixture
parity sintetis; pengujian tidak membaca `.env` atau membuka koneksi jaringan.

Beberapa perbedaan Python memang disengaja dan diuji terpisah:

- Validasi subscription lebih ketat: setiap container subscription tidak kosong
  harus memiliki keempat field inti 2, 6, 7, dan 9 secara konsisten. Field ganda,
  symbol yang bertentangan, atau struktur ambigu ditolak sebelum pengiriman.
- Perubahan symbol mempertahankan potongan byte field yang tidak disentuh,
  termasuk unknown fields dan representasi varint nonkanonis. Hanya nilai
  symbol serta panjang container yang relevan diperbarui.
- Decoder Done mengumpulkan record dari seluruh container outer field 8 yang
  valid dalam satu message. JavaScript mengembalikan batch valid pertama saja.
- Handler menjalankan decoder order book dan Done pada message yang sama,
  sehingga keduanya tetap diproses ketika satu message memuat kedua jenis data.
- Integer Python mempertahankan nilai uint64 secara tepat. Pengurutan trade ID
  besar pada timestamp yang sama tidak perlu dikonversi menjadi floating point.

Pemetaan side `1 = HAKA/BUY` dan `2 = HAKI/SELL` tetap mengikuti interpretasi
feed pada project sebelumnya. Migrasi bahasa tidak menambah bukti baru bahwa
pemetaan tersebut merupakan definisi protokol resmi.

## Menjalankan pemeriksaan ulang

Seluruh test Python:

```bash
uv run python -m unittest discover -s tests -v
```

Hanya perbandingan dengan JavaScript:

```bash
uv run python -m unittest discover -s tests -p 'test_parity.py' -v
```

Test client JavaScript yang dipertahankan:

```bash
npm test
```

Node.js diperlukan untuk parity dan test JavaScript. Jika Node tidak tersedia,
test parity berstatus skip; itu tidak sama dengan lolos perbandingan. Client
Python sendiri tidak memerlukan Node.js untuk beroperasi.

## Tahap berikutnya setelah migrasi

Perekaman event pasar, pemeriksaan kualitas, dan replay offline kini sudah
diimplementasikan sebagai tahap lanjutan. Lihat [panduan tes live Senin](LIVE_TEST.md)
untuk perintah dan batasannya. Hasil 77 test di atas adalah checkpoint migrasi;
suite lanjutan menambahkan pengujian recorder/kualitas/replay.

Gate berikutnya adalah membuktikan aliran Done baru selama sesi aktif dan
mengukur perilaku client pada periode ramai. Rekaman event dan replay yang
sudah tersedia menjadi fondasi pengujian konsep sinyal setelah gate ini lulus.

Tahap riset setelah migrasi kini menambahkan scanner multi-symbol, replay
deterministik, paper sniper, dan reconnect terbatas pada sidecar L2. Feed utama
belum reconnect otomatis; refresh session, model probabilitas profit yang
tervalidasi, dan auto buy/sell juga belum tersedia. Session yang kedaluwarsa
tetap perlu diperbarui melalui capture yang valid. Hasil paper terbaru ada di
[`reports/research_validation_2026-09-09.md`](../reports/research_validation_2026-09-09.md)
dan belum menunjukkan strategi yang profitable.
