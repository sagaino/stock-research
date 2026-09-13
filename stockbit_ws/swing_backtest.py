"""Walk-forward evaluation for the EOD-only swing macro shortlist."""

from __future__ import annotations

import argparse
import datetime
import statistics
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx

from stockbit_ws.postgres import connect_database, initialize_schema
from stockbit_ws.swing_confluence import run_swing_confluence


PRICE_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}.JK"
PRICE_SOURCE = "Yahoo Finance daily chart (raw OHLC)"
PRICE_HEADERS = {"User-Agent": "Mozilla/5.0"}


def week_ends(start: datetime.date, end: datetime.date) -> list[datetime.date]:
    """Return Friday signal dates that still have one full following week."""
    first = start + datetime.timedelta(days=(4 - start.weekday()) % 7)
    result = []
    while first + datetime.timedelta(days=7) <= end:
        result.append(first)
        first += datetime.timedelta(days=7)
    return result


def fetch_daily_prices(symbol: str, start: datetime.date, end: datetime.date) -> list[tuple]:
    response = httpx.get(
        PRICE_URL.format(symbol=symbol),
        params={
            "period1": int(datetime.datetime.combine(start, datetime.time(), datetime.UTC).timestamp()),
            "period2": int(datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time(), datetime.UTC).timestamp()),
            "interval": "1d",
        },
        headers=PRICE_HEADERS,
        timeout=20,
    )
    response.raise_for_status()
    chart = (response.json().get("chart", {}).get("result") or [None])[0]
    if not chart:
        return []
    quote = (chart.get("indicators", {}).get("quote") or [{}])[0]
    rows = []
    for timestamp, opening, high, low, close in zip(
        chart.get("timestamp") or [], quote.get("open") or [], quote.get("high") or [],
        quote.get("low") or [], quote.get("close") or [],
    ):
        if not all(isinstance(value, (int, float)) and value > 0 for value in (opening, high, low, close)):
            continue
        date = datetime.datetime.fromtimestamp(timestamp, datetime.UTC).date()
        if start <= date <= end:
            rows.append((date, symbol, opening, high, low, close, PRICE_SOURCE))
    return rows


def store_daily_prices(rows: list[tuple]) -> None:
    if not rows:
        return
    conn = connect_database()
    initialize_schema(conn)
    try:
        with conn.transaction():
            conn.cursor().executemany(
                """INSERT INTO stockbit_ws.market_daily_prices
                (date, symbol, open, high, low, close, source)
                VALUES (%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (date, symbol) DO UPDATE SET
                  open = EXCLUDED.open, high = EXCLUDED.high, low = EXCLUDED.low,
                  close = EXCLUDED.close, source = EXCLUDED.source, fetched_at = now()""",
                rows,
            )
    finally:
        conn.close()


def load_daily_prices(symbols: list[str], start: datetime.date, end: datetime.date) -> dict[str, dict[datetime.date, dict[str, float]]]:
    conn = connect_database(readonly=True)
    try:
        rows = conn.execute(
            """SELECT date, symbol, open, high, low, close
               FROM stockbit_ws.market_daily_prices
               WHERE symbol = ANY(%s) AND date BETWEEN %s AND %s""",
            (symbols, start, end),
        ).fetchall()
    finally:
        conn.close()
    prices: dict[str, dict[datetime.date, dict[str, float]]] = defaultdict(dict)
    for row in rows:
        prices[row["symbol"]][row["date"]] = {key: float(row[key]) for key in ("open", "high", "low", "close")}
    return prices


def evaluate_outcome(signal_date: datetime.date, bars: dict[datetime.date, dict[str, float]]) -> dict[str, float] | None:
    """Measure the first five available sessions after an EOD shortlist."""
    signal = bars.get(signal_date)
    future_dates = sorted(date for date in bars if date > signal_date)[:5]
    if not signal or len(future_dates) < 5:
        return None
    entry = signal["close"]
    future = [bars[date] for date in future_dates]
    return {
        "entry": entry,
        "exit": future[-1]["close"],
        "return_pct": (future[-1]["close"] / entry - 1) * 100,
        "max_up_pct": (max(bar["high"] for bar in future) / entry - 1) * 100,
        "max_down_pct": (min(bar["low"] for bar in future) / entry - 1) * 100,
    }


def _summary(values: list[float]) -> dict[str, float | int]:
    return {
        "count": len(values),
        "mean": statistics.mean(values) if values else 0.0,
        "median": statistics.median(values) if values else 0.0,
        "win_rate": sum(value > 0 for value in values) / len(values) * 100 if values else 0.0,
    }


def generate_report(folds: list[dict[str, Any]], start: datetime.date, end: datetime.date) -> str:
    all_outcomes = [outcome for fold in folds for outcome in fold["outcomes"]]
    summary = _summary([outcome["return_pct"] for outcome in all_outcomes])
    lines = [
        "# 📈 WALK-FORWARD BACKTEST — SWING MACRO EOD (TANPA L2)",
        f"**Periode sinyal:** `{start}` s/d `{end}`",
        "**Metode:** setiap Jumat, jalankan shortlist broker EOD 5 hari; ukur close, high, dan low pada 5 sesi IDX sesudahnya.",
        f"**Harga:** `{PRICE_SOURCE}`; bar disimpan di `stockbit_ws.market_daily_prices`.",
        "**Batasan:** ini evaluasi kualitas shortlist, bukan simulasi order atau klaim profit. Fee, spread, slippage, likuiditas entry, dan corporate action tidak dimodelkan.",
        "",
        f"## Ringkasan ({summary['count']} kandidat dengan harga lengkap)",
        "",
        f"- Return close 5 sesi: rata-rata **{summary['mean']:+.2f}%**, median **{summary['median']:+.2f}%**.",
        f"- Win rate close 5 sesi: **{summary['win_rate']:.1f}%**.",
        "",
        "| Minggu sinyal | Shortlist EOD | Terukur | Rata-rata return 5s | Median | Win rate |",
        "|:-------------:|--------------:|---------:|-------------------:|-------:|---------:|",
    ]
    for fold in folds:
        stats = _summary([outcome["return_pct"] for outcome in fold["outcomes"]])
        lines.append(f"| {fold['date']} | {fold['candidates']} | {stats['count']} | {stats['mean']:+.2f}% | {stats['median']:+.2f}% | {stats['win_rate']:.1f}% |")
    lines.extend(["", "## Detail kandidat", "", "| Minggu sinyal | Saham | Entry close | Exit close 5s | Return | Maks. naik | Maks. turun |", "|:-------------:|:-----:|------------:|--------------:|-------:|-----------:|------------:|"])
    for fold in folds:
        for outcome in fold["outcomes"]:
            lines.append(f"| {fold['date']} | {outcome['symbol']} | {outcome['entry']:,.0f} | {outcome['exit']:,.0f} | {outcome['return_pct']:+.2f}% | {outcome['max_up_pct']:+.2f}% | {outcome['max_down_pct']:+.2f}% |")
    return "\n".join(lines)


def run_backtest(start: datetime.date, end: datetime.date, *, auto_fetch_eod: bool = True, refresh_prices: bool = False) -> tuple[list[dict[str, Any]], str]:
    if start > end:
        raise ValueError("Tanggal mulai tidak boleh setelah tanggal akhir")
    folds = []
    for signal_date in week_ends(start, end):
        print(f"📊 [EOD] Membentuk shortlist minggu berakhir {signal_date}...")
        picks, dates = run_swing_confluence(signal_date.isoformat(), auto_fetch_eod=auto_fetch_eod, auto_fetch_l2=False, macro_only=True)
        if len(dates) < 5:
            print(f"⚠️ {signal_date}: EOD lengkap belum tersedia; minggu dilewati.")
            continue
        folds.append({
            "date": datetime.date.fromisoformat(dates[-1]),
            "picks": picks, "candidates": len(picks), "outcomes": [],
        })

    symbols = sorted({pick["symbol"] for fold in folds for pick in fold["picks"]})
    if symbols:
        conn = connect_database(readonly=True)
        try:
            cached = {row["symbol"] for row in conn.execute(
                """SELECT symbol FROM stockbit_ws.market_daily_prices
                   WHERE symbol = ANY(%s) AND date BETWEEN %s AND %s
                   GROUP BY symbol HAVING min(date) <= %s AND max(date) >= %s""",
                (symbols, start, end, start, end),
            ).fetchall()}
        finally:
            conn.close()
        needed = symbols if refresh_prices else [symbol for symbol in symbols if symbol not in cached]
        for index, symbol in enumerate(needed, 1):
            try:
                store_daily_prices(fetch_daily_prices(symbol, start, end))
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
                print(f"⚠️ Harga {symbol} tidak tersedia: {type(exc).__name__}")
            if index < len(needed):
                time.sleep(0.1)

    prices = load_daily_prices(symbols, start, end)
    for fold in folds:
        for pick in fold["picks"]:
            outcome = evaluate_outcome(fold["date"], prices.get(pick["symbol"], {}))
            if outcome:
                fold["outcomes"].append({"symbol": pick["symbol"], **outcome})
    return folds, generate_report(folds, start, end)


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward shortlist swing EOD tanpa L2")
    parser.add_argument("--from", dest="start", required=True, help="Mulai minggu pertama, YYYY-MM-DD")
    parser.add_argument("--to", dest="end", required=True, help="Tanggal akhir harga evaluasi, YYYY-MM-DD")
    parser.add_argument("--no-eod", action="store_true", help="Jangan backfill EOD yang belum lengkap")
    parser.add_argument("--refresh-prices", action="store_true", help="Ambil ulang OHLC harian dari sumber harga")
    args = parser.parse_args()
    try:
        start = datetime.date.fromisoformat(args.start)
        end = datetime.date.fromisoformat(args.end)
    except ValueError:
        parser.error("--from dan --to harus YYYY-MM-DD")

    folds, report = run_backtest(start, end, auto_fetch_eod=not args.no_eod, refresh_prices=args.refresh_prices)
    out_dir = Path("reports")
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / f"swing_macro_backtest_{start:%Y%m%d}_{end:%Y%m%d}.md"
    out_file.write_text(report, encoding="utf-8")
    measured = sum(len(fold["outcomes"]) for fold in folds)
    print(f"✅ {len(folds)} minggu dan {measured} kandidat terukur. Laporan: {out_file}")


if __name__ == "__main__":
    main()
