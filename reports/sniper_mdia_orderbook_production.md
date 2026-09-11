# Laporan Hasil Eksekusi Taktis Scout & Sniper (Trade Log, TP & CL)
**Session ID**: `6acf24a3e3794e808f559679fb85a915` | **Symbol**: `MDIA` | **Rentang Sesi**: 2026-09-07T08:36:04.843+00:00 s.d. 2026-09-07T08:51:50.280+00:00
**Konfigurasi Sniper**: Kapasitas `1 Slot` | Target TP `+3.0%` | Stop Loss `-1.5%` | Max Hold `180s` | Observasi `10s`
**Simulasi Frictions**: Modal per Trade `Rp 550,000` | Fee Beli `0.15%` | Fee Jual `0.25%` (Round-trip ~0.40%)

---

## 1. Papan Skor Kinerja & Return Finansial (Financial Scoreboard)

| Metrik Evaluasi Finansial | Nilai Kinerja | Keterangan |
|---|:---:|---|
| **Status Hasil Akhir** | **PROFIT BERSIH 🟢** | Setelah dikurangi seluruh biaya broker (Buy 0.15% + Sell 0.25%) |
| **Laba Bersih (Net Profit/Loss)** | **+Rp 11,767** | **Profit bersih final masuk ke akun trading** |
| **Laba Kotor (Gross Profit/Loss)**| +Rp 18,400 | Akumulasi selisih harga jual dikurangi harga beli |
| **Total Biaya Broker (Fees Paid)**| Rp 6,633 | Beban komisi transaksi beli & jual |
| **Total Modal Ditransaksikan**    | Rp 1,646,800 | Akumulasi perputaran modal dari 3 kali transaksi |
| **Win Rate (TP vs CL)**           | **100.0%** | Rasio kemenangan posisi yang terdeterminasi |
| **Take-Profit (TP Hit)**          | **3** (100.0%) | Target profit tercapai (+3.0% s/d +4.0%) |
| **Cut-Loss (CL Hit)**             | **0** (0.0%) | Batas invalidasi tertembus (disiplin cut-loss) |
| **Stagnant Exit (Timeout)**       | **0** (0.0%) | Posisi mandek dilepas pada 180s |
| **Dibatalkan Pra-Entry (ABORTED)**| **0** | Momentum padam dalam 10s (nol risiko modal) |
| **Rata-rata Profit (Avg Win)**    | **+1.12%** | Rata-rata persentase gain posisi TP |
| **Rata-rata Rugi (Avg Loss)**     | **0.00%** | Rata-rata persentase loss posisi CL |
| **Akumulasi Net PnL (%)**         | **+3.36%** | Total persentase PnL seluruh posisi masuk |

---

## 2. Rangkuman Hasil per Kode Saham (P&L dan Biaya Broker)

| Saham | Masuk | TP | CL | Timeout | Gross PnL (Rp) | Fee Broker (Rp) | Net Return (Rp) | Akumulasi PnL (%) | Status / Perilaku |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **MDIA** | 3 | 3 | 0 | 0 | +Rp 18,400 | Rp 6,633 | **+Rp 11,767** | **+3.36%** | Juara Momentum 🚀 |

---

## 3. Log Rinci Seluruh Posisi Yang Masuk (Trade Log)

| Waktu (WIB) | Saham | Pola Radar | Lot | Modal Beli | Beli | Jual | TP | CL | Fee (Rp) | Net Return (Rp) | PnL (%) | Durasi | Hasil | Catatan Alasan |
|---|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| 15:36:57 | **MDIA** | `BREAKOUT_MOMENTUM` | 23 | Rp 542,800 | 236 | 240 | 243 | 232 | Rp 2,194 | **+Rp 7,006** | **+1.7%** | 74s | `TAKE_PROFIT` | Dynamic TP: Offer Wall [242.0] di-refill masif -> HAKI @ 240 (+1.7%) |
| 15:39:48 | **MDIA** | `BREAKOUT_MOMENTUM` | 23 | Rp 547,400 | 238 | 240 | 245 | 234 | Rp 2,201 | **+Rp 2,399** | **+0.8%** | 354s | `TAKE_PROFIT` | Dynamic TP: Offer Wall [242.0] di-refill masif -> HAKI @ 240 (+0.8%) |
| 15:48:42 | **MDIA** | `BREAKOUT_MOMENTUM` | 23 | Rp 556,600 | 242 | 244 | 249 | 238 | Rp 2,238 | **+Rp 2,362** | **+0.8%** | 33s | `TAKE_PROFIT` | Dynamic TP: Offer Wall [246.0] di-refill masif -> HAKI @ 244 (+0.8%) |

---

## 4. Log Kandidat yang Dibatalkan Pra-Entry (Aborted Log)
*Daftar sinyal radar yang tidak memenuhi konfirmasi follow-through HAKA sehingga otomatis dibatalkan dalam 10 detik tanpa risiko modal:*

| Waktu Radar (WIB) | Saham | Pola Radar | Harga Ref | Durasi Observasi | Alasan Pembatalan |
|---|:---:|---|:---:|:---:|---|

---

## 5. Analisis & Kesimpulan Praktis Peningkatan Return

1. **Eliminasi Saham Big Caps Menghentikan Kebocoran Fee (Fee Drag)**:
   - Saham berkapitalisasi besar (BBCA, BBRI, BMRI, ASII, TLKM, BUMI, dll.) cenderung lambat bergerak dan jarang mencapai +3% dalam 2-3 menit. Mengeluarkannya dari radar sniper secara drastis memangkas biaya broker sia-sia pada posisi stagnan.
2. **Fokus Pola Breakout Momentum Murni & Velocity Tinggi (>= 50 tr/5s)**:
   - Menaikkan ambang kecepatan transaksi ke >= 50 tr/5s menyaring saham setengah-matang dan hanya mengeksekusi momentum agresif riil. Ini memangkas transaksi mandek dan menghemat biaya broker.
3. **Filter Akumulasi Follow-Through Volume (>= 100 Lot HAKA)**:
   - Sinyal radar yang hanya dimakan 1-5 lot retail otomatis gugur di detik ke-10 (Aborted) dengan Rp 0 biaya broker, mengeliminasi false breakout sebelum masuk market.
4. **Blacklist Pasca Cut-Loss Mencegah Revenge Trading**:
   - Jika suatu saham menembus stop loss, saham tersebut langsung diblokir selama 30 menit untuk mencegah kerugian berulang pada saham yang sedang mengalami tekanan jual institusi.
5. **Optimalisasi Window Menahan Posisi (130 Detik)**:
   - Window 130 detik memberikan nafas yang cukup bagi saham pemenang untuk memicu target TP +3.0% s/d +3.6% sekaligus melepas modal secara disiplin jika saham terbukti sideways, membebaskan slot lebih cepat untuk momentum berikutnya.
6. **Filter Ambang Batas Harga Saham (Price Floor >= Rp 200)**:
   - Saham di bawah Rp 200 berada pada Fraksi 1 (tick size Rp 1), di mana penurunan 2 tick saja sudah setara -1.5% s/d -2.0% yang langsung menjebol stop loss akibat noise antrean bid.
   - Memfilter saham >= Rp 200 (fraksi Rp 2 ke atas) mengeliminasi 'penny-stock whipsaws' dan kebocoran fee pada saham murah yang stagnan (seperti IATA, KOCI, IKAN), mendongkrak profit bersih ke rekor tertinggi.