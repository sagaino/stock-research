# Laporan Paper Backtest Scout & Sniper (Trade Log, TP & CL)
**Session ID**: `9410d22dad804563af76a91374bc9e81` | **Symbol**: `*` | **Rentang Sesi**: 2026-09-10T03:39:04.700+00:00 s.d. 2026-09-10T05:00:20.570+00:00
**Konfigurasi Sniper**: Kapasitas `5 Slot` | Target TP `+3.0%` | Stop Loss `-1.5%` | Max Hold `130s` | Observasi `10s`
**Order Book Strategy**: mode `legacy` — target persentase + tape-reading dinamis.
**Paper Frictions**: Modal per posisi `Rp 550,000` | Fee Beli `0.15%` | Fee Jual `0.25%` | Slippage adverse `1 tick/sisi`
**Peringatan**: ini simulasi sinyal, bukan order broker. Antrean, partial fill, market impact, reject, dan latency belum dimodelkan.

---

## 1. Papan Skor Kinerja & Return Finansial (Financial Scoreboard)

| Metrik Evaluasi Finansial | Nilai Kinerja | Keterangan |
|---|:---:|---|
| **Status Paper Backtest** | **PAPER PROFIT 🟢** | Sesudah fee dan asumsi slippage; belum membuktikan fill nyata |
| **Estimasi Net Paper Return** | **+Rp 8,036** | Estimasi simulasi, bukan saldo akun trading |
| **Laba Kotor (Gross Profit/Loss)**| +Rp 12,500 | Akumulasi selisih harga jual dikurangi harga beli |
| **Total Biaya Broker (Fees Paid)**| Rp 4,464 | Beban komisi transaksi beli & jual |
| **Total Modal Ditransaksikan**    | Rp 1,108,100 | Akumulasi perputaran modal dari 2 kali transaksi |
| **Win Rate Paper (sesudah biaya)**| **50.0%** | Posisi net positif dibanding posisi net negatif |
| **Posisi Net Positif**            | **1** (50.0%) | Setelah fee dan slippage asumsi |
| **Posisi Net Negatif**            | **1** (50.0%) | Setelah fee dan slippage asumsi |
| **Stagnant Exit (Timeout)**       | **0** (0.0%) | Posisi mandek dilepas pada 130s |
| **Dibatalkan Pra-Entry (ABORTED)**| **18** | Momentum padam dalam 10s (nol risiko modal) |
| **Rata-rata Net Return Positif**  | **+3.07%** | Sudah memperhitungkan fee dan slippage asumsi |
| **Rata-rata Net Return Negatif**  | **-1.60%** | Sudah memperhitungkan fee dan slippage asumsi |
| **Akumulasi Net Paper Return (%)**| **+1.47%** | Penjumlahan return tiap posisi, bukan return portofolio majemuk |

---

## 2. Rangkuman Hasil per Kode Saham (P&L dan Biaya Broker)

| Saham | Masuk | TP | CL | Timeout | Gross PnL (Rp) | Fee Broker (Rp) | Net Return (Rp) | Akumulasi PnL (%) | Status / Perilaku |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **KIOS** | 1 | 1 | 0 | 0 | +Rp 19,200 | Rp 2,256 | **+Rp 16,944** | **+3.07%** | Juara Momentum 🚀 |
| **KPIG** | 1 | 0 | 1 | 0 | Rp -6,700 | Rp 2,208 | **Rp -8,908** | **-1.60%** | High Volatility / Choppy ⚠️ |

---

## 3. Log Rinci Seluruh Posisi Yang Masuk (Trade Log)

| Waktu (WIB) | Saham | Pola Radar | Lot | Modal Beli | Beli | Jual | TP | CL | Fee (Rp) | Net Return (Rp) | PnL (%) | Durasi | Hasil | Catatan Alasan |
|---|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| 11:13:19 | **KPIG** | `BREAKOUT_MOMENTUM` | 67 | Rp 556,100 | 83 | 82 | 87 | 81 | Rp 2,208 | **Rp -8,908** | **-1.6%** | 30s | `TAKE_PROFIT` | Dynamic TP: Offer Wall ['89 (+63,392L, 2x refill)', '85 (+44,698L, 2x refill)'] di-refill berulang -> HAKI @ 83 (+1.2%) |
| 11:59:01 | **KIOS** | `BREAKOUT_MOMENTUM` | 48 | Rp 552,000 | 115 | 119 | 120 | 117 | Rp 2,256 | **+Rp 16,944** | **+3.1%** | 1s | `TAKE_PROFIT` | TP HIT @ 120 (+5.3%)! Mengamankan profit. |

---

## 4. Log Kandidat yang Dibatalkan Pra-Entry (Aborted Log)
*Daftar sinyal radar yang tidak memenuhi konfirmasi follow-through HAKA sehingga otomatis dibatalkan dalam 10 detik tanpa risiko modal:*

| Waktu Radar (WIB) | Saham | Pola Radar | Harga Ref | Durasi Observasi | Alasan Pembatalan |
|---|:---:|---|:---:|:---:|---|
| 10:40:47 | **KPIG** | `BREAKOUT_MOMENTUM` | 78 | 5s | Tape hening 2.5s > 2.5s. Abort! |
| 10:46:48 | **KPIG** | `BREAKOUT_MOMENTUM` | 80 | 10s | Timeout 10s: Momentum padam. Abort! |
| 10:49:35 | **KPIG** | `BREAKOUT_MOMENTUM` | 83 | 10s | Timeout 10s: Momentum padam. Abort! |
| 10:57:03 | **JARR** | `BREAKOUT_MOMENTUM` | 3480 | 6s | Tape hening 2.5s > 2.5s. Abort! |
| 10:57:38 | **CUAN** | `BREAKOUT_MOMENTUM` | 1020 | 5s | Tape hening 5.1s > 2.5s. Abort! |
| 10:59:24 | **JARR** | `BREAKOUT_MOMENTUM` | 3580 | 3s | Tape hening 2.6s > 2.5s. Abort! |
| 11:05:43 | **JARR** | `BREAKOUT_MOMENTUM` | 3710 | 8s | Tape hening 7.6s > 2.5s. Abort! |
| 11:08:21 | **FAST** | `BREAKOUT_MOMENTUM` | 470 | 8s | Tape hening 6.6s > 2.5s. Abort! |
| 11:10:45 | **ASLI** | `BREAKOUT_MOMENTUM` | 432 | 10s | Tape hening 3.0s > 2.5s. Abort! |
| 11:15:21 | **JARR** | `BREAKOUT_MOMENTUM` | 3860 | 8s | Tape hening 2.9s > 2.5s. Abort! |
| 11:15:25 | **TEBE** | `BREAKOUT_MOMENTUM` | 1925 | 10s | Timeout 10s: Momentum padam. Abort! |
| 11:19:00 | **KPIG** | `BREAKOUT_MOMENTUM` | 84 | 4s | Tape hening 3.4s > 2.5s. Abort! |
| 11:22:20 | **KPIG** | `BREAKOUT_MOMENTUM` | 86 | 10s | Timeout 10s: Momentum padam. Abort! |
| 11:23:23 | **JARR** | `BREAKOUT_MOMENTUM` | 3900 | 10s | Timeout 10s: Momentum padam. Abort! |
| 11:23:54 | **KPIG** | `BREAKOUT_MOMENTUM` | 87 | 10s | Timeout 10s: Momentum padam. Abort! |
| 11:35:10 | **JARR** | `BREAKOUT_MOMENTUM` | 3850 | 5s | Tape hening 3.3s > 2.5s. Abort! |
| 11:41:28 | **FAST** | `BREAKOUT_MOMENTUM` | 490 | 10s | Timeout 10s: Momentum padam. Abort! |
| 11:59:02 | **KPIG** | `BREAKOUT_MOMENTUM` | 86 | 10s | Timeout 10s: Momentum padam. Abort! |

---

## 5. Batasan dan Hipotesis Riset Berikutnya

- Hasil hanya berlaku pada sesi dan konfigurasi di atas; uji pada hari lain tanpa mengubah parameter sebelum menyimpulkan ada edge.
- Slippage adverse dan fee sudah dihitung, tetapi antrean, partial fill, market impact, reject, serta latency belum dimodelkan.
- Filter harga, velocity, follow-through HAKA, holding time, dan pengecualian big-cap masih merupakan hipotesis yang perlu diuji out-of-sample.
- Gunakan sesi wildcard untuk screening; konfirmasi mikrostruktur dan kelengkapan transaksi sebaiknya memakai feed dedicated per saham.