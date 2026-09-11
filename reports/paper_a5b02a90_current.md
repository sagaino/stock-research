# Laporan Paper Backtest Scout & Sniper (Trade Log, TP & CL)
**Session ID**: `a5b02a9097084d7cad2f7d58eddfc90b` | **Symbol**: `*` | **Rentang Sesi**: 2026-09-08T06:41:30.946+00:00 s.d. 2026-09-08T07:09:41.042+00:00
**Konfigurasi Sniper**: Kapasitas `5 Slot` | Target TP `+3.0%` | Stop Loss `-1.5%` | Max Hold `130s` | Observasi `10s`
**Paper Frictions**: Modal per posisi `Rp 550,000` | Fee Beli `0.15%` | Fee Jual `0.25%` | Slippage adverse `1 tick/sisi`
**Peringatan**: ini simulasi sinyal, bukan order broker. Antrean, partial fill, market impact, reject, dan latency belum dimodelkan.

---

## 1. Papan Skor Kinerja & Return Finansial (Financial Scoreboard)

| Metrik Evaluasi Finansial | Nilai Kinerja | Keterangan |
|---|:---:|---|
| **Status Paper Backtest** | **PAPER LOSS 🔴** | Sesudah fee dan asumsi slippage; belum membuktikan fill nyata |
| **Estimasi Net Paper Return** | **Rp -17,222** | Estimasi simulasi, bukan saldo akun trading |
| **Laba Kotor (Gross Profit/Loss)**| Rp -15,000 | Akumulasi selisih harga jual dikurangi harga beli |
| **Total Biaya Broker (Fees Paid)**| Rp 2,222 | Beban komisi transaksi beli & jual |
| **Total Modal Ditransaksikan**    | Rp 565,000 | Akumulasi perputaran modal dari 1 kali transaksi |
| **Win Rate Paper (sesudah biaya)**| **0.0%** | Posisi net positif dibanding posisi net negatif |
| **Posisi Net Positif**            | **0** (0.0%) | Setelah fee dan slippage asumsi |
| **Posisi Net Negatif**            | **1** (100.0%) | Setelah fee dan slippage asumsi |
| **Stagnant Exit (Timeout)**       | **0** (0.0%) | Posisi mandek dilepas pada 130s |
| **Dibatalkan Pra-Entry (ABORTED)**| **4** | Momentum padam dalam 10s (nol risiko modal) |
| **Rata-rata Net Return Positif**  | **+0.00%** | Sudah memperhitungkan fee dan slippage asumsi |
| **Rata-rata Net Return Negatif**  | **-3.05%** | Sudah memperhitungkan fee dan slippage asumsi |
| **Akumulasi Net Paper Return (%)**| **-3.05%** | Penjumlahan return tiap posisi, bukan return portofolio majemuk |

---

## 2. Rangkuman Hasil per Kode Saham (P&L dan Biaya Broker)

| Saham | Masuk | TP | CL | Timeout | Gross PnL (Rp) | Fee Broker (Rp) | Net Return (Rp) | Akumulasi PnL (%) | Status / Perilaku |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **PIPA** | 1 | 0 | 1 | 0 | Rp -15,000 | Rp 2,222 | **Rp -17,222** | **-3.05%** | High Volatility / Choppy ⚠️ |

---

## 3. Log Rinci Seluruh Posisi Yang Masuk (Trade Log)

| Waktu (WIB) | Saham | Pola Radar | Lot | Modal Beli | Beli | Jual | TP | CL | Fee (Rp) | Net Return (Rp) | PnL (%) | Durasi | Hasil | Catatan Alasan |
|---|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| 13:47:35 | **PIPA** | `BREAKOUT_MOMENTUM` | 25 | Rp 565,000 | 226 | 220 | 236 | 226 | Rp 2,222 | **Rp -17,222** | **-3.0%** | 0s | `CUT_LOSS` | CL HIT @ 222 (-0.9%)! Batas invalidasi jebol. |

---

## 4. Log Kandidat yang Dibatalkan Pra-Entry (Aborted Log)
*Daftar sinyal radar yang tidak memenuhi konfirmasi follow-through HAKA sehingga otomatis dibatalkan dalam 10 detik tanpa risiko modal:*

| Waktu Radar (WIB) | Saham | Pola Radar | Harga Ref | Durasi Observasi | Alasan Pembatalan |
|---|:---:|---|:---:|:---:|---|
| 13:44:00 | **PIPA** | `BREAKOUT_MOMENTUM` | 220 | 10s | Timeout 10s: Momentum padam. Abort! |
| 13:46:20 | **PIPA** | `BREAKOUT_MOMENTUM` | 218 | 10s | Timeout 10s: Momentum padam. Abort! |
| 13:54:03 | **FILM** | `BREAKOUT_MOMENTUM` | 950 | 6s | Tape hening 5.3s > 2.5s. Abort! |
| 14:03:27 | **FILM** | `BREAKOUT_MOMENTUM` | 955 | 6s | Tape hening 2.8s > 2.5s. Abort! |

---

## 5. Batasan dan Hipotesis Riset Berikutnya

- Hasil hanya berlaku pada sesi dan konfigurasi di atas; uji pada hari lain tanpa mengubah parameter sebelum menyimpulkan ada edge.
- Slippage adverse dan fee sudah dihitung, tetapi antrean, partial fill, market impact, reject, serta latency belum dimodelkan.
- Filter harga, velocity, follow-through HAKA, holding time, dan pengecualian big-cap masih merupakan hipotesis yang perlu diuji out-of-sample.
- Gunakan sesi wildcard untuk screening; konfirmasi mikrostruktur dan kelengkapan transaksi sebaiknya memakai feed dedicated per saham.