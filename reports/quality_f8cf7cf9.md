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
- **Delay Waktu Klien (Exchange Timestamp vs Received At)**:
  - Sesi Khusus  : Rata-rata -60.3 ms | Median -50.0 ms | P95 31.0 ms
  - Sesi Wildcard: Rata-rata -63.6 ms | Median -56.0 ms | P95 21.0 ms

  *Sampel Transaksi Hilang di Wildcard:*
  | Trade ID | Waktu Bursa (UTC) | Waktu Terima (UTC) | Harga | Lot | Aksi |
  |---|---|---|---|---|---|
  | 985406 | 2026-09-07T03:32:15.283+00:00 | 2026-09-07T03:32:15.315+00:00 | 222.0 | 50.0 | SELL |
  | 985407 | 2026-09-07T03:32:15.283+00:00 | 2026-09-07T03:32:15.315+00:00 | 222.0 | 10.0 | SELL |
  | 985408 | 2026-09-07T03:32:15.283+00:00 | 2026-09-07T03:32:15.315+00:00 | 222.0 | 10.0 | SELL |
  | 985409 | 2026-09-07T03:32:15.283+00:00 | 2026-09-07T03:32:15.315+00:00 | 222.0 | 198.0 | SELL |
  | 995541 | 2026-09-07T03:33:56.018+00:00 | 2026-09-07T03:33:56.009+00:00 | 220.0 | 746.0 | SELL |

  > *Catatan Faktual: Perbedaan transaksi teramati saat lonjakan transaksi bursa terjadi simultan. Tidak ada deviasi harga/lot pada transaksi yang cocok.*

## 3. Pengukuran Kemampuan & Throughput Recorder
- **Total Event Database**: 66,753 event
- **Throughput Rata-rata**: 12.09 event/detik (Median: 11 event/s)
- **Beban Puncak (Peak Throughput)**: **46 event/detik** (P95: 24 e/s, P99: 31 e/s)
- **Kedatangan Simultan (Δt = 0 ms)**: 30,602 event (45.84%)
- **Jeda Tertua Tanpa Pesan**: 3984 ms
- **Evaluasi Kebutuhan Antrean & Batching**: `AMAN (SINGLE WRITE): Throughput saat ini masih dalam kapasitas aman I/O sinkron.`

## 4. Analisis Deskriptif Pasar & Mikrostruktur
- **Total Volume Transaksi**: 4,072,251 lot | **Nilai Total**: Rp90.351.289.600
- **Proporsi Agresi Transaksi**:
  - **HAKA (Buy Agresif)** : 4,961 trade (60.73%) | 2,468,280 lot | Rp54.867.394.000
  - **HAKI (Sell Agresif)**: 3,631 trade (39.27%) | 1,603,971 lot | Rp35.483.895.600
  - **Net Aggression Flow**: **+Rp19.383.498.400** (+864,309 lot)
- **Kecepatan Transaksi (Trade Velocity)**:
  - Jendela 1 Detik : Maks 401 trade/s | Rata-rata 2.5 trade/s | P95 4 trade/s
  - Jendela 5 Detik : Maks 609 trade/5s | Rata-rata 7.8 trade/5s | P95 14 trade/5s
  - Jendela 30 Detik: Maks 639 trade/30s | Rata-rata 46.7 trade/30s | P95 84 trade/30s
- **Dinamika Buku Pesanan (Order Book)**:
  - Total Update Order Book: 25,030 update
  - Rata-rata Spread: 2.0 poin (90.19 bps) | Rentang: 0.0 - 4.0 poin
  - Rata-rata Top-1 Depth Imbalance: +0.060 (Skala -1.0 s.d. +1.0)
  - Rata-rata Top-3 Depth Imbalance: -0.010
  - Kejadian Crossed/Locked Book: 0

## VERDICT: KONSISTENSI DATA & KELAYAKAN RISET SINYAL
✅ **LAYAK PENUH UNTUK RISET SINYAL (HIGH INTEGRITY)**

Data rekaman sesi per-saham ini memiliki kelengkapan dan konsistensi sangat tinggi. Seluruh transaksi yang diterima memiliki urutan sequence utuh, 0 perbedaan nilai pada cross-validation, dan mikrostruktur buku pesanan stabil. Aman digunakan sebagai dasar pengujian kandidat sinyal.