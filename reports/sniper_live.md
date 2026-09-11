# Laporan Hasil Eksekusi Taktis Scout & Sniper (Trade Log, TP & CL)
**Session ID**: `live` | **Symbol**: `*` | **Rentang Sesi**: 2026-09-08T07:59:59.888+00:00 s.d. 2026-09-08T08:50:16.754+00:00
**Konfigurasi Sniper**: Kapasitas `5 Slot` | Target TP `+3.0%` | Stop Loss `-1.5%` | Max Hold `130s` | Observasi `10s` | Mode Hybrid `T1 50% Scalp / T2 50% Runner` (Max Hold 900s)
**Simulasi Frictions**: Modal per Trade `Rp 550,000` | Fee Beli `0.15%` | Fee Jual `0.25%` (Round-trip ~0.40%)

---

## 1. Papan Skor Kinerja & Return Finansial (Financial Scoreboard)

| Metrik Evaluasi Finansial | Nilai Kinerja | Keterangan |
|---|:---:|---|
| **Status Hasil Akhir** | **LOSS 🔴** | Setelah dikurangi seluruh biaya broker (Buy 0.15% + Sell 0.25%) |
| **Laba Bersih (Net Profit/Loss)** | **Rp -20,582** | **Profit bersih final masuk ke akun trading** |
| **Laba Kotor (Gross Profit/Loss)**| +Rp 2,100 | Akumulasi selisih harga jual dikurangi harga beli |
| **Total Biaya Broker (Fees Paid)**| Rp 22,682 | Beban komisi transaksi beli & jual |
| **Total Modal Ditransaksikan**    | Rp 5,669,100 | Akumulasi perputaran modal dari 10 kali transaksi |
| **Win Rate (TP vs CL)**           | **33.3%** | Rasio kemenangan posisi yang terdeterminasi |
| **Take-Profit (TP Hit)**          | **1** (10.0%) | Target profit tercapai (+3.0% s/d +4.0%) |
| **Cut-Loss (CL Hit)**             | **2** (20.0%) | Batas invalidasi tertembus (disiplin cut-loss) |
| **Stagnant Exit (Timeout)**       | **7** (70.0%) | Posisi mandek dilepas pada 130s |
| **Dibatalkan Pra-Entry (ABORTED)**| **3** | Momentum padam dalam 10s (nol risiko modal) |
| **Rata-rata Profit (Avg Win)**    | **+2.54%** | Rata-rata persentase gain posisi TP |
| **Rata-rata Rugi (Avg Loss)**     | **-1.56%** | Rata-rata persentase loss posisi CL |
| **Akumulasi Net PnL (%)**         | **+0.40%** | Total persentase PnL seluruh posisi masuk |

---

## 2. Rangkuman Hasil per Kode Saham (P&L dan Biaya Broker)

| Saham | Masuk | TP | CL | Timeout | Gross PnL (Rp) | Fee Broker (Rp) | Net Return (Rp) | Akumulasi PnL (%) | Status / Perilaku |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **KETR** | 1 | 1 | 0 | 0 | +Rp 13,500 | Rp 2,158 | **+Rp 11,342** | **+2.54%** | Juara Momentum 🚀 |
| **MDKA** | 1 | 0 | 0 | 1 | +Rp 4,000 | Rp 2,482 | **+Rp 1,518** | **+0.65%** | Aman / Konsisten 👍 |
| **FUTR** | 1 | 0 | 0 | 1 | +Rp 0 | Rp 2,190 | **Rp -2,190** | **+0.00%** | High Volatility / Choppy ⚠️ |
| **COCO** | 1 | 0 | 0 | 1 | +Rp 0 | Rp 2,200 | **Rp -2,200** | **+0.00%** | High Volatility / Choppy ⚠️ |
| **RMKE** | 1 | 0 | 0 | 1 | +Rp 0 | Rp 2,257 | **Rp -2,257** | **+0.00%** | High Volatility / Choppy ⚠️ |
| **RAJA** | 1 | 0 | 0 | 1 | +Rp 0 | Rp 2,296 | **Rp -2,296** | **+0.00%** | High Volatility / Choppy ⚠️ |
| **ENRG** | 2 | 0 | 0 | 2 | +Rp 2,000 | Rp 4,701 | **Rp -2,701** | **+0.34%** | High Volatility / Choppy ⚠️ |
| **IATA** | 1 | 0 | 1 | 0 | Rp -7,800 | Rp 2,196 | **Rp -9,996** | **-1.41%** | High Volatility / Choppy ⚠️ |
| **PIPA** | 1 | 0 | 1 | 0 | Rp -9,600 | Rp 2,203 | **Rp -11,803** | **-1.72%** | High Volatility / Choppy ⚠️ |

---

## 3. Log Rinci Seluruh Posisi Yang Masuk (Trade Log)

| Waktu (WIB) | Saham | Pola Radar | Lot | Modal Beli | Beli | Jual | TP | CL | Fee (Rp) | Net Return (Rp) | PnL (%) | Durasi | Hasil | Catatan Alasan |
|---|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| 15:18:49 | **IATA** | `BREAKOUT_MOMENTUM` | 39 | Rp 553,800 | 142 | 140 | 146 | 140 | Rp 2,196 | **Rp -9,996** | **-1.4%** | 298s | `CUT_LOSS` | CL HIT @ 140 (-1.4%)! Batas invalidasi jebol. |
| 15:09:05 | **RAJA** | `BREAKOUT_MOMENTUM` | 7 | Rp 574,000 | 820 | 820 | 845 | 808 | Rp 2,296 | **Rp -2,296** | **+0.0%** | 900s | `EXIT_TIMEOUT` | Timeout 900s: Stagnan (+0.0%). Exit! |
| 15:09:13 | **RMKE** | `BREAKOUT_MOMENTUM` | 13 | Rp 564,200 | 434 | 434 | 447 | 427 | Rp 2,257 | **Rp -2,257** | **+0.0%** | 900s | `EXIT_TIMEOUT` | Timeout 900s: Stagnan (+0.0%). Exit! |
| 15:10:49 | **ENRG** | `BREAKOUT_MOMENTUM` | 4 | Rp 586,000 | 1465 | 1465 | 1509 | 1443 | Rp 2,344 | **Rp -2,344** | **+0.0%** | 900s | `EXIT_TIMEOUT` | Timeout 900s: Stagnan (+0.0%). Exit! |
| 15:21:13 | **COCO** | `BREAKOUT_MOMENTUM` | 39 | Rp 549,900 | 141 | 141 | 145 | 139 | Rp 2,200 | **Rp -2,200** | **+0.0%** | 900s | `EXIT_TIMEOUT` | Timeout 900s: Stagnan (+0.0%). Exit! |
| 15:24:26 | **MDKA** | `BREAKOUT_MOMENTUM` | 2 | Rp 618,000 | 3090 | 3110 | 3183 | 3044 | Rp 2,482 | **+Rp 1,518** | **+0.7%** | 900s | `EXIT_TIMEOUT` | Timeout 900s: Stagnan (+0.7%). Exit! |
| 15:40:28 | **KETR** | `BREAKOUT_MOMENTUM` | 6 | Rp 531,000 | 885 | 908 | 912 | 872 | Rp 2,158 | **+Rp 11,342** | **+2.5%** | 5s | `TAKE_PROFIT` | ⚡ Hybrid: T1(3L): TP@915 (+3.4%, Net:+Rp 7,916) | T2(3L): Out@900 (+1.7%, Net:+Rp 3,427) |
| 15:28:10 | **ENRG** | `BREAKOUT_MOMENTUM` | 4 | Rp 588,000 | 1470 | 1475 | 1514 | 1448 | Rp 2,357 | **Rp -357** | **+0.3%** | 900s | `EXIT_TIMEOUT` | Timeout 900s: Stagnan (+0.3%). Exit! |
| 15:29:26 | **FUTR** | `BREAKOUT_MOMENTUM` | 17 | Rp 547,400 | 322 | 322 | 332 | 317 | Rp 2,190 | **Rp -2,190** | **+0.0%** | 900s | `EXIT_TIMEOUT` | Timeout 900s: Stagnan (+0.0%). Exit! |
| 15:42:59 | **PIPA** | `BREAKOUT_MOMENTUM` | 24 | Rp 556,800 | 232 | 228 | 239 | 229 | Rp 2,203 | **Rp -11,803** | **-1.7%** | 199s | `CUT_LOSS` | CL HIT @ 228 (-1.7%)! Batas invalidasi jebol. |

---

## 4. Log Kandidat yang Dibatalkan Pra-Entry (Aborted Log)
*Daftar sinyal radar yang tidak memenuhi konfirmasi follow-through HAKA sehingga otomatis dibatalkan dalam 10 detik tanpa risiko modal:*

| Waktu Radar (WIB) | Saham | Pola Radar | Harga Ref | Durasi Observasi | Alasan Pembatalan |
|---|:---:|---|:---:|:---:|---|
| 15:01:42 | **BKDP** | `BREAKOUT_MOMENTUM` | 224 | 10s | Timeout 10s: Momentum padam. Abort! |
| 15:15:27 | **JPFA** | `BREAKOUT_MOMENTUM` | 2400 | 10s | Timeout 10s: Momentum padam. Abort! |
| 15:42:30 | **MDKA** | `BREAKOUT_MOMENTUM` | 3140 | 10s | Timeout 10s: Momentum padam. Abort! |

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