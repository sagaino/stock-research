# Laporan Kualitas Rekaman & Analisis Deskriptif
**Session ID**: `eaf9a059184f4b0192aa4be7a2908209` | **Symbol**: `*` | **Status**: `STOPPED` | **Source**: `LIVE`
**Waktu**: 2026-09-07T03:25:51.603+00:00 s.d. 2026-09-07T05:00:14.224+00:00 (Durasi: 5662.7 detik)

## 1. Audit Transaksi Unik & Deduplikasi Database
- **Total Batch Done Diterima**: 53,534
- **Total Record Transaksi Mentah**: 366,759
- **Transaksi Memiliki Trade ID**: 366,759 (Unik: 366,759)
- **Transaksi Tanpa Trade ID**: 0 (Unik: 0)
- **Duplikat di Database**: 0 record
- **Total Transaksi Unik Sebenarnya**: **366,759**

## 3. Pengukuran Kemampuan & Throughput Recorder
- **Total Event Database**: 107,078 event
- **Throughput Rata-rata**: 18.91 event/detik (Median: 20 event/s)
- **Beban Puncak (Peak Throughput)**: **34 event/detik** (P95: 20 e/s, P99: 22 e/s)
- **Pasangan Event Bertimestamp Sama (dapat berasal dari satu pesan)**: 53,534 event (50.0%)
- **Jeda Terpanjang Antar-event**: 14388 ms
- **Evaluasi Kebutuhan Antrean & Batching**: `BELUM TERUKUR: durasi commit, backlog, dan event-loop lag tidak direkam; jumlah event bukan bukti kapasitas I/O.`

- Anomali sequence lokal: 0; elapsed mundur: 0
- Median/persentil event hanya bucket detik terisi; bukan kapasitas recorder.
## 4. Analisis Deskriptif Pasar & Mikrostruktur
- **Total Volume Transaksi**: 45,179,880 lot | **Nilai Total**: Rp1.982.748.850.600
- **Proporsi Agresi Transaksi**:
  - **HAKA (Buy Agresif)** : 176,545 trade (45.76%) | 21,214,483 lot | Rp907.261.283.600
  - **HAKI (Sell Agresif)**: 190,214 trade (54.24%) | 23,965,397 lot | Rp1.075.487.567.000
  - **Net Aggression Flow**: **Rp-168.226.283.400** (-2,750,914 lot)
- Volume/nilai memakai salinan pertama transaksi unik; fallback tanpa ID bersifat perkiraan.
- **Kecepatan teramati client**: bucket tetap dari waktu penerimaan, bukan waktu bursa; rata-rata/persentil hanya bucket terisi. Snapshot awal dapat menaikkan puncak.
  - Jendela 1 Detik : Maks 856 trade/s | Rata-rata 64.9 trade/s | P95 149 trade/s
  - Jendela 5 Detik : Maks 1266 trade/5s | Rata-rata 324.6 trade/5s | P95 594 trade/5s
  - Jendela 30 Detik: Maks 4187 trade/30s | Rata-rata 1940.5 trade/30s | P95 2917 trade/30s

## VERDICT: KONSISTENSI DATA & KELAYAKAN RISET SINYAL
**DESKRIPTIF TERSEDIA; KELENGKAPAN BELUM TERVERIFIKASI**

Pembandingan lintas feed belum dilakukan pada laporan ini.

Urutan lokal dan kesamaan nilai tidak membuktikan kelengkapan bursa. Kapasitas I/O, interpretasi timestamp/side, serta penyebab transaksi tidak ditemukan belum terverifikasi. Net aggression bukan bukti akumulasi/distribusi atau arus dana bersih.

Cache deduplikasi tidak memangkas hitungan kumulatif; eviction hanya dapat membuat transaksi lama dihitung baru lagi bila dikirim ulang. Tidak menyimpulkan selisih berasal dari cache tanpa pembuktian.