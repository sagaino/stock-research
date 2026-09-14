"""Walk-forward simulation for the EOD-only swing macro shortlist."""

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
from stockbit_ws.idx_calendar import first_idx_session_on_or_after, is_idx_session, last_idx_session_on_or_before, next_idx_sessions
from stockbit_ws.sniper import _paper_fill, get_idx_tick_size, round_to_idx_tick
from stockbit_ws.swing_confluence import run_swing_confluence


PRICE_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}.JK"
PRICE_SOURCE = "Yahoo Finance daily chart (raw OHLC)"
PRICE_HEADERS = {"User-Agent": "Mozilla/5.0"}
DEFAULT_MIN_COVERAGE_PCT = 80.0
DEFAULT_MIN_PROFIT_FACTOR = 1.20
DEFAULT_MIN_VALIDATION_TRADES = 30


def week_ends(start: datetime.date, end: datetime.date, hold_sessions: int = 5) -> list[datetime.date]:
    """Return Friday signals that still have the requested IDX holding window."""
    first = start + datetime.timedelta(days=(4 - start.weekday()) % 7)
    result = []
    while first <= end:
        if is_idx_session(first) and next_idx_sessions(first, hold_sessions)[-1] <= end:
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


def eod_coverage(dates: list[str]) -> tuple[float, float]:
    """Return minimum and average Top-20 broker value coverage for a window."""
    conn = connect_database(readonly=True)
    try:
        rows = conn.execute(
            """WITH selected AS (
                   SELECT DISTINCT date, broker_code
                   FROM stockbit_ws.broker_stock_activity
                   WHERE date = ANY(%s)
               )
               SELECT t.date,
                      sum(t.total_value) AS all_value,
                      sum(t.total_value) FILTER (WHERE s.broker_code IS NOT NULL) AS selected_value
               FROM stockbit_ws.broker_top_daily t
               LEFT JOIN selected s ON s.date = t.date AND s.broker_code = t.broker_code
               WHERE t.date = ANY(%s)
               GROUP BY t.date""",
            (dates, dates),
        ).fetchall()
    finally:
        conn.close()
    values = [float(row["selected_value"] or 0) / float(row["all_value"] or 1) * 100 for row in rows]
    return (min(values), statistics.mean(values)) if len(values) == len(dates) and values else (0.0, 0.0)


def rank_candidates(
    picks: list[dict[str, Any]], signal_date: datetime.date,
    prices: dict[str, dict[datetime.date, dict[str, float]]], *,
    max_margin_pct: float, max_positions: int,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Rank candidates and retain an auditable reason for every exclusion."""
    eligible, audit = [], []
    for pick in picks:
        close = prices.get(pick["symbol"], {}).get(signal_date, {}).get("close", 0)
        average = float(pick["top_buyer_avg"] or 0)
        if close <= 0:
            audit.append({"symbol": pick["symbol"], "stage": "FILTER", "reason": "OHLC_SINYAL_TIDAK_TERSEDIA"})
            continue
        if average <= 0:
            audit.append({"symbol": pick["symbol"], "stage": "FILTER", "reason": "AVERAGE_BROKER_TIDAK_TERSEDIA"})
            continue
        margin_pct = (close / average - 1) * 100
        if margin_pct <= max_margin_pct + 1e-9:
            eligible.append({**pick, "signal_close": close, "margin_pct": margin_pct})
        else:
            audit.append({"symbol": pick["symbol"], "stage": "FILTER", "reason": "HARGA_DI_ATAS_BATAS_AVERAGE"})
    ranked = sorted(eligible, key=lambda pick: pick["smart_net"], reverse=True)
    for pick in ranked[max_positions:]:
        audit.append({"symbol": pick["symbol"], "stage": "RANK", "reason": "DI_LUAR_BATAS_POSISI"})
    return ranked[:max_positions], audit


def select_candidates(
    picks: list[dict[str, Any]], signal_date: datetime.date,
    prices: dict[str, dict[datetime.date, dict[str, float]]], *,
    max_margin_pct: float, max_positions: int,
) -> list[dict[str, Any]]:
    return rank_candidates(picks, signal_date, prices, max_margin_pct=max_margin_pct, max_positions=max_positions)[0]


def unavailable_trade_reason(signal_date: datetime.date, bars: dict[datetime.date, dict[str, float]], broker_average: float, hold_sessions: int = 5) -> str | None:
    if broker_average <= 0:
        return "AVERAGE_BROKER_TIDAK_TERSEDIA"
    if any(date not in bars for date in next_idx_sessions(signal_date, hold_sessions)):
        return f"OHLC_{hold_sessions}_SESI_TIDAK_LENGKAP"
    return None


def simulate_trade(
    signal_date: datetime.date, bars: dict[datetime.date, dict[str, float]], broker_average: float,
    *, fee_buy_pct: float, fee_sell_pct: float, slippage_ticks: int, hold_sessions: int = 5,
    take_profit_pct: float = 7.0, static_stop_loss_pct: float | None = None,
) -> dict[str, float | str | datetime.date] | None:
    """Conservative IDX-session trade: next open entry, TP/SL, then time exit."""
    if unavailable_trade_reason(signal_date, bars, broker_average, hold_sessions):
        return None
    future_dates = next_idx_sessions(signal_date, hold_sessions)
    future = [bars[date] for date in future_dates]
    entry_signal = future[0]["open"]
    entry = _paper_fill(entry_signal, True, slippage_ticks)
    target = round_to_idx_tick(entry * (1 + take_profit_pct / 100))
    stop = round_to_idx_tick(entry * (1 - static_stop_loss_pct / 100)) if static_stop_loss_pct else round_to_idx_tick(min(entry * 0.95, broker_average * 0.975))
    if stop >= entry:
        stop = max(get_idx_tick_size(entry), entry - get_idx_tick_size(entry))

    exit_signal = future[-1]["close"]
    exit_date = future_dates[-1]
    outcome = "TIME_EXIT"
    for date, bar in zip(future_dates, future):
        opening, high, low = bar["open"], bar["high"], bar["low"]
        if opening <= stop:
            exit_signal, exit_date, outcome = opening, date, "STOP_GAP"
            break
        if opening >= target:
            exit_signal, exit_date, outcome = opening, date, "TAKE_PROFIT_GAP"
            break
        if low <= stop and high >= target:
            exit_signal, exit_date, outcome = stop, date, "STOP_AMBIGUOUS"
            break
        if low <= stop:
            exit_signal, exit_date, outcome = stop, date, "STOP_LOSS"
            break
        if high >= target:
            exit_signal, exit_date, outcome = target, date, "TAKE_PROFIT"
            break

    exit_price = _paper_fill(exit_signal, False, slippage_ticks)
    net_return_pct = (exit_price * (1 - fee_sell_pct / 100) / (entry * (1 + fee_buy_pct / 100)) - 1) * 100
    return {
        "entry_date": future_dates[0], "entry": entry, "exit_date": exit_date, "exit": exit_price,
        "target": target, "stop": stop, "outcome": outcome, "net_return_pct": net_return_pct,
        "max_up_pct": (max(bar["high"] for bar in future) / entry - 1) * 100,
        "max_down_pct": (min(bar["low"] for bar in future) / entry - 1) * 100,
    }


def _summary(values: list[float]) -> dict[str, float | int]:
    gross_profit = sum(value for value in values if value > 0)
    gross_loss = -sum(value for value in values if value < 0)
    return {
        "count": len(values),
        "mean": statistics.mean(values) if values else 0.0,
        "median": statistics.median(values) if values else 0.0,
        "win_rate": sum(value > 0 for value in values) / len(values) * 100 if values else 0.0,
        "gross_profit": gross_profit,
        "gross_loss": gross_loss,
        "profit_factor": gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0),
    }


def _profit_factor_label(stats: dict[str, float | int]) -> str:
    value = float(stats["profit_factor"])
    return "∞" if value == float("inf") else f"{value:.2f}"


def validation_health(values: list[float], *, min_profit_factor: float, min_trades: int) -> tuple[bool, str, dict[str, float | int]]:
    """Fail closed unless untouched validation clears sample and PF thresholds."""
    stats = _summary(values)
    if stats["count"] < min_trades:
        return False, f"trade validasi {stats['count']} < minimum {min_trades}", stats
    if float(stats["profit_factor"]) < min_profit_factor:
        return False, f"profit factor {_profit_factor_label(stats)} < minimum {min_profit_factor:.2f}", stats
    return True, "profit factor dan ukuran sampel memenuhi batas", stats


def generate_report(folds: list[dict[str, Any]], start: datetime.date, end: datetime.date, *, max_margin_pct: float, max_positions: int, fee_buy_pct: float, fee_sell_pct: float, slippage_ticks: int, min_coverage_pct: float, validation_from: datetime.date | None = None, min_profit_factor: float = DEFAULT_MIN_PROFIT_FACTOR, min_validation_trades: int = DEFAULT_MIN_VALIDATION_TRADES, hold_sessions: int = 5, take_profit_pct: float = 7.0, static_stop_loss_pct: float | None = None) -> str:
    trades = [trade for fold in folds for trade in fold["trades"]]
    summary = _summary([float(trade["net_return_pct"]) for trade in trades])
    lines = [
        "# 📈 WALK-FORWARD SWING MACRO — EOD (TANPA L2)",
        f"**Periode sinyal:** `{start}` s/d `{end}`",
        f"**Entry:** open sesi berikutnya + slippage adverse; TP `+{take_profit_pct:.1f}%`; SL {'`-' + f'{static_stop_loss_pct:.1f}' + '%` dari entry' if static_stop_loss_pct else 'di bawah average buy broker/entry'}; time exit setelah `{hold_sessions}` sesi.",
        f"**Filter:** margin harga ≤ `{max_margin_pct:.1f}%` di atas average buy broker | maksimal `{max_positions}` posisi per minggu | cakupan Top-20 minimal `{min_coverage_pct:.1f}%`.",
        f"**Friction:** fee beli `{fee_buy_pct:.2f}%`, fee jual `{fee_sell_pct:.2f}%`, slippage `{slippage_ticks}` tick per sisi.",
        f"**Harga:** `{PRICE_SOURCE}`; bar tersimpan di `stockbit_ws.market_daily_prices`.",
        "**Konservatif:** jika TP dan SL sama-sama tersentuh dalam candle harian, hasil dihitung sebagai SL. Corporate action, antrean, partial fill, dan market impact belum dimodelkan.",
        "",
        f"## Ringkasan ({summary['count']} trade terukur)",
        "",
        f"- Net return {hold_sessions} sesi: rata-rata **{summary['mean']:+.2f}%**, median **{summary['median']:+.2f}%**.",
        f"- Win rate net: **{summary['win_rate']:.1f}%**.",
        f"- Gross profit/loss: **{float(summary['gross_profit']):+.2f}% / -{float(summary['gross_loss']):.2f}%**; profit factor: **{_profit_factor_label(summary)}**.",
        "",
        "| Minggu sinyal | Cakupan min/avg | Macro | OHLC sinyal | Posisi | Trade | Audit | Net mean | Median | Win rate |",
        "|:-------------:|:---------------:|------:|------------:|-------:|------:|:------|---------:|-------:|---------:|",
    ]
    for fold in folds:
        stats = _summary([float(trade["net_return_pct"]) for trade in fold["trades"]])
        coverage = f"{fold['coverage_min']:.1f}/{fold['coverage_avg']:.1f}%"
        lines.append(f"| {fold['date']} | {coverage} | {fold['macro_count']} | {fold['price_count']} | {fold['position_count']} | {stats['count']} | {len(fold['audit'])} | {stats['mean']:+.2f}% | {stats['median']:+.2f}% | {stats['win_rate']:.1f}% |")
    if validation_from:
        training = [float(trade["net_return_pct"]) for fold in folds if fold["date"] < validation_from for trade in fold["trades"]]
        validation = [float(trade["net_return_pct"]) for fold in folds if fold["date"] >= validation_from for trade in fold["trades"]]
        train_stats, validation_stats = _summary(training), _summary(validation)
        passed, reason, _ = validation_health(validation, min_profit_factor=min_profit_factor, min_trades=min_validation_trades)
        lines.extend([
            "", "## Split walk-forward", "",
            "Parameter yang sama dipakai di kedua periode; hasil validasi tidak dipakai untuk tuning ulang.",
            "| Periode | Trade | Net mean | Median | Win rate | Profit factor |",
            "|:--|--:|--:|--:|--:|--:|",
            f"| Kalibrasi sebelum {validation_from} | {train_stats['count']} | {train_stats['mean']:+.2f}% | {train_stats['median']:+.2f}% | {train_stats['win_rate']:.1f}% | {_profit_factor_label(train_stats)} |",
            f"| Validasi mulai {validation_from} | {validation_stats['count']} | {validation_stats['mean']:+.2f}% | {validation_stats['median']:+.2f}% | {validation_stats['win_rate']:.1f}% | {_profit_factor_label(validation_stats)} |",
            "",
            "## Quality gate profit factor",
            "",
            f"- Ambang: profit factor validasi ≥ **{min_profit_factor:.2f}** dan minimal **{min_validation_trades}** trade.",
            f"- Status: **{'LOLOS — boleh dilanjutkan ke paper trading' if passed else 'BLOKIR — research only'}** ({reason}).",
        ])
    else:
        lines.extend(["", "## Quality gate profit factor", "", "- Status: **BELUM TERVERIFIKASI — research only**. Jalankan dengan `--validation-from` sebelum memakai hasil sebagai sinyal."])
    audit = [item | {"date": fold["date"]} for fold in folds for item in fold["audit"]]
    if audit:
        lines.extend(["", "## Audit kandidat tidak terpilih / tidak terukur", "", "| Minggu | Saham | Tahap | Alasan |", "|:--|:--|:--|:--|"])
        lines.extend(f"| {item['date']} | {item['symbol']} | {item['stage']} | {item['reason']} |" for item in audit)
    lines.extend(["", "## Detail trade", "", "| Minggu | Saham | Broker | Margin | Entry | Exit | TP | SL | Net | Hasil |", "|:------:|:-----:|:------:|-------:|------:|-----:|---:|---:|----:|:------|"])
    for fold in folds:
        for trade in fold["trades"]:
            lines.append(f"| {fold['date']} | {trade['symbol']} | {trade['top_buyer']} | {trade['margin_pct']:+.1f}% | {trade['entry']:,.0f} | {trade['exit']:,.0f} | {trade['target']:,.0f} | {trade['stop']:,.0f} | {trade['net_return_pct']:+.2f}% | {trade['outcome']} |")
    return "\n".join(lines)


def run_backtest(start: datetime.date, end: datetime.date, *, auto_fetch_eod: bool = True, refresh_prices: bool = False, max_margin_pct: float = 6.0, max_positions: int = 5, fee_buy_pct: float = 0.15, fee_sell_pct: float = 0.25, slippage_ticks: int = 1, min_coverage_pct: float = DEFAULT_MIN_COVERAGE_PCT, validation_from: datetime.date | None = None, min_profit_factor: float = DEFAULT_MIN_PROFIT_FACTOR, min_validation_trades: int = DEFAULT_MIN_VALIDATION_TRADES, hold_sessions: int = 5, take_profit_pct: float = 7.0, static_stop_loss_pct: float | None = None) -> tuple[list[dict[str, Any]], str]:
    if start > end or max_positions < 1 or hold_sessions < 1 or take_profit_pct <= 0 or static_stop_loss_pct is not None and not 0 < static_stop_loss_pct < 100 or slippage_ticks < 0 or not 0 <= min_coverage_pct <= 100 or min_profit_factor <= 0 or min_validation_trades < 1 or validation_from and not start <= validation_from <= end:
        raise ValueError("Parameter backtest tidak valid")
    folds = []
    for signal_date in week_ends(start, end, hold_sessions):
        print(f"📊 [EOD] Membentuk shortlist minggu berakhir {signal_date}...")
        picks, dates = run_swing_confluence(signal_date.isoformat(), auto_fetch_eod=auto_fetch_eod, auto_fetch_l2=False, macro_only=True, macro_limit=None)
        if len(dates) < 5:
            print(f"⚠️ {signal_date}: EOD berurutan belum tersedia; minggu dilewati.")
            continue
        coverage_min, coverage_avg = eod_coverage(dates)
        folds.append({"date": datetime.date.fromisoformat(dates[-1]), "dates": dates, "picks": picks, "macro_count": len(picks), "coverage_min": coverage_min, "coverage_avg": coverage_avg, "price_count": 0, "position_count": 0, "trades": [], "audit": []})

    symbols = sorted({pick["symbol"] for fold in folds for pick in fold["picks"]})
    if symbols:
        cache_start = first_idx_session_on_or_after(start)
        cache_end = last_idx_session_on_or_before(end)
        conn = connect_database(readonly=True)
        try:
            cached = {row["symbol"] for row in conn.execute(
                """SELECT symbol FROM stockbit_ws.market_daily_prices
                   WHERE symbol = ANY(%s) AND date BETWEEN %s AND %s
                   GROUP BY symbol HAVING min(date) <= %s AND max(date) >= %s""",
                (symbols, start, end, cache_start, cache_end),
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
        if fold["coverage_min"] < min_coverage_pct:
            print(f"⚠️ {fold['date']}: cakupan Top-20 {fold['coverage_min']:.1f}% < {min_coverage_pct:.1f}%; minggu dilewati.")
            fold["audit"].extend({"symbol": pick["symbol"], "stage": "DATA", "reason": "CAKUPAN_BROKER_DI_BAWAH_BATAS"} for pick in fold["picks"])
            continue
        candidates, audit = rank_candidates(fold["picks"], fold["date"], prices, max_margin_pct=max_margin_pct, max_positions=max_positions)
        fold["audit"].extend(audit)
        fold["price_count"] = sum(1 for pick in fold["picks"] if pick["symbol"] in prices and fold["date"] in prices[pick["symbol"]])
        fold["position_count"] = len(candidates)
        for pick in candidates:
            trade = simulate_trade(fold["date"], prices.get(pick["symbol"], {}), float(pick["top_buyer_avg"]), fee_buy_pct=fee_buy_pct, fee_sell_pct=fee_sell_pct, slippage_ticks=slippage_ticks, hold_sessions=hold_sessions, take_profit_pct=take_profit_pct, static_stop_loss_pct=static_stop_loss_pct)
            if trade:
                fold["trades"].append({**pick, **trade})
            else:
                reason = unavailable_trade_reason(fold["date"], prices.get(pick["symbol"], {}), float(pick["top_buyer_avg"]), hold_sessions)
                fold["audit"].append({"symbol": pick["symbol"], "stage": "SIMULASI", "reason": reason or "TRADE_TIDAK_TERUKUR"})
    return folds, generate_report(folds, start, end, max_margin_pct=max_margin_pct, max_positions=max_positions, fee_buy_pct=fee_buy_pct, fee_sell_pct=fee_sell_pct, slippage_ticks=slippage_ticks, min_coverage_pct=min_coverage_pct, validation_from=validation_from, min_profit_factor=min_profit_factor, min_validation_trades=min_validation_trades, hold_sessions=hold_sessions, take_profit_pct=take_profit_pct, static_stop_loss_pct=static_stop_loss_pct)


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward swing macro EOD tanpa L2")
    parser.add_argument("--from", dest="start", required=True, help="Mulai minggu pertama, YYYY-MM-DD")
    parser.add_argument("--to", dest="end", required=True, help="Tanggal akhir harga evaluasi, YYYY-MM-DD")
    parser.add_argument("--no-eod", action="store_true", help="Jangan backfill EOD yang belum lengkap")
    parser.add_argument("--refresh-prices", action="store_true", help="Ambil ulang OHLC harian dari sumber harga")
    parser.add_argument("--max-margin", type=float, default=6.0, help="Margin maksimum di atas average buy broker (default: 6%%)")
    parser.add_argument("--max-positions", type=int, default=5, help="Maksimal posisi per minggu (default: 5)")
    parser.add_argument("--fee-buy", type=float, default=0.15, help="Fee beli persen (default: 0.15%%)")
    parser.add_argument("--fee-sell", type=float, default=0.25, help="Fee jual persen (default: 0.25%%)")
    parser.add_argument("--slippage-ticks", type=int, default=1, help="Slippage adverse per sisi dalam tick IDX (default: 1)")
    parser.add_argument("--min-coverage", type=float, default=DEFAULT_MIN_COVERAGE_PCT, help="Cakupan nilai Top-20 minimum persen (default: 80)")
    parser.add_argument("--validation-from", help="Mulai periode validasi YYYY-MM-DD; parameter tidak dituning ulang")
    parser.add_argument("--min-profit-factor", type=float, default=DEFAULT_MIN_PROFIT_FACTOR, help="Profit factor minimum pada validasi (default: 1.20)")
    parser.add_argument("--min-validation-trades", type=int, default=DEFAULT_MIN_VALIDATION_TRADES, help="Trade validasi minimum untuk quality gate (default: 30)")
    parser.add_argument("--enforce-profit-factor", action="store_true", help="Keluar dengan status gagal bila quality gate tidak lolos; wajib --validation-from")
    parser.add_argument("--hold-sessions", type=int, default=5, help="Maksimum sesi IDX yang ditahan (default: 5)")
    parser.add_argument("--take-profit", type=float, default=7.0, help="Target profit persen dari entry (default: 7%%)")
    parser.add_argument("--stop-loss", type=float, help="Stop loss statis persen dari entry; default tetap stop berbasis broker")
    args = parser.parse_args()
    try:
        start = datetime.date.fromisoformat(args.start)
        end = datetime.date.fromisoformat(args.end)
    except ValueError:
        parser.error("--from dan --to harus YYYY-MM-DD")
    try:
        validation_from = datetime.date.fromisoformat(args.validation_from) if args.validation_from else None
    except ValueError:
        parser.error("--validation-from harus YYYY-MM-DD")
    if args.enforce_profit_factor and not validation_from:
        parser.error("--enforce-profit-factor membutuhkan --validation-from")
    try:
        folds, report = run_backtest(start, end, auto_fetch_eod=not args.no_eod, refresh_prices=args.refresh_prices, max_margin_pct=args.max_margin, max_positions=args.max_positions, fee_buy_pct=args.fee_buy, fee_sell_pct=args.fee_sell, slippage_ticks=args.slippage_ticks, min_coverage_pct=args.min_coverage, validation_from=validation_from, min_profit_factor=args.min_profit_factor, min_validation_trades=args.min_validation_trades, hold_sessions=args.hold_sessions, take_profit_pct=args.take_profit, static_stop_loss_pct=args.stop_loss)
    except ValueError as exc:
        parser.error(str(exc))

    out_dir = Path("reports")
    out_dir.mkdir(exist_ok=True)
    tag = "" if (args.hold_sessions, args.take_profit, args.stop_loss) == (5, 7.0, None) else f"_h{args.hold_sessions}_tp{args.take_profit:g}" + (f"_sl{args.stop_loss:g}" if args.stop_loss else "_broker_sl")
    out_file = out_dir / f"swing_macro_backtest_{start:%Y%m%d}_{end:%Y%m%d}{tag}.md"
    out_file.write_text(report, encoding="utf-8")
    measured = sum(len(fold["trades"]) for fold in folds)
    print(f"✅ {len(folds)} minggu dan {measured} trade terukur. Laporan: {out_file}")
    if args.enforce_profit_factor:
        validation = [float(trade["net_return_pct"]) for fold in folds if fold["date"] >= validation_from for trade in fold["trades"]]
        passed, reason, _ = validation_health(validation, min_profit_factor=args.min_profit_factor, min_trades=args.min_validation_trades)
        if not passed:
            print(f"⛔ Quality gate: {reason}.")
            raise SystemExit(2)


if __name__ == "__main__":
    main()
