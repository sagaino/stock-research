# Laporan Hasil Eksekusi Taktis Scout & Sniper (Trade Log, TP & CL)
**Session ID**: `f39d374ba0e044b58cb8e126dd5c4971` | **Symbol**: `*` | **Rentang Sesi**: 2026-09-07T07:45:44.821+00:00 s.d. 2026-09-07T08:51:48.398+00:00
**Konfigurasi Sniper**: Kapasitas `5 Slot` | Target TP `+3.0%` | Stop Loss `-1.5%` | Max Hold `130s` | Observasi `10s`
**Simulasi Frictions**: Modal per Trade `Rp 550,000` | Fee Beli `0.15%` | Fee Jual `0.25%` (Round-trip ~0.40%)

---

## 1. Papan Skor Kinerja & Return Finansial (Financial Scoreboard)

| Metrik Evaluasi Finansial | Nilai Kinerja | Keterangan |
|---|:---:|---|
| **Status Hasil Akhir** | **PROFIT BERSIH 🟢** | Setelah dikurangi seluruh biaya broker (Buy 0.15% + Sell 0.25%) |
| **Laba Bersih (Net Profit/Loss)** | **+Rp 59,381** | **Profit bersih final masuk ke akun trading** |
| **Laba Kotor (Gross Profit/Loss)**| +Rp 106,200 | Akumulasi selisih harga jual dikurangi harga beli |
| **Total Biaya Broker (Fees Paid)**| Rp 46,819 | Beban komisi transaksi beli & jual |
| **Total Modal Ditransaksikan**    | Rp 11,638,400 | Akumulasi perputaran modal dari 21 kali transaksi |
| **Win Rate (TP vs CL)**           | **80.0%** | Rasio kemenangan posisi yang terdeterminasi |
| **Take-Profit (TP Hit)**          | **4** (19.0%) | Target profit tercapai (+3.0% s/d +4.0%) |
| **Cut-Loss (CL Hit)**             | **1** (4.8%) | Batas invalidasi tertembus (disiplin cut-loss) |
| **Stagnant Exit (Timeout)**       | **16** (76.2%) | Posisi mandek dilepas pada 130s |
| **Dibatalkan Pra-Entry (ABORTED)**| **6** | Momentum padam dalam 10s (nol risiko modal) |
| **Rata-rata Profit (Avg Win)**    | **+3.30%** | Rata-rata persentase gain posisi TP |
| **Rata-rata Rugi (Avg Loss)**     | **-1.49%** | Rata-rata persentase loss posisi CL |
| **Akumulasi Net PnL (%)**         | **+19.06%** | Total persentase PnL seluruh posisi masuk |

---

## 2. Rangkuman Hasil per Kode Saham (P&L dan Biaya Broker)

| Saham | Masuk | TP | CL | Timeout | Gross PnL (Rp) | Fee Broker (Rp) | Net Return (Rp) | Akumulasi PnL (%) | Status / Perilaku |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **MDIA** | 7 | 2 | 0 | 5 | +Rp 76,000 | Rp 15,576 | **+Rp 60,424** | **+13.78%** | Juara Momentum 🚀 |
| **EKAD** | 1 | 1 | 0 | 0 | +Rp 18,200 | Rp 2,282 | **+Rp 15,918** | **+3.26%** | Juara Momentum 🚀 |
| **KOTA** | 2 | 1 | 0 | 1 | +Rp 15,600 | Rp 4,383 | **+Rp 11,217** | **+2.86%** | Juara Momentum 🚀 |
| **INET** | 1 | 0 | 0 | 1 | +Rp 3,000 | Rp 2,144 | **+Rp 856** | **+0.56%** | Aman / Konsisten 👍 |
| **ERAA** | 1 | 0 | 0 | 1 | +Rp 0 | Rp 2,088 | **Rp -2,088** | **+0.00%** | High Volatility / Choppy ⚠️ |
| **CUAN** | 1 | 0 | 0 | 1 | +Rp 0 | Rp 2,256 | **Rp -2,256** | **+0.00%** | High Volatility / Choppy ⚠️ |
| **DMAS** | 2 | 0 | 0 | 2 | +Rp 0 | Rp 4,450 | **Rp -4,450** | **+0.00%** | High Volatility / Choppy ⚠️ |
| **IMPC** | 4 | 0 | 0 | 4 | +Rp 4,500 | Rp 9,363 | **Rp -4,863** | **+0.65%** | High Volatility / Choppy ⚠️ |
| **VKTR** | 1 | 0 | 0 | 1 | Rp -3,000 | Rp 2,116 | **Rp -5,116** | **-0.56%** | High Volatility / Choppy ⚠️ |
| **NZIA** | 1 | 0 | 1 | 0 | Rp -8,100 | Rp 2,161 | **Rp -10,261** | **-1.49%** | High Volatility / Choppy ⚠️ |

---

## 3. Log Rinci Seluruh Posisi Yang Masuk (Trade Log)

| Waktu (WIB) | Saham | Pola Radar | Lot | Modal Beli | Beli | Jual | TP | CL | Fee (Rp) | Net Return (Rp) | PnL (%) | Durasi | Hasil | Catatan Alasan |
|---|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| 14:48:58 | **EKAD** | `BREAKOUT_MOMENTUM` | 13 | Rp 559,000 | 430 | 444 | 443 | 424 | Rp 2,282 | **+Rp 15,918** | **+3.3%** | 57s | `TAKE_PROFIT` | TP HIT @ 444 (+3.3%)! Mengamankan profit. |
| 14:56:43 | **IMPC** | `BREAKOUT_MOMENTUM` | 4 | Rp 616,000 | 1540 | 1545 | 1586 | 1517 | Rp 2,469 | **Rp -469** | **+0.3%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (+0.3%). Exit! |
| 15:25:26 | **MDIA** | `BREAKOUT_MOMENTUM` | 25 | Rp 550,000 | 220 | 220 | 227 | 217 | Rp 2,200 | **Rp -2,200** | **+0.0%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (+0.0%). Exit! |
| 15:30:35 | **MDIA** | `BREAKOUT_MOMENTUM` | 25 | Rp 555,000 | 222 | 230 | 229 | 219 | Rp 2,270 | **+Rp 17,730** | **+3.6%** | 119s | `TAKE_PROFIT` | TP HIT @ 230 (+3.6%)! Mengamankan profit. |
| 15:31:48 | **KOTA** | `BREAKOUT_MOMENTUM` | 26 | Rp 546,000 | 210 | 216 | 216 | 207 | Rp 2,223 | **+Rp 13,377** | **+2.9%** | 125s | `TAKE_PROFIT` | TP HIT @ 216 (+2.9%)! Mengamankan profit. |
| 15:32:30 | **VKTR** | `BREAKOUT_MOMENTUM` | 6 | Rp 531,000 | 885 | 880 | 912 | 872 | Rp 2,116 | **Rp -5,116** | **-0.6%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (-0.6%). Exit! |
| 15:33:07 | **MDIA** | `BREAKOUT_MOMENTUM` | 24 | Rp 552,000 | 230 | 238 | 237 | 227 | Rp 2,256 | **+Rp 16,944** | **+3.5%** | 110s | `TAKE_PROFIT` | TP HIT @ 238 (+3.5%)! Mengamankan profit. |
| 15:34:23 | **IMPC** | `BREAKOUT_MOMENTUM` | 4 | Rp 620,000 | 1550 | 1565 | 1596 | 1527 | Rp 2,495 | **+Rp 3,505** | **+1.0%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (+1.0%). Exit! |
| 15:35:50 | **MDIA** | `BREAKOUT_MOMENTUM` | 23 | Rp 542,800 | 236 | 240 | 243 | 232 | Rp 2,194 | **+Rp 7,006** | **+1.7%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (+1.7%). Exit! |
| 15:38:01 | **INET** | `BREAKOUT_MOMENTUM` | 15 | Rp 534,000 | 356 | 358 | 367 | 351 | Rp 2,144 | **+Rp 856** | **+0.6%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (+0.6%). Exit! |
| 15:38:44 | **IMPC** | `BREAKOUT_MOMENTUM` | 4 | Rp 628,000 | 1570 | 1565 | 1617 | 1546 | Rp 2,507 | **Rp -4,507** | **-0.3%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (-0.3%). Exit! |
| 15:38:59 | **KOTA** | `BREAKOUT_MOMENTUM` | 25 | Rp 540,000 | 216 | 216 | 222 | 213 | Rp 2,160 | **Rp -2,160** | **+0.0%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (+0.0%). Exit! |
| 15:39:15 | **DMAS** | `BREAKOUT_MOMENTUM` | 27 | Rp 556,200 | 206 | 206 | 212 | 203 | Rp 2,225 | **Rp -2,225** | **+0.0%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (+0.0%). Exit! |
| 15:41:22 | **NZIA** | `BREAKOUT_MOMENTUM` | 27 | Rp 545,400 | 202 | 199 | 208 | 199 | Rp 2,161 | **Rp -10,261** | **-1.5%** | 20s | `CUT_LOSS` | CL HIT @ 199 (-1.5%)! Batas invalidasi jebol. |
| 15:39:33 | **CUAN** | `BREAKOUT_MOMENTUM` | 6 | Rp 564,000 | 940 | 940 | 968 | 926 | Rp 2,256 | **Rp -2,256** | **+0.0%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (+0.0%). Exit! |
| 15:41:09 | **MDIA** | `BREAKOUT_MOMENTUM` | 23 | Rp 542,800 | 236 | 238 | 243 | 232 | Rp 2,183 | **+Rp 2,417** | **+0.8%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (+0.8%). Exit! |
| 15:41:49 | **IMPC** | `BREAKOUT_MOMENTUM` | 3 | Rp 474,000 | 1580 | 1575 | 1627 | 1556 | Rp 1,892 | **Rp -3,392** | **-0.3%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (-0.3%). Exit! |
| 15:45:34 | **MDIA** | `BREAKOUT_MOMENTUM` | 23 | Rp 547,400 | 238 | 242 | 245 | 234 | Rp 2,213 | **+Rp 6,987** | **+1.7%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (+1.7%). Exit! |
| 15:46:02 | **ERAA** | `BREAKOUT_MOMENTUM` | 9 | Rp 522,000 | 580 | 580 | 597 | 571 | Rp 2,088 | **Rp -2,088** | **+0.0%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (+0.0%). Exit! |
| 15:48:42 | **MDIA** | `BREAKOUT_MOMENTUM` | 23 | Rp 556,600 | 242 | 248 | 249 | 238 | Rp 2,261 | **+Rp 11,539** | **+2.5%** | 185s | `SESSION_CLOSED` | Sesi Berakhir: Posisi ditutup @ 248 (+2.5%) |
| 15:49:56 | **DMAS** | `BREAKOUT_MOMENTUM` | 27 | Rp 556,200 | 206 | 206 | 212 | 203 | Rp 2,225 | **Rp -2,225** | **+0.0%** | 112s | `SESSION_CLOSED` | Sesi Berakhir: Posisi ditutup @ 206 (+0.0%) |

---

## 4. Log Kandidat yang Dibatalkan Pra-Entry (Aborted Log)
*Daftar sinyal radar yang tidak memenuhi konfirmasi follow-through HAKA sehingga otomatis dibatalkan dalam 10 detik tanpa risiko modal:*

| Waktu Radar (WIB) | Saham | Pola Radar | Harga Ref | Durasi Observasi | Alasan Pembatalan |
|---|:---:|---|:---:|:---:|---|
| 15:08:57 | **ERAA** | `BREAKOUT_MOMENTUM` | 580 | 10s | Timeout 10s: Momentum padam. Abort! |
| 15:17:33 | **BULL** | `BREAKOUT_MOMENTUM` | 442 | 10s | Timeout 10s: Momentum padam. Abort! |
| 15:19:00 | **VKTR** | `BREAKOUT_MOMENTUM` | 885 | 10s | Timeout 10s: Momentum padam. Abort! |
| 15:37:46 | **KOTA** | `BREAKOUT_MOMENTUM` | 218 | 10s | Timeout 10s: Momentum padam. Abort! |
| 15:46:37 | **KOTA** | `BREAKOUT_MOMENTUM` | 218 | 10s | Timeout 10s: Momentum padam. Abort! |
| 15:48:50 | **DEWA** | `BREAKOUT_MOMENTUM` | 448 | 10s | Timeout 10s: Momentum padam. Abort! |

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