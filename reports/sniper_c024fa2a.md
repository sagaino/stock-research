# Laporan Hasil Eksekusi Taktis Scout & Sniper (Trade Log, TP & CL)
**Session ID**: `c024fa2a9af64e6d805d0ecd2e75ff6d` | **Symbol**: `*` | **Rentang Sesi**: 2026-09-08T07:09:56.257+00:00 s.d. 2026-09-08T08:00:17.094+00:00
**Konfigurasi Sniper**: Kapasitas `5 Slot` | Target TP `+3.0%` | Stop Loss `-1.5%` | Max Hold `130s` | Observasi `10s` | Mode Hybrid `T1 50% Scalp / T2 50% Runner` (Max Hold 900s)
**Simulasi Frictions**: Modal per Trade `Rp 550,000` | Fee Beli `0.15%` | Fee Jual `0.25%` (Round-trip ~0.40%)

---

## 1. Papan Skor Kinerja & Return Finansial (Financial Scoreboard)

| Metrik Evaluasi Finansial | Nilai Kinerja | Keterangan |
|---|:---:|---|
| **Status Hasil Akhir** | **LOSS 🔴** | Setelah dikurangi seluruh biaya broker (Buy 0.15% + Sell 0.25%) |
| **Laba Bersih (Net Profit/Loss)** | **Rp -31,016** | **Profit bersih final masuk ke akun trading** |
| **Laba Kotor (Gross Profit/Loss)**| Rp -13,400 | Akumulasi selisih harga jual dikurangi harga beli |
| **Total Biaya Broker (Fees Paid)**| Rp 17,616 | Beban komisi transaksi beli & jual |
| **Total Modal Ditransaksikan**    | Rp 4,412,400 | Akumulasi perputaran modal dari 8 kali transaksi |
| **Win Rate (TP vs CL)**           | **25.0%** | Rasio kemenangan posisi yang terdeterminasi |
| **Take-Profit (TP Hit)**          | **1** (12.5%) | Target profit tercapai (+3.0% s/d +4.0%) |
| **Cut-Loss (CL Hit)**             | **3** (37.5%) | Batas invalidasi tertembus (disiplin cut-loss) |
| **Stagnant Exit (Timeout)**       | **4** (50.0%) | Posisi mandek dilepas pada 130s |
| **Dibatalkan Pra-Entry (ABORTED)**| **2** | Momentum padam dalam 10s (nol risiko modal) |
| **Rata-rata Profit (Avg Win)**    | **+2.18%** | Rata-rata persentase gain posisi TP |
| **Rata-rata Rugi (Avg Loss)**     | **-2.07%** | Rata-rata persentase loss posisi CL |
| **Akumulasi Net PnL (%)**         | **-2.49%** | Total persentase PnL seluruh posisi masuk |

---

## 2. Rangkuman Hasil per Kode Saham (P&L dan Biaya Broker)

| Saham | Masuk | TP | CL | Timeout | Gross PnL (Rp) | Fee Broker (Rp) | Net Return (Rp) | Akumulasi PnL (%) | Status / Perilaku |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **COCO** | 1 | 0 | 0 | 1 | +Rp 7,800 | Rp 2,204 | **+Rp 5,596** | **+1.43%** | Aman / Konsisten 👍 |
| **INET** | 1 | 0 | 0 | 1 | +Rp 3,000 | Rp 2,240 | **+Rp 760** | **+0.54%** | Aman / Konsisten 👍 |
| **PIPA** | 2 | 1 | 1 | 0 | +Rp 2,600 | Rp 4,416 | **Rp -1,816** | **+0.41%** | High Volatility / Choppy ⚠️ |
| **BULL** | 1 | 0 | 0 | 1 | +Rp 0 | Rp 2,236 | **Rp -2,236** | **+0.00%** | High Volatility / Choppy ⚠️ |
| **EKAD** | 1 | 0 | 0 | 1 | Rp -2,400 | Rp 2,173 | **Rp -4,573** | **-0.44%** | High Volatility / Choppy ⚠️ |
| **GPRA** | 1 | 0 | 1 | 0 | Rp -10,000 | Rp 2,195 | **Rp -12,195** | **-1.80%** | High Volatility / Choppy ⚠️ |
| **PADI** | 1 | 0 | 1 | 0 | Rp -14,400 | Rp 2,153 | **Rp -16,553** | **-2.63%** | High Volatility / Choppy ⚠️ |

---

## 3. Log Rinci Seluruh Posisi Yang Masuk (Trade Log)

| Waktu (WIB) | Saham | Pola Radar | Lot | Modal Beli | Beli | Jual | TP | CL | Fee (Rp) | Net Return (Rp) | PnL (%) | Durasi | Hasil | Catatan Alasan |
|---|:---:|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| 14:12:04 | **PADI** | `BREAKOUT_MOMENTUM` | 72 | Rp 547,200 | 76 | 74 | 78 | 74 | Rp 2,153 | **Rp -16,553** | **-2.6%** | 212s | `CUT_LOSS` | CL HIT @ 74 (-2.6%)! Batas invalidasi jebol. |
| 14:18:40 | **GPRA** | `BREAKOUT_MOMENTUM` | 50 | Rp 555,000 | 111 | 109 | 114 | 109 | Rp 2,195 | **Rp -12,195** | **-1.8%** | 20s | `CUT_LOSS` | CL HIT @ 109 (-1.8%)! Batas invalidasi jebol. |
| 14:16:38 | **PIPA** | `BREAKOUT_MOMENTUM` | 25 | Rp 560,000 | 224 | 229 | 231 | 221 | Rp 2,270 | **+Rp 9,930** | **+2.2%** | 547s | `TAKE_PROFIT` | ⚡ Hybrid: T1(12L): TP@232 (+3.6%, Net:+Rp 8,501) | T2(13L): Out@226 (+0.9%, Net:+Rp 1,429) |
| 14:13:01 | **INET** | `BREAKOUT_MOMENTUM` | 15 | Rp 558,000 | 372 | 374 | 383 | 366 | Rp 2,240 | **+Rp 760** | **+0.5%** | 900s | `EXIT_TIMEOUT` | Timeout 900s: Stagnan (+0.5%). Exit! |
| 14:30:07 | **COCO** | `BREAKOUT_MOMENTUM` | 39 | Rp 546,000 | 140 | 142 | 144 | 138 | Rp 2,204 | **+Rp 5,596** | **+1.4%** | 900s | `EXIT_TIMEOUT` | Timeout 900s: Stagnan (+1.4%). Exit! |
| 14:33:20 | **BULL** | `BREAKOUT_MOMENTUM` | 13 | Rp 559,000 | 430 | 430 | 443 | 424 | Rp 2,236 | **Rp -2,236** | **+0.0%** | 900s | `EXIT_TIMEOUT` | Timeout 900s: Stagnan (+0.0%). Exit! |
| 14:43:17 | **PIPA** | `BREAKOUT_MOMENTUM` | 24 | Rp 542,400 | 226 | 222 | 233 | 223 | Rp 2,146 | **Rp -11,746** | **-1.8%** | 318s | `CUT_LOSS` | CL HIT @ 222 (-1.8%)! Batas invalidasi jebol. |
| 14:43:04 | **EKAD** | `BREAKOUT_MOMENTUM` | 12 | Rp 544,800 | 454 | 452 | 468 | 447 | Rp 2,173 | **Rp -4,573** | **-0.4%** | 900s | `EXIT_TIMEOUT` | Timeout 900s: Stagnan (-0.4%). Exit! |

---

## 4. Log Kandidat yang Dibatalkan Pra-Entry (Aborted Log)
*Daftar sinyal radar yang tidak memenuhi konfirmasi follow-through HAKA sehingga otomatis dibatalkan dalam 10 detik tanpa risiko modal:*

| Waktu Radar (WIB) | Saham | Pola Radar | Harga Ref | Durasi Observasi | Alasan Pembatalan |
|---|:---:|---|:---:|:---:|---|
| 14:39:23 | **PIPA** | `BREAKOUT_MOMENTUM` | 226 | 10s | Timeout 10s: Momentum padam. Abort! |
| 14:54:34 | **ENRG** | `BREAKOUT_MOMENTUM` | 1460 | 10s | Timeout 10s: Momentum padam. Abort! |

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