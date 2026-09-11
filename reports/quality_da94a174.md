# Laporan Kualitas Rekaman & Analisis Deskriptif
**Session ID**: `da94a1743d464e7097f12f41a04a56ff` | **Symbol**: `*` | **Status**: `STOPPED` | **Source**: `LIVE`
**Waktu**: 2026-09-09T06:31:33.288+00:00 s.d. 2026-09-09T08:50:06.715+00:00 (Durasi: 8313.3 detik)

## 1. Audit Transaksi Unik & Deduplikasi Database
- **Total Batch Done Diterima**: 80,862
- **Total Record Transaksi Mentah**: 743,710
- **Transaksi Memiliki Trade ID**: 743,710 (Unik: 743,710)
- **Transaksi Tanpa Trade ID**: 0 (Unik: 0)
- **Duplikat di Database**: 0 record
- **Total Transaksi Unik Sebenarnya**: **743,710**

## 3. Pengukuran Kemampuan & Throughput Recorder
- **Total Event Database**: 162,548 event
- **Throughput Rata-rata**: 19.55 event/detik (Median: 20.0 event/s)
- **Beban Puncak (Peak Throughput)**: **626 event/detik** (P95: 22 e/s, P99: 26 e/s)
- **Pasangan Event Bertimestamp Sama (dapat berasal dari satu pesan)**: 80,864 event (49.75%)
- **Jeda Terpanjang Antar-event**: 58113 ms
- **Evaluasi Kebutuhan Antrean & Batching**: `BELUM TERUKUR: durasi commit, backlog, dan event-loop lag tidak direkam; jumlah event bukan bukti kapasitas I/O.`

- Anomali sequence lokal: 0; elapsed mundur: 0
- Median/persentil event hanya bucket detik terisi; bukan kapasitas recorder.
## 4. Analisis Deskriptif Pasar & Mikrostruktur
- **Total Volume Transaksi**: 94,221,089 lot | **Nilai Total**: Rp5.376.949.810.700
- **Proporsi Agresi Transaksi**:
  - **HAKA (Buy Agresif)** : 379,285 trade (51.74%) | 44,800,280 lot | Rp2.781.838.510.200
  - **HAKI (Sell Agresif)**: 364,425 trade (48.26%) | 49,420,809 lot | Rp2.595.111.300.500
  - **Net Aggression Flow**: **+Rp186.727.209.700** (+-4,620,529 lot)
- Volume/nilai memakai salinan pertama transaksi unik; fallback tanpa ID bersifat perkiraan.
- **Kecepatan teramati client**: bucket tetap dari waktu penerimaan, bukan waktu bursa; rata-rata/persentil hanya bucket terisi. Snapshot awal dapat menaikkan puncak.
  - Jendela 1 Detik : Maks 2433 trade/s | Rata-rata 90.2 trade/s | P95 202 trade/s
  - Jendela 5 Detik : Maks 4947 trade/5s | Rata-rata 450.5 trade/5s | P95 769 trade/5s
  - Jendela 30 Detik: Maks 6148 trade/30s | Rata-rata 2694.6 trade/30s | P95 4257 trade/30s

## VERDICT: KONSISTENSI DATA & KELAYAKAN RISET SINYAL
**DESKRIPTIF TERSEDIA; KELENGKAPAN BELUM TERVERIFIKASI**

Pembandingan lintas feed belum dilakukan pada laporan ini.

Urutan lokal dan kesamaan nilai tidak membuktikan kelengkapan bursa. Kapasitas I/O, interpretasi timestamp/side, serta penyebab transaksi tidak ditemukan belum terverifikasi. Net aggression bukan bukti akumulasi/distribusi atau arus dana bersih.

Cache deduplikasi tidak memangkas hitungan kumulatif; eviction hanya dapat membuat transaksi lama dihitung baru lagi bila dikirim ulang. Tidak menyimpulkan selisih berasal dari cache tanpa pembuktian.