# Laporan Kualitas Rekaman & Analisis Deskriptif
**Session ID**: `2b7935ca680047818e52085e2893bc7b` | **Symbol**: `PTRO` | **Status**: `STOPPED` | **Source**: `LIVE`
**Waktu**: 2026-09-07T03:34:32.583+00:00 s.d. 2026-09-07T05:00:18.288+00:00 (Durasi: 5145.8 detik)

## 1. Audit Transaksi Unik & Deduplikasi Database
- **Total Batch Done Diterima**: 1,576
- **Total Record Transaksi Mentah**: 3,742
- **Transaksi Memiliki Trade ID**: 3,742 (Unik: 3,742)
- **Transaksi Tanpa Trade ID**: 0 (Unik: 0)
- **Duplikat di Database**: 0 record
- **Total Transaksi Unik Sebenarnya**: **3,742**

## 2. Pembandingan Ketat (Dedicated vs Wildcard '*')
- **Saham Diuji**: `PTRO`
- **Irisan Waktu**: `2026-09-07T03:34:32.583+00:00` s.d. `2026-09-07T05:00:14.224+00:00` (5141.6s)
- **Unique Trade ID Sesi Khusus**: 3,703
- **Unique Trade ID Sesi Wildcard**: 3,687
- **Tingkat Kecocokan (Intersection)**: **3,687 (99.57%)**
- **Ada di Khusus, Hilang di Wildcard**: **16 trade**
- **Ada di Wildcard, Hilang di Khusus**: **0 trade**
- **Perbedaan Nilai/Data pada Trade yang Cocok**: **0**
- **Delay Waktu Klien (Exchange Timestamp vs Received At)**:
  - Sesi Khusus  : Rata-rata -62.6 ms | Median -57.0 ms | P95 15.0 ms
  - Sesi Wildcard: Rata-rata -64.9 ms | Median -58.0 ms | P95 15.0 ms

  *Sampel Transaksi Hilang di Wildcard:*
  | Trade ID | Waktu Bursa (UTC) | Waktu Terima (UTC) | Harga | Lot | Aksi |
  |---|---|---|---|---|---|
  | 1027895 | 2026-09-07T03:40:46.784+00:00 | 2026-09-07T03:40:46.795+00:00 | 5550.0 | 1.0 | BUY |
  | 1027896 | 2026-09-07T03:40:46.784+00:00 | 2026-09-07T03:40:46.795+00:00 | 5550.0 | 4.0 | BUY |
  | 1101600 | 2026-09-07T04:00:05.697+00:00 | 2026-09-07T04:00:05.701+00:00 | 5550.0 | 500.0 | SELL |
  | 1101601 | 2026-09-07T04:00:05.697+00:00 | 2026-09-07T04:00:05.701+00:00 | 5550.0 | 2.0 | SELL |
  | 1101602 | 2026-09-07T04:00:05.697+00:00 | 2026-09-07T04:00:05.701+00:00 | 5550.0 | 10.0 | SELL |

  > *Catatan Faktual: Perbedaan transaksi teramati saat lonjakan transaksi bursa terjadi simultan. Tidak ada deviasi harga/lot pada transaksi yang cocok.*

## 3. Pengukuran Kemampuan & Throughput Recorder
- **Total Event Database**: 21,759 event
- **Throughput Rata-rata**: 4.23 event/detik (Median: 4 event/s)
- **Beban Puncak (Peak Throughput)**: **36 event/detik** (P95: 15 e/s, P99: 22 e/s)
- **Kedatangan Simultan (Δt = 0 ms)**: 10,095 event (46.39%)
- **Jeda Tertua Tanpa Pesan**: 9698 ms
- **Evaluasi Kebutuhan Antrean & Batching**: `AMAN (SINGLE WRITE): Throughput saat ini masih dalam kapasitas aman I/O sinkron.`

## 4. Analisis Deskriptif Pasar & Mikrostruktur
- **Total Volume Transaksi**: 103,444 lot | **Nilai Total**: Rp57.504.297.500
- **Proporsi Agresi Transaksi**:
  - **HAKA (Buy Agresif)** : 1,312 trade (30.84%) | 31,883 lot | Rp17.736.150.000
  - **HAKI (Sell Agresif)**: 2,430 trade (69.16%) | 71,561 lot | Rp39.768.147.500
  - **Net Aggression Flow**: **Rp-22.031.997.500** (-39,678 lot)
- **Kecepatan Transaksi (Trade Velocity)**:
  - Jendela 1 Detik : Maks 200 trade/s | Rata-rata 2.9 trade/s | P95 8 trade/s
  - Jendela 5 Detik : Maks 233 trade/5s | Rata-rata 5.1 trade/5s | P95 18 trade/5s
  - Jendela 30 Detik: Maks 364 trade/30s | Rata-rata 21.9 trade/30s | P95 83 trade/30s
- **Dinamika Buku Pesanan (Order Book)**:
  - Total Update Order Book: 8,514 update
  - Rata-rata Spread: 25.21 poin (45.35 bps) | Rentang: 0.0 - 50.0 poin
  - Rata-rata Top-1 Depth Imbalance: +0.250 (Skala -1.0 s.d. +1.0)
  - Rata-rata Top-3 Depth Imbalance: +0.350
  - Kejadian Crossed/Locked Book: 0

## VERDICT: KONSISTENSI DATA & KELAYAKAN RISET SINYAL
✅ **LAYAK PENUH UNTUK RISET SINYAL (HIGH INTEGRITY)**

Data rekaman sesi per-saham ini memiliki kelengkapan dan konsistensi sangat tinggi. Seluruh transaksi yang diterima memiliki urutan sequence utuh, 0 perbedaan nilai pada cross-validation, dan mikrostruktur buku pesanan stabil. Aman digunakan sebagai dasar pengujian kandidat sinyal.