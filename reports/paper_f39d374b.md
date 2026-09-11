# Laporan Paper Backtest Scout & Sniper (Trade Log, TP & CL)
**Session ID**: `f39d374ba0e044b58cb8e126dd5c4971` | **Symbol**: `*` | **Rentang Sesi**: 2026-09-07T07:45:44.821+00:00 s.d. 2026-09-07T08:51:48.398+00:00
**Konfigurasi Sniper**: Kapasitas `5 Slot` | Target TP `+3.0%` | Stop Loss `-1.5%` | Max Hold `130s` | Observasi `10s`
**Paper Frictions**: Modal per posisi `Rp 550,000` | Fee Beli `0.15%` | Fee Jual `0.25%` | Slippage adverse `1 tick/sisi`
**Peringatan**: ini simulasi sinyal, bukan order broker. Antrean, partial fill, market impact, reject, dan latency belum dimodelkan.

---

## 1. Papan Skor Kinerja & Return Finansial (Financial Scoreboard)

| Metrik Evaluasi Finansial | Nilai Kinerja | Keterangan |
|---|:---:|---|
| **Status Paper Backtest** | **PAPER LOSS 🔴** | Sesudah fee dan asumsi slippage; belum membuktikan fill nyata |
| **Estimasi Net Paper Return** | **Rp -11,048** | Estimasi simulasi, bukan saldo akun trading |
| **Laba Kotor (Gross Profit/Loss)**| Rp -6,600 | Akumulasi selisih harga jual dikurangi harga beli |
| **Total Biaya Broker (Fees Paid)**| Rp 4,448 | Beban komisi transaksi beli & jual |
| **Total Modal Ditransaksikan**    | Rp 1,116,200 | Akumulasi perputaran modal dari 2 kali transaksi |
| **Win Rate Paper (sesudah biaya)**| **50.0%** | Posisi net positif dibanding posisi net negatif |
| **Posisi Net Positif**            | **1** (50.0%) | Setelah fee dan slippage asumsi |
| **Posisi Net Negatif**            | **1** (50.0%) | Setelah fee dan slippage asumsi |
| **Stagnant Exit (Timeout)**       | **0** (0.0%) | Posisi mandek dilepas pada 130s |
| **Dibatalkan Pra-Entry (ABORTED)**| **1** | Momentum padam dalam 10s (nol risiko modal) |
| **Rata-rata Net Return Positif**  | **+0.06%** | Sudah memperhitungkan fee dan slippage asumsi |
| **Rata-rata Net Return Negatif**  | **-2.06%** | Sudah memperhitungkan fee dan slippage asumsi |
| **Akumulasi Net Paper Return (%)**| **-2.00%** | Penjumlahan return tiap posisi, bukan return portofolio majemuk |

---

## 2. Rangkuman Hasil per Kode Saham (P&L dan Biaya Broker)

| Saham | Masuk | TP | CL | Timeout | Gross PnL (Rp) | Fee Broker (Rp) | Net Return (Rp) | Akumulasi PnL (%) | Status / Perilaku |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **EKAD** | 1 | 1 | 0 | 0 | +Rp 2,600 | Rp 2,263 | **+Rp 337** | **+0.06%** | Juara Momentum 🚀 |
| **MDIA** | 1 | 0 | 1 | 0 | Rp -9,200 | Rp 2,185 | **Rp -11,385** | **-2.06%** | High Volatility / Choppy ⚠️ |

---

## 3. Log Rinci Seluruh Posisi Yang Masuk (Trade Log)

| Waktu (WIB) | Saham | Pola Radar | Lot | Modal Beli | Beli | Jual | TP | CL | Fee (Rp) | Net Return (Rp) | PnL (%) | Durasi | Hasil | Catatan Alasan |
|---|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| 14:49:02 | **EKAD** | `BREAKOUT_MOMENTUM` | 13 | Rp 564,200 | 434 | 436 | 450 | 438 | Rp 2,263 | **+Rp 337** | **+0.1%** | 13s | `TAKE_PROFIT` | Trailing Stop HIT @ 438 (+1.4%)! Mengamankan profit. |
| 15:34:56 | **MDIA** | `BREAKOUT_MOMENTUM` | 23 | Rp 552,000 | 240 | 236 | 250 | 240 | Rp 2,185 | **Rp -11,385** | **-2.1%** | 0s | `CUT_LOSS` | CL HIT @ 238 (0.0%)! Batas invalidasi jebol. |

---

## 4. Log Kandidat yang Dibatalkan Pra-Entry (Aborted Log)
*Daftar sinyal radar yang tidak memenuhi konfirmasi follow-through HAKA sehingga otomatis dibatalkan dalam 10 detik tanpa risiko modal:*

| Waktu Radar (WIB) | Saham | Pola Radar | Harga Ref | Durasi Observasi | Alasan Pembatalan |
|---|:---:|---|:---:|:---:|---|
| 15:34:44 | **IMPC** | `BREAKOUT_MOMENTUM` | 1565 | 4s | Tape hening 2.8s > 2.5s. Abort! |

---

## 5. Batasan dan Hipotesis Riset Berikutnya

- Hasil hanya berlaku pada sesi dan konfigurasi di atas; uji pada hari lain tanpa mengubah parameter sebelum menyimpulkan ada edge.
- Slippage adverse dan fee sudah dihitung, tetapi antrean, partial fill, market impact, reject, serta latency belum dimodelkan.
- Filter harga, velocity, follow-through HAKA, holding time, dan pengecualian big-cap masih merupakan hipotesis yang perlu diuji out-of-sample.
- Gunakan sesi wildcard untuk screening; konfirmasi mikrostruktur dan kelengkapan transaksi sebaiknya memakai feed dedicated per saham.