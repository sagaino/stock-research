# 📈 WALK-FORWARD BACKTEST — SWING MACRO EOD (TANPA L2)
**Periode sinyal:** `2026-06-29` s/d `2026-07-12`
**Metode:** setiap Jumat, jalankan shortlist broker EOD 5 hari; ukur close, high, dan low pada 5 sesi IDX sesudahnya.
**Harga:** `Yahoo Finance daily chart (raw OHLC)`; bar disimpan di `stockbit_ws.market_daily_prices`.
**Batasan:** ini evaluasi kualitas shortlist, bukan simulasi order atau klaim profit. Fee, spread, slippage, likuiditas entry, dan corporate action tidak dimodelkan.

## Ringkasan (10 kandidat dengan harga lengkap)

- Return close 5 sesi: rata-rata **+5.05%**, median **+1.40%**.
- Win rate close 5 sesi: **60.0%**.

| Minggu sinyal | Shortlist EOD | Terukur | Rata-rata return 5s | Median | Win rate |
|:-------------:|--------------:|---------:|-------------------:|-------:|---------:|
| 2026-07-03 | 10 | 10 | +5.05% | +1.40% | 60.0% |

## Detail kandidat

| Minggu sinyal | Saham | Entry close | Exit close 5s | Return | Maks. naik | Maks. turun |
|:-------------:|:-----:|------------:|--------------:|-------:|-----------:|------------:|
| 2026-07-03 | ANTM | 2,930 | 2,900 | -1.02% | +3.75% | -6.48% |
| 2026-07-03 | BREN | 3,400 | 3,170 | -6.76% | +4.41% | -7.94% |
| 2026-07-03 | INDF | 6,925 | 6,775 | -2.17% | +0.72% | -5.05% |
| 2026-07-03 | CUAN | 610 | 620 | +1.64% | +4.92% | -3.28% |
| 2026-07-03 | SMGR | 1,425 | 1,415 | -0.70% | +7.37% | -3.16% |
| 2026-07-03 | MARK | 990 | 1,090 | +10.10% | +13.64% | -3.03% |
| 2026-07-03 | TINS | 3,430 | 3,470 | +1.17% | +2.92% | -4.96% |
| 2026-07-03 | SRTG | 1,555 | 1,585 | +1.93% | +2.57% | -2.25% |
| 2026-07-03 | ELSA | 565 | 655 | +15.93% | +16.81% | -2.65% |
| 2026-07-03 | BEEF | 204 | 266 | +30.39% | +44.12% | -6.86% |