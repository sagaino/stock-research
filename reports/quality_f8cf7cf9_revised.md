# Laporan Kualitas Rekaman & Analisis Deskriptif
**Session ID**: `f8cf7cf9ff794499bb9cda8f8d646b03` | **Symbol**: `BUMI` | **Status**: `STOPPED` | **Source**: `LIVE`
**Waktu**: 2026-09-07T03:28:15.006+00:00 s.d. 2026-09-07T05:00:16.485+00:00 (Durasi: 5521.5 detik)

## 1. Audit Transaksi Unik & Deduplikasi Database
- **Total Batch Done Diterima**: 5,566
- **Total Record Transaksi Mentah**: 8,592
- **Transaksi Memiliki Trade ID**: 8,592 (Unik: 8,592)
- **Transaksi Tanpa Trade ID**: 0 (Unik: 0)
- **Duplikat di Database**: 0 record
- **Total Transaksi Unik Sebenarnya**: **8,592**

## 2. Pembandingan Ketat (Dedicated vs Wildcard '*')
- **Saham Diuji**: `BUMI`
- **Irisan Waktu**: `2026-09-07T03:28:15.006+00:00` s.d. `2026-09-07T05:00:14.224+00:00` (5519.2s)
- **Unique Trade ID Sesi Khusus**: 8,553
- **Unique Trade ID Sesi Wildcard**: 8,538
- **Tingkat Kecocokan (Intersection)**: **8,538 (99.82%)**
- **Ada di Khusus, Hilang di Wildcard**: **15 trade**
- **Ada di Wildcard, Hilang di Khusus**: **0 trade**
- **Perbedaan Nilai/Data pada Trade yang Cocok**: **0**
- **Selisih Timestamp (Received At minus timestamp transaksi; bukan latensi jaringan terverifikasi)**:
  - Sesi Khusus  : Rata-rata -60.3 ms | Median -50.0 ms | P95 31.0 ms
  - Sesi Wildcard: Rata-rata -63.6 ms | Median -56.0 ms | P95 21.0 ms
  - Selisih negatif: dedicated=7063, wildcard=7368; perbedaan jam/makna timestamp belum dikoreksi.
- Record tanpa ID dikecualikan: dedicated=0, wildcard=0
- Irisan memakai timestamp transaksi terhadap batas sesi lokal; bukan jaminan cakupan server identik.

  *Sampel Transaksi Hilang di Wildcard:*
  | Trade ID | Waktu Bursa (UTC) | Waktu Terima (UTC) | Harga | Lot | Aksi |
  |---|---|---|---|---|---|
  | 985406 | 2026-09-07T03:32:15.283+00:00 | 2026-09-07T03:32:15.315+00:00 | 222.0 | 50.0 | SELL |
  | 985407 | 2026-09-07T03:32:15.283+00:00 | 2026-09-07T03:32:15.315+00:00 | 222.0 | 10.0 | SELL |
  | 985408 | 2026-09-07T03:32:15.283+00:00 | 2026-09-07T03:32:15.315+00:00 | 222.0 | 10.0 | SELL |
  | 985409 | 2026-09-07T03:32:15.283+00:00 | 2026-09-07T03:32:15.315+00:00 | 222.0 | 198.0 | SELL |
  | 995541 | 2026-09-07T03:33:56.018+00:00 | 2026-09-07T03:33:56.009+00:00 | 220.0 | 746.0 | SELL |

  > *Catatan Faktual: Selisih adalah perbedaan rekaman; penyebab belum ditentukan. Kecocokan hanya berlaku untuk sampel ini, bukan kelengkapan seluruh pasar.*

## 3. Pengukuran Kemampuan & Throughput Recorder
- **Total Event Database**: 66,753 event
- **Throughput Rata-rata**: 12.09 event/detik (Median: 11 event/s)
- **Beban Puncak (Peak Throughput)**: **46 event/detik** (P95: 24 e/s, P99: 31 e/s)
- **Pasangan Event Bertimestamp Sama (dapat berasal dari satu pesan)**: 30,601 event (45.84%)
- **Jeda Terpanjang Antar-event**: 3984 ms
- **Evaluasi Kebutuhan Antrean & Batching**: `BELUM TERUKUR: durasi commit, backlog, dan event-loop lag tidak direkam; jumlah event bukan bukti kapasitas I/O.`

- Anomali sequence lokal: 0; elapsed mundur: 0
- Median/persentil event hanya bucket detik terisi; bukan kapasitas recorder.
## 4. Analisis Deskriptif Pasar & Mikrostruktur
- **Total Volume Transaksi**: 4,072,251 lot | **Nilai Total**: Rp90.351.289.600
- **Proporsi Agresi Transaksi**:
  - **HAKA (Buy Agresif)** : 4,961 trade (60.73%) | 2,468,280 lot | Rp54.867.394.000
  - **HAKI (Sell Agresif)**: 3,631 trade (39.27%) | 1,603,971 lot | Rp35.483.895.600
  - **Net Aggression Flow**: **+Rp19.383.498.400** (+864,309 lot)
- Volume/nilai memakai salinan pertama transaksi unik; fallback tanpa ID bersifat perkiraan.
- **Kecepatan teramati client**: bucket tetap dari waktu penerimaan, bukan waktu bursa; rata-rata/persentil hanya bucket terisi. Snapshot awal dapat menaikkan puncak.
  - Jendela 1 Detik : Maks 401 trade/s | Rata-rata 2.5 trade/s | P95 4 trade/s
  - Jendela 5 Detik : Maks 609 trade/5s | Rata-rata 7.8 trade/5s | P95 14 trade/5s
  - Jendela 30 Detik: Maks 639 trade/30s | Rata-rata 46.7 trade/30s | P95 84 trade/30s
- **Dinamika Buku Pesanan (Order Book)**:
  - Total Update Order Book: 25,030 update
  - Rata-rata Spread: 2.0 poin (90.19 bps) | Rentang: 0.0 - 4.0 poin
  - Rata-rata Top-1 Depth Imbalance: +0.060 (Skala -1.0 s.d. +1.0)
  - Rata-rata Top-3 Depth Imbalance: -0.010
  - Crossed book: 0; Locked book: 1
  - Rata-rata berbobot update, bukan durasi; sisi stale belum dikecualikan.

## VERDICT: KONSISTENSI DATA & KELAYAKAN RISET SINYAL
**PERLU PEMERIKSAAN**: terdapat selisih cakupan antarsesi

Urutan lokal dan kesamaan nilai tidak membuktikan kelengkapan bursa. Kapasitas I/O, interpretasi timestamp/side, serta penyebab transaksi tidak ditemukan belum terverifikasi. Net aggression bukan bukti akumulasi/distribusi atau arus dana bersih.

Cache deduplikasi tidak memangkas hitungan kumulatif; eviction hanya dapat membuat transaksi lama dihitung baru lagi bila dikirim ulang. Tidak menyimpulkan selisih berasal dari cache tanpa pembuktian.