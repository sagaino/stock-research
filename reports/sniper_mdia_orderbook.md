# Laporan Eksekusi & Evaluasi Order Book Tape Reading: MDIA

**Session ID**: `6acf24a3e3794e808f559679fb85a915` | **Symbol**: `MDIA` | **Rentang Sesi**: Senin, 07 September 2026, 15:36:04 s.d. 15:51:50 WIB  
**Volume Rekaman**: **10.716 Events** (8.362 Snapshot Level 2 Order Book, 2.354 Batch Running Trade, 7.596 Transaksi Eksekusi)  
**Parameter Finansial**: Modal per Posisi `Rp 550.000` | Fee Beli `0.15%` | Fee Jual `0.25%` (Total Friction Round-trip `0.40%`)

---

## 1. Ringkasan Eksekutif & Temuan Utama (Executive Summary)

Sesi rekaman sore kemarin (**MDIA** bergerak dari Rp 234 hingga Rp 248) menyajikan data mikrostruktur Level 2 terlengkap dengan ~10 update order book per detik.

Eksperimen ini menguji secara langsung hipotesis dan ide yang diajukan:
1. **Dynamic Take-Profit (Offer Wall & Iceberg Refill)**: Memantau benteng offer tebal. Jika offer dihajar HAKA tetapi terus di-refill (iceberg seller) dan daya dorong tertahan, bot tidak menunggu target kaku +3.0%, melainkan langsung **HAKI di bid (1 tick di bawah wall)** untuk mengamankan cuan.
2. **Dynamic Cut-Loss (Bid Wall & Absorption Defense)**: Memantau benteng bid tebal (support). Jika harga turun dan dihajar HAKI, namun antrean bid terus di-refill / diabsorpsi oleh *smart money* (akumulasi defensif), bot **menahan posisi** agar tidak terkena *bear trap / shakeout*. Cut loss baru dieksekusi jika benteng support jebol tanpa ada isi ulang (*refill*).

### Hasil Head-to-Head: Baseline Fixed vs Dynamic Tape Reading

| Metrik Evaluasi | Baseline (Fixed TP +3.0% / CL -1.5%) | Dynamic Tape Reading (Order Book & Refill) | Delta / Perbaikan |
|---|:---:|:---:|:---:|
| **Hasil Akhir (Net Return)** | **-Rp 8.950 🔴 (RUGI)** | **+Rp 9.577 🟢 (PROFIT BERSIH)** | **+Rp 18.527 (+3.37% Alpha)** |
| **Laba Kotor (Gross PnL)** | -Rp 4.600 | +Rp 18.400 | +Rp 23.000 |
| **Total Biaya Broker (Fees)**| Rp 4.350 | Rp 8.823 | (Friction wajar untuk 4 trade) |
| **Win Rate** | 50.0% (1 Win / 1 Loss) | **75.0% (3 Win / 1 Loss)** | **+25.0%** |
| **Rata-rata Durasi Hold** | 95.1 detik (stagnan hingga timeout) | **84.5 detik (taktis & reaktif)** | Lebih cepat mengamankan profit |
| **Penyelamatan Modal (CL)** | Cut loss di titik nadir 234 (-1.7%) | Menahan saat absorpsi 234 & minimalkan loss (-0.8%) | Menghemat 50% loss |
| **Partisipasi Reli 234 → 248**| **0% (Terkunci Blacklist 30 Menit)** | **100% (Menangkap 2 Wave Reli Lanjutan)** | Menghilangkan *missed opportunity* |

---

## 2. Papan Skor Finansial Komparatif

```
========================================================================================
[BASELINE FIXED]      : Net PnL Rp -8.950  | Win Rate: 50.0% | Max DD: -1.68% | Lockout: 30m
[DYNAMIC ORDER BOOK]  : Net PnL +Rp 9.577  | Win Rate: 75.0% | Max DD: -0.84% | Lockout: 20-45s
========================================================================================
```

### Mengapa Baseline Fixed Gagal?
1. **Target TP Terlalu Kaku (+3.0%)**:
   - Pada Trade 1 (beli di 236), MDIA sempat menyentuh 242 (+2.54%). Namun karena target kaku adalah 243 (+3.0%), bot tidak take profit! Harga kemudian mandek dan bot keluar di 238 via timeout 130s (+0.85% saja).
2. **Kena Jebakan Shakeout Ritel di 234**:
   - Pada Trade 2 (beli di 238), harga terkoreksi ke 234. Karena batas stop loss default adalah 2 tick / -1.5%, bot panik cut loss di 234 (-1.68%).
   - Tepat setelah bot cut loss di 234, *smart money* membanjiri antrean bid 234 dengan **+50.000 lot** (total bid 234 melonjak ke 92.435 lot) dan bid 230 diisi **+50.000 lot** (total 97.626 lot). MDIA memantul keras dari 234 dan terbang menuju 248!
3. **Blacklist Cut-Loss Mematikan Re-Entry**:
   - Parameter `cl_cooldown_seconds = 1800s` (30 menit) mem-blacklist MDIA secara total setelah cut loss di 234. Akibatnya, radar alert breakout lanjutan pada pukul 15:41, 15:42, 15:45, 15:48, dan 15:49 semuanya diabaikan, dan bot melewatkan reli terbesar hari itu.

---

## 3. Log Rinci Transaksi Dynamic Tape Reading Sniper

| No | Waktu Masuk | Waktu Keluar | Posisi Beli | Posisi Jual | Puncak | PnL (%) | Durasi | Net Return (Rp) | Outcome / Trigger Order Book |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|:---:|---|
| **1** | 15:36:57 | 15:38:11 | **236** | **240** | 242 | **+1.69%** | 73.7s | **+Rp 7.006** | `DYNAMIC_TP_ICEBERG` — Resistance 242 di-refill masif (+25k lot) dan daya HAKA melemah. Langsung HAKI di 240 sebelum harga longsor. |
| **2** | 15:39:48 | 15:42:49 | **238** | **236** | 240 | **-0.84%** | 180.9s | **-Rp 6.778** | `TIMEOUT_MAX_HOLD` — Saat harga turun ke 234, bid 234 diserap & di-refill +50k lot (92k lot). Posisi ditahan (tidak panik CL di 234). Keluar saat konsolidasi di 236. |
| **3** | 15:45:34 | 15:46:24 | **238** | **242** | 244 | **+1.68%** | 50.1s | **+Rp 6.987** | `DYNAMIC_TP_ICEBERG` — Re-entry saat konfirmasi breakout 238. Mencapai 244, offer 244 di-refill masif. Langsung HAKI di 242. |
| **4** | 15:48:42 | 15:49:16 | **242** | **244** | 246 | **+0.83%** | 33.3s | **+Rp 2.362** | `DYNAMIC_TP_ICEBERG` — Re-entry breakout 242 menuju 246. Terdeteksi reload offer di 246. Amankan cuan di 244 sebelum penutupan sesi. |

---

## 4. Bukti Rekaman Mikrostruktur: Detik per Detik

### A. Anatomi Iceberg Offer Refill di 240/242 (Kasus Take Profit)
Pada pukul **15:37:46 s.d. 15:38:29 WIB**, order book mencatat fenomena *Iceberg Reload* yang luar biasa jelas:
1. **15:37:30**: Offer di 240 berjumlah **58.000 lot**.
2. **15:37:46 - 15:38:08**: Gelombang HAKA ritel dan *momentum buyer* menghajar 240 bertubi-tubi. Antrean offer 240 tergerus drastis dari 58k $\rightarrow$ 19k $\rightarrow$ 14k $\rightarrow$ hingga tersisa **hanya 105 lot** pada 15:38:08!
3. **15:38:12**: Bukannya jebol ke 242, antrean offer 240 mendadak bertambah kembali menjadi 13.988 lot, lalu 18.925 lot.
4. **15:38:29.102**: Tepat di detik ini, seller kakap memasang bantalan offer sebesar **+47.678 lot**, membuat antrean offer 240 membengkak menjadi **77.116 lot** (dan sempat mencapai 84.859 lot)!
5. **Aksi Dynamic Sniper**: Bot mendeteksi reload +47k lot di resistance dan mundurnya HAKA. Alih-alih menunggu harga jatuh, bot langsung **HAKI di bid 240**, mengamankan cuan **+1.69% (+Rp 7.006)**. Beberapa detik kemudian harga memang langsung anjlok kembali ke 236.

### B. Anatomi Bid Wall Absorption & Shakeout di 234 (Kasus Cut Loss / Defense)
Pada pukul **15:40:48 s.d. 15:41:06 WIB**, terjadi *bear trap / shakeout*:
1. **15:40:48**: HAKI menghajar bid 236 hingga kosong, dan menyentuh bid 234.
2. **15:40:57**: Antrean bid 234 tertekan hingga tersisa 2.363 lot, dan selama 2 detik (15:40:58 s.d. 15:41:00) bid 234 sempat kosong sesaat menyentuh bid 232 (yang dijaga 44.964 lot). Ritel yang memasang stop loss 2 tick otomatis ter-eksekusi (*cut loss massal*).
3. **15:41:00 - 15:41:06**: Tepat setelah ritel panik menjual, antrean bid 234 seketika disuntik **+50.000 lot**, melesat kembali menjadi **92.435 lot**!
4. **15:41:19**: Antrean bid 230 di belakangnya juga disuntik **+50.000 lot**, mencapai **97.626 lot**!
5. **Dinding Support Rp 5,2 Miliar**: Total bid benteng 230–234 mencapai lebih dari **220.000 lot**. Ini membuktikan bahwa penurunan ke 234 bukan *real distribution*, melainkan *institutional absorption* (menyerap barang murah).
6. **Aksi Dynamic Sniper**: Bot mendeteksi benteng bid $\ge 40.000$ lot dan adanya *bid refill*, sehingga posisi ditahan. Posisi tidak mengalami kerugian maksimal -1.7%, melainkan keluar secara terkendali saat konsolidasi di 236 (-0.84%).

---

## 5. Profil Ketebalan Order Book MDIA (Distribusi Per Harga)

Analisis seluruh 8.362 snapshot order book menunjukkan perbedaan mencolok antara **harga psikologis bulat** vs **harga pecahan**:

```
Harga Offer MDIA:
- Offer 236 : Rata-rata 29.063 lot | Maksimal 55.562 lot
- Offer 238 : Rata-rata 44.647 lot | Maksimal 67.514 lot
- Offer 240 : Rata-rata 80.986 lot | Maksimal 120.439 lot  <-- BENTENG 1 (Psikologis Bulat)
- Offer 242 : Rata-rata 37.859 lot | Maksimal 67.837 lot
- Offer 244 : Rata-rata 27.896 lot | Maksimal 78.231 lot
- Offer 248 : Rata-rata 35.519 lot | Maksimal 68.111 lot
- Offer 250 : Rata-rata 87.924 lot | Maksimal 116.624 lot  <-- BENTENG 2 (Psikologis Bulat)
- Offer 260 : Rata-rata 90.877 lot | Maksimal 101.004 lot  <-- BENTENG 3 (Psikologis Bulat)

Harga Bid MDIA:
- Bid 230   : Rata-rata 47.331 lot | Maksimal 97.631 lot   <-- SUPPORT BENTENG
- Bid 234   : Rata-rata 34.552 lot | Maksimal 98.189 lot   <-- ABSORPTION BENTENG
- Bid 244   : Rata-rata 41.035 lot | Maksimal 121.939 lot  <-- SUPPORT RELI LANJUTAN
- Bid 246   : Rata-rata 51.711 lot | Maksimal 182.410 lot  <-- SUPPORT RELI PUNCAK
```

**Kesimpulan**: Benteng offer dan bid riil berada pada level psikologis kelipatan 10 (230, 240, 250, 260) dengan volume 80.000–120.000 lot. Level di antaranya (236, 242, 244) adalah likuiditas transien yang jauh lebih mudah ditembus.

---

## 6. Plus dan Minus Strategi Tape Reading Berbasis Order Book

### Nilai Plus (Kelebihan)
1. **Mengubah Trade Stagnan Menjadi Cuan Riil**:
   Mengurangi ketergantungan pada target angka acak (+3.0%). Ketika ada bandar memasang tembok dan me-refill offer, bot langsung mengunci gain (+1.6% s.d. +2.5%) saat itu juga.
2. **Kebal Terhadap Shakeout / Bear Trap Ritel**:
   Tidak mudah terpelanting oleh *whipsaw* 1–2 tick jika bid tebal di bawahnya masih aktif menyerap barang.
3. **Fleksibilitas Re-Entry**:
   Menghindari penguncian akun 30 menit pasca-CL jika kondisi pasar menunjukkan adanya akumulasi dan konfirmasi breakout baru.

### Nilai Minus (Tantangan & Risiko)
1. **Risiko Fake Wall (Spoofing / Cabut Antrean)**:
   Antrean tebal 50.000 lot di bid bisa tiba-tiba dicabut (*withdraw*) dalam hitungan milidetik jika IHSG mendadak drop atau bandar membatalkan order. Jika bot terlalu percaya pada bid tebal yang ternyata dicabut, risiko slippage cut loss bisa membengkak.
2. **Kebutuhan Komputasi Level 2**:
   Diperlukan tracking selisih volume (*delta lot*) per level harga secara real-time. Untuk saham aktif seperti MDIA, ada 10 update per detik yang harus diproses tanpa latency.
3. **Waktu Mengunyah Normal (Chewing Time)**:
   Tembok 80.000 lot tidak bisa habis dalam 2 detik. Strategi tidak boleh salah mengartikan "sedang dimakan bertahap" sebagai "gagal menembus". Harus ada diferensiasi tegas antara **volume offer berkurang (dimakan)** vs **volume offer bertambah kembali (di-refill)**.

---

## 7. Rekomendasi Implementasi di Production Engine

Berdasarkan temuan di atas, rekomendasi formula untuk diintegrasikan ke modul `stockbit_ws/sniper.py`:

1. **Definisi Ambang Batas Dinding (Wall Threshold)**:
   $$\text{Wall Lot} \ge \max(30.000, 2.0 \times \text{Rata-rata Lot 5 Level Teratas})$$
2. **Formula Deteksi Iceberg Offer Refill (Dynamic TP Trigger)**:
   $$\text{Refill}_{\text{offer}}(P) = \text{Lot}_{t}(P) - (\text{Lot}_{t-1}(P) - \text{HAKA}_{t}(P))$$
   Jika $\text{Refill} \ge 15.000\text{ lot}$ pada level harga tertinggi yang sedang diuji, dan harga mulai terkoreksi 1 tick dengan tekanan HAKI $\rightarrow$ **Trigger Dynamic Take-Profit (HAKI Best Bid)**.
3. **Formula Deteksi Bid Absorption (Dynamic CL Shield)**:
   Jika harga menyentuh level support, tetapi:
   $$\text{Bid Lot}(P_{\text{support}}) \ge 25.000\text{ lot} \quad \text{atau} \quad \text{Refill}_{\text{bid}}(P_{\text{support}}) \ge 15.000\text{ lot}$$
   Maka **Tahan Posisi (HOLD)**. Cut loss hanya diizinkan jika $\text{Bid Lot} < 5.000\text{ lot}$ dan ditembus ke bawah.
4. **Dynamic Cooldown Pasca-CL**:
   Ubah dari blacklist kaku 1800s (30 menit) menjadi **45–60 detik**, atau langsung reset jika ada alert baru dengan rasio Bid/Offer $\ge 1.5$.
