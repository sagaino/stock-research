# Laporan Hasil Eksekusi Taktis Scout & Sniper (Trade Log, TP & CL)
**Session ID**: `a5b02a9097084d7cad2f7d58eddfc90b` | **Symbol**: `*` | **Rentang Sesi**: 2026-09-08T06:41:30.946+00:00 s.d. 2026-09-08T07:09:41.042+00:00
**Konfigurasi Sniper**: Kapasitas `5 Slot` | Target TP `+3.0%` | Stop Loss `-1.5%` | Max Hold `130s` | Observasi `10s` | Mode Hybrid `T1 50% Scalp / T2 50% Runner` (Max Hold 900s)
**Simulasi Frictions**: Modal per Trade `Rp 550,000` | Fee Beli `0.15%` | Fee Jual `0.25%` (Round-trip ~0.40%)

---

## 1. Papan Skor Kinerja & Return Finansial (Financial Scoreboard)

| Metrik Evaluasi Finansial | Nilai Kinerja | Keterangan |
|---|:---:|---|
| **Status Hasil Akhir** | **LOSS 🔴** | Setelah dikurangi seluruh biaya broker (Buy 0.15% + Sell 0.25%) |
| **Laba Bersih (Net Profit/Loss)** | **Rp -26,219** | **Profit bersih final masuk ke akun trading** |
| **Laba Kotor (Gross Profit/Loss)**| +Rp 5,400 | Akumulasi selisih harga jual dikurangi harga beli |
| **Total Biaya Broker (Fees Paid)**| Rp 31,619 | Beban komisi transaksi beli & jual |
| **Total Modal Ditransaksikan**    | Rp 7,901,400 | Akumulasi perputaran modal dari 7 kali transaksi |
| **Win Rate (TP vs CL)**           | **33.3%** | Rasio kemenangan posisi yang terdeterminasi |
| **Take-Profit (TP Hit)**          | **1** (14.3%) | Target profit tercapai (+3.0% s/d +4.0%) |
| **Cut-Loss (CL Hit)**             | **2** (28.6%) | Batas invalidasi tertembus (disiplin cut-loss) |
| **Stagnant Exit (Timeout)**       | **4** (57.1%) | Posisi mandek dilepas pada 130s |
| **Dibatalkan Pra-Entry (ABORTED)**| **4** | Momentum padam dalam 10s (nol risiko modal) |
| **Rata-rata Profit (Avg Win)**    | **+2.78%** | Rata-rata persentase gain posisi TP |
| **Rata-rata Rugi (Avg Loss)**     | **-1.61%** | Rata-rata persentase loss posisi CL |
| **Akumulasi Net PnL (%)**         | **-0.50%** | Total persentase PnL seluruh posisi masuk |

---

## 2. Rangkuman Hasil per Kode Saham (P&L dan Biaya Broker)

| Saham | Masuk | TP | CL | Timeout | Gross PnL (Rp) | Fee Broker (Rp) | Net Return (Rp) | Akumulasi PnL (%) | Status / Perilaku |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **PIPA** | 2 | 1 | 1 | 0 | +Rp 5,400 | Rp 4,343 | **+Rp 1,057** | **+1.01%** | Aman / Konsisten 👍 |
| **INET** | 1 | 0 | 0 | 1 | +Rp 0 | Rp 2,220 | **Rp -2,220** | **+0.00%** | High Volatility / Choppy ⚠️ |
| **ITMG** | 1 | 0 | 0 | 1 | +Rp 7,500 | Rp 10,729 | **Rp -3,229** | **+0.28%** | High Volatility / Choppy ⚠️ |
| **TAPG** | 1 | 0 | 0 | 1 | Rp -2,000 | Rp 1,859 | **Rp -3,859** | **-0.43%** | High Volatility / Choppy ⚠️ |
| **UNTR** | 1 | 0 | 0 | 1 | +Rp 2,500 | Rp 10,296 | **Rp -7,796** | **+0.10%** | High Volatility / Choppy ⚠️ |
| **COCO** | 1 | 0 | 1 | 0 | Rp -8,000 | Rp 2,172 | **Rp -10,172** | **-1.46%** | High Volatility / Choppy ⚠️ |

---

## 3. Log Rinci Seluruh Posisi Yang Masuk (Trade Log)

| Waktu (WIB) | Saham | Pola Radar | Lot | Modal Beli | Beli | Jual | TP | CL | Fee (Rp) | Net Return (Rp) | PnL (%) | Durasi | Hasil | Catatan Alasan |
|---|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| 13:52:34 | **UNTR** | `BREAKOUT_MOMENTUM` | 1 | Rp 2,572,500 | 25725 | 25750 | 26497 | 25339 | Rp 10,296 | **Rp -7,796** | **+0.1%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (+0.1%). Exit! |
| 13:54:55 | **ITMG** | `BREAKOUT_MOMENTUM` | 1 | Rp 2,677,500 | 26775 | 26850 | 27578 | 26373 | Rp 10,729 | **Rp -3,229** | **+0.3%** | 130s | `EXIT_TIMEOUT` | Timeout 130s: Stagnan (+0.3%). Exit! |
| 13:43:14 | **PIPA** | `BREAKOUT_MOMENTUM` | 25 | Rp 540,000 | 216 | 222 | 222 | 213 | Rp 2,198 | **+Rp 12,802** | **+2.8%** | 900s | `TAKE_PROFIT` | ⚡ Hybrid: T1(12L): TP@222 (+2.8%, Net:+Rp 6,145) | T2(13L): Out@222 (+2.8%, Net:+Rp 6,657) |
| 14:04:09 | **PIPA** | `BREAKOUT_MOMENTUM` | 24 | Rp 542,400 | 226 | 222 | 233 | 223 | Rp 2,146 | **Rp -11,746** | **-1.8%** | 32s | `CUT_LOSS` | CL HIT @ 222 (-1.8%)! Batas invalidasi jebol. |
| 13:51:23 | **TAPG** | `BREAKOUT_MOMENTUM` | 2 | Rp 466,000 | 2330 | 2320 | 2400 | 2295 | Rp 1,859 | **Rp -3,859** | **-0.4%** | 900s | `EXIT_TIMEOUT` | Timeout 900s: Stagnan (-0.4%). Exit! |
| 14:06:51 | **COCO** | `BREAKOUT_MOMENTUM` | 40 | Rp 548,000 | 137 | 135 | 141 | 135 | Rp 2,172 | **Rp -10,172** | **-1.5%** | 0s | `CUT_LOSS` | CL HIT @ 135 (-1.5%)! Batas invalidasi jebol. |
| 13:52:42 | **INET** | `BREAKOUT_MOMENTUM` | 15 | Rp 555,000 | 370 | 370 | 381 | 364 | Rp 2,220 | **Rp -2,220** | **+0.0%** | 900s | `EXIT_TIMEOUT` | Timeout 900s: Stagnan (+0.0%). Exit! |

---

## 4. Log Kandidat yang Dibatalkan Pra-Entry (Aborted Log)
*Daftar sinyal radar yang tidak memenuhi konfirmasi follow-through HAKA sehingga otomatis dibatalkan dalam 10 detik tanpa risiko modal:*

| Waktu Radar (WIB) | Saham | Pola Radar | Harga Ref | Durasi Observasi | Alasan Pembatalan |
|---|:---:|---|:---:|:---:|---|
| 13:46:48 | **MDKA** | `BREAKOUT_MOMENTUM` | 2960 | 10s | Timeout 10s: Momentum padam. Abort! |
| 13:46:55 | **UNTR** | `BREAKOUT_MOMENTUM` | 25675 | 10s | Timeout 10s: Momentum padam. Abort! |
| 13:57:27 | **DEWA** | `BREAKOUT_MOMENTUM` | 446 | 10s | Timeout 10s: Momentum padam. Abort! |
| 14:02:25 | **PIPA** | `BREAKOUT_MOMENTUM` | 222 | 10s | Timeout 10s: Momentum padam. Abort! |

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