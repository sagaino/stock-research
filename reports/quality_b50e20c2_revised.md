# Laporan Kualitas Rekaman & Analisis Deskriptif
**Session ID**: `b50e20c2d68047d39b184e7c259a3cbc` | **Symbol**: `IMPC` | **Status**: `STOPPED` | **Source**: `LIVE`
**Waktu**: 2026-09-07T03:42:53.787+00:00 s.d. 2026-09-07T05:00:20.736+00:00 (Durasi: 4647.0 detik)

## 1. Audit Transaksi Unik & Deduplikasi Database
- **Total Batch Done Diterima**: 221
- **Total Record Transaksi Mentah**: 620
- **Transaksi Memiliki Trade ID**: 620 (Unik: 620)
- **Transaksi Tanpa Trade ID**: 0 (Unik: 0)
- **Duplikat di Database**: 0 record
- **Total Transaksi Unik Sebenarnya**: **620**

## 3. Pengukuran Kemampuan & Throughput Recorder
- **Total Event Database**: 3,167 event
- **Throughput Rata-rata**: 0.68 event/detik (Median: 2 event/s)
- **Beban Puncak (Peak Throughput)**: **19 event/detik** (P95: 8 e/s, P99: 12 e/s)
- **Pasangan Event Bertimestamp Sama (dapat berasal dari satu pesan)**: 1,471 event (46.46%)
- **Jeda Terpanjang Antar-event**: 62699 ms
- **Evaluasi Kebutuhan Antrean & Batching**: `BELUM TERUKUR: durasi commit, backlog, dan event-loop lag tidak direkam; jumlah event bukan bukti kapasitas I/O.`

- Anomali sequence lokal: 0; elapsed mundur: 0
- Median/persentil event hanya bucket detik terisi; bukan kapasitas recorder.
## 4. Analisis Deskriptif Pasar & Mikrostruktur
- **Total Volume Transaksi**: 21,886 lot | **Nilai Total**: Rp3.220.683.000
- **Proporsi Agresi Transaksi**:
  - **HAKA (Buy Agresif)** : 215 trade (55.29%) | 12,062 lot | Rp1.780.829.500
  - **HAKI (Sell Agresif)**: 405 trade (44.71%) | 9,824 lot | Rp1.439.853.500
  - **Net Aggression Flow**: **+Rp340.976.000** (+2,238 lot)
- Volume/nilai memakai salinan pertama transaksi unik; fallback tanpa ID bersifat perkiraan.
- **Kecepatan teramati client**: bucket tetap dari waktu penerimaan, bukan waktu bursa; rata-rata/persentil hanya bucket terisi. Snapshot awal dapat menaikkan puncak.
  - Jendela 1 Detik : Maks 64 trade/s | Rata-rata 3.0 trade/s | P95 12 trade/s
  - Jendela 5 Detik : Maks 71 trade/5s | Rata-rata 3.4 trade/5s | P95 14 trade/5s
  - Jendela 30 Detik: Maks 71 trade/30s | Rata-rata 5.7 trade/30s | P95 25 trade/30s
- **Dinamika Buku Pesanan (Order Book)**:
  - Total Update Order Book: 1,250 update
  - Rata-rata Spread: 6.43 poin (43.76 bps) | Rentang: 0.0 - 25.0 poin
  - Rata-rata Top-1 Depth Imbalance: +0.250 (Skala -1.0 s.d. +1.0)
  - Rata-rata Top-3 Depth Imbalance: +0.670
  - Crossed book: 0; Locked book: 4
  - Rata-rata berbobot update, bukan durasi; sisi stale belum dikecualikan.

## VERDICT: KONSISTENSI DATA & KELAYAKAN RISET SINYAL
**DESKRIPTIF TERSEDIA; KELENGKAPAN BELUM TERVERIFIKASI**

Pembandingan lintas feed belum dilakukan pada laporan ini.

Urutan lokal dan kesamaan nilai tidak membuktikan kelengkapan bursa. Kapasitas I/O, interpretasi timestamp/side, serta penyebab transaksi tidak ditemukan belum terverifikasi. Net aggression bukan bukti akumulasi/distribusi atau arus dana bersih.

Cache deduplikasi tidak memangkas hitungan kumulatif; eviction hanya dapat membuat transaksi lama dihitung baru lagi bila dikirim ulang. Tidak menyimpulkan selisih berasal dari cache tanpa pembuktian.