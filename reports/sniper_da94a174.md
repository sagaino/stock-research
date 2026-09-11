# Laporan Paper Backtest Scout & Sniper (Trade Log, TP & CL)
**Session ID**: `da94a1743d464e7097f12f41a04a56ff` | **Symbol**: `*` | **Rentang Sesi**: 2026-09-09T06:31:33.288+00:00 s.d. 2026-09-09T08:50:06.715+00:00
**Konfigurasi Sniper**: Kapasitas `5 Slot` | Target TP `+3.0%` | Stop Loss `-1.5%` | Max Hold `130s` | Observasi `10s`
**Paper Frictions**: Modal per posisi `Rp 550,000` | Fee Beli `0.15%` | Fee Jual `0.25%` | Slippage adverse `1 tick/sisi`
**Peringatan**: ini simulasi sinyal, bukan order broker. Antrean, partial fill, market impact, reject, dan latency belum dimodelkan.

---

## 1. Papan Skor Kinerja & Return Finansial (Financial Scoreboard)

| Metrik Evaluasi Finansial | Nilai Kinerja | Keterangan |
|---|:---:|---|
| **Status Paper Backtest** | **PAPER FLAT ⚪** | Sesudah fee dan asumsi slippage; belum membuktikan fill nyata |
| **Estimasi Net Paper Return** | **+Rp 0** | Estimasi simulasi, bukan saldo akun trading |
| **Laba Kotor (Gross Profit/Loss)**| +Rp 0 | Akumulasi selisih harga jual dikurangi harga beli |
| **Total Biaya Broker (Fees Paid)**| Rp 0 | Beban komisi transaksi beli & jual |
| **Total Modal Ditransaksikan**    | Rp 0 | Akumulasi perputaran modal dari 0 kali transaksi |
| **Win Rate Paper (sesudah biaya)**| **0.0%** | Posisi net positif dibanding posisi net negatif |
| **Posisi Net Positif**            | **0** (0.0%) | Setelah fee dan slippage asumsi |
| **Posisi Net Negatif**            | **0** (0.0%) | Setelah fee dan slippage asumsi |
| **Stagnant Exit (Timeout)**       | **0** (0.0%) | Posisi mandek dilepas pada 130s |
| **Dibatalkan Pra-Entry (ABORTED)**| **17** | Momentum padam dalam 10s (nol risiko modal) |
| **Rata-rata Net Return Positif**  | **+0.00%** | Sudah memperhitungkan fee dan slippage asumsi |
| **Rata-rata Net Return Negatif**  | **0.00%** | Sudah memperhitungkan fee dan slippage asumsi |
| **Akumulasi Net Paper Return (%)**| **+0.00%** | Penjumlahan return tiap posisi, bukan return portofolio majemuk |

---

## 2. Rangkuman Hasil per Kode Saham (P&L dan Biaya Broker)

| Saham | Masuk | TP | CL | Timeout | Gross PnL (Rp) | Fee Broker (Rp) | Net Return (Rp) | Akumulasi PnL (%) | Status / Perilaku |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|

---

## 3. Log Rinci Seluruh Posisi Yang Masuk (Trade Log)

| Waktu (WIB) | Saham | Pola Radar | Lot | Modal Beli | Beli | Jual | TP | CL | Fee (Rp) | Net Return (Rp) | PnL (%) | Durasi | Hasil | Catatan Alasan |
|---|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|

---

## 4. Log Kandidat yang Dibatalkan Pra-Entry (Aborted Log)
*Daftar sinyal radar yang tidak memenuhi konfirmasi follow-through HAKA sehingga otomatis dibatalkan dalam 10 detik tanpa risiko modal:*

| Waktu Radar (WIB) | Saham | Pola Radar | Harga Ref | Durasi Observasi | Alasan Pembatalan |
|---|:---:|---|:---:|:---:|---|
| 13:32:25 | **ARCI** | `BREAKOUT_MOMENTUM` | 1340 | 9s | Tape hening 4.1s > 2.5s. Abort! |
| 13:37:34 | **DMAS** | `BREAKOUT_MOMENTUM` | 206 | 3s | Tape hening 2.9s > 2.5s. Abort! |
| 13:41:05 | **KOTA** | `BREAKOUT_MOMENTUM` | 210 | 10s | Timeout 10s: Momentum padam. Abort! |
| 13:46:08 | **NCKL** | `BREAKOUT_MOMENTUM` | 1000 | 8s | Tape hening 5.6s > 2.5s. Abort! |
| 13:54:06 | **DPUM** | `BREAKOUT_MOMENTUM` | 139 | 10s | Timeout 10s: Momentum padam. Abort! |
| 14:06:05 | **ERAA** | `BREAKOUT_MOMENTUM` | 615 | 4s | Tape hening 3.2s > 2.5s. Abort! |
| 14:07:11 | **KOKA** | `BREAKOUT_MOMENTUM` | 200 | 10s | Timeout 10s: Momentum padam. Abort! |
| 14:15:58 | **KOTA** | `BREAKOUT_MOMENTUM` | 212 | 10s | Timeout 10s: Momentum padam. Abort! |
| 14:18:49 | **NICL** | `BREAKOUT_MOMENTUM` | 505 | 10s | Timeout 10s: Momentum padam. Abort! |
| 14:26:31 | **SQMI** | `BREAKOUT_MOMENTUM` | 110 | 10s | Timeout 10s: Momentum padam. Abort! |
| 14:38:18 | **IMPC** | `BREAKOUT_MOMENTUM` | 1765 | 7s | Tape hening 2.7s > 2.5s. Abort! |
| 14:55:41 | **NIKL** | `BREAKOUT_MOMENTUM` | 240 | 5s | Tape hening 4.8s > 2.5s. Abort! |
| 15:00:56 | **SUPA** | `BREAKOUT_MOMENTUM` | 520 | 10s | Timeout 10s: Momentum padam. Abort! |
| 15:09:08 | **KOKA** | `BREAKOUT_MOMENTUM` | 206 | 10s | Timeout 10s: Momentum padam. Abort! |
| 15:24:56 | **ESTI** | `BREAKOUT_MOMENTUM` | 194 | 10s | Timeout 10s: Momentum padam. Abort! |
| 15:26:56 | **ESTI** | `BREAKOUT_MOMENTUM` | 202 | 10s | Timeout 10s: Momentum padam. Abort! |
| 15:29:50 | **ERAA** | `BREAKOUT_MOMENTUM` | 610 | 10s | Timeout 10s: Momentum padam. Abort! |

---

## 5. Batasan dan Hipotesis Riset Berikutnya

- Hasil hanya berlaku pada sesi dan konfigurasi di atas; uji pada hari lain tanpa mengubah parameter sebelum menyimpulkan ada edge.
- Slippage adverse dan fee sudah dihitung, tetapi antrean, partial fill, market impact, reject, serta latency belum dimodelkan.
- Filter harga, velocity, follow-through HAKA, holding time, dan pengecualian big-cap masih merupakan hipotesis yang perlu diuji out-of-sample.
- Gunakan sesi wildcard untuk screening; konfirmasi mikrostruktur dan kelengkapan transaksi sebaiknya memakai feed dedicated per saham.