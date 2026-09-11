# Laporan Paper Backtest Scout & Sniper (Trade Log, TP & CL)
**Session ID**: `a93bc2ea17204456adfc473436394b3d` | **Symbol**: `*` | **Rentang Sesi**: 2026-09-10T07:07:06.425+00:00 s.d. 2026-09-10T07:47:59.763+00:00
**Konfigurasi Sniper**: Kapasitas `5 Slot` | Target TP `Order Book` | Stop Loss `Support wall` | Max Hold `130s` | Watchlist idle 300s
**Order Book Strategy**: mode `full` — Watchlist Pullback: bid absorb/refill 2x + 2 HAKA dekat support; TP/CL memakai wall.
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
| **Dilepas dari Watchlist Pra-Entry**| **2** | Idle, support jebol, atau diganti Radar baru (nol risiko modal) |
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

## 4. Log Kandidat Pra-Entry yang Dilepas
*Daftar kandidat tanpa posisi terbuka; tidak ada risiko modal:*

| Waktu Radar (WIB) | Saham | Pola Radar | Harga Ref | Durasi Watchlist | Alasan Pelepasan |
|---|:---:|---|:---:|:---:|---|
| 14:23:47 | **KPIG** | `BREAKOUT_MOMENTUM` | 84 | 958s | Sepi 5 menit tanpa DONE |
| 14:08:57 | **BIPI** | `BREAKOUT_MOMENTUM` | 157 | 1848s | Sepi 5 menit tanpa DONE |

---

## 5. Batasan dan Hipotesis Riset Berikutnya

- Hasil hanya berlaku pada sesi dan konfigurasi di atas; uji pada hari lain tanpa mengubah parameter sebelum menyimpulkan ada edge.
- Slippage adverse dan fee sudah dihitung, tetapi antrean, partial fill, market impact, reject, serta latency belum dimodelkan.
- Filter harga, velocity, follow-through HAKA, holding time, dan pengecualian big-cap masih merupakan hipotesis yang perlu diuji out-of-sample.
- Gunakan sesi wildcard untuk screening; konfirmasi mikrostruktur dan kelengkapan transaksi sebaiknya memakai feed dedicated per saham.