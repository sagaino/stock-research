# Laporan Paper Backtest Scout & Sniper (Trade Log, TP & CL)
**Session ID**: `fc73b5a60f91441aaaf9f294964ed64a` | **Symbol**: `*` | **Rentang Sesi**: 2026-09-10T07:06:29.874+00:00 s.d. 2026-09-10T07:07:04.369+00:00
**Konfigurasi Sniper**: Kapasitas `5 Slot` | Target TP `+3.0%` | Stop Loss `-1.5%` | Max Hold `130s` | Observasi `10s`
**Order Book Strategy**: mode `legacy` — target persentase + tape-reading dinamis.
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
| **Dibatalkan Pra-Entry (ABORTED)**| **1** | Momentum padam dalam 10s (nol risiko modal) |
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
*Daftar sinyal radar yang tidak memenuhi konfirmasi follow-through HAKA sehingga otomatis dibatalkan dalam 10 detik tanpa risiko modal:*

| Waktu Radar (WIB) | Saham | Pola Radar | Harga Ref | Durasi Observasi | Alasan Pembatalan |
|---|:---:|---|:---:|:---:|---|
| 14:06:35 | **KOTA** | `BREAKOUT_MOMENTUM` | 210 | 10s | Timeout 10s: Momentum padam. Abort! |

---

## 5. Batasan dan Hipotesis Riset Berikutnya

- Hasil hanya berlaku pada sesi dan konfigurasi di atas; uji pada hari lain tanpa mengubah parameter sebelum menyimpulkan ada edge.
- Slippage adverse dan fee sudah dihitung, tetapi antrean, partial fill, market impact, reject, serta latency belum dimodelkan.
- Filter harga, velocity, follow-through HAKA, holding time, dan pengecualian big-cap masih merupakan hipotesis yang perlu diuji out-of-sample.
- Gunakan sesi wildcard untuk screening; konfirmasi mikrostruktur dan kelengkapan transaksi sebaiknya memakai feed dedicated per saham.