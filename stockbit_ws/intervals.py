"""Time-series interval analysis (1s, 5s, 30s) for recorded market data.

Computes:
- OHLC price action and price change.
- Volume (lot) and transaction value (IDR).
- HAKA vs HAKI volume, value, proportion (%), and Net Flow.
- Trade velocity (unique trades / interval).
- Order book spread and top-1/top-3 depth imbalance.
- Strict pre-connection snapshot separation.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import sys
from typing import Any

from .events import timestamp_text, utc_time
from .orderbook import format_number
from .postgres import connect_database, verify_schema
from .recording import RecordingError
from .subscription import SYMBOL_PATTERN

_WIB = timezone(timedelta(hours=7), "WIB")


def load_session_trades_and_books(conn, session_id: str, symbol: str | None = None):
    """Load one closed session and partition canonical trades without mutating it."""
    session = conn.execute(
        "SELECT * FROM stockbit_ws.sessions WHERE id = %s", (session_id,)
    ).fetchone()
    if not session:
        raise ValueError(f"Sesi {session_id} tidak ditemukan.")

    session_symbol = session["symbol"]
    if session["status"] not in ("STOPPED", "COMPLETED") or session["ended_at"] is None:
        raise ValueError("Analisis interval hanya menerima sesi tertutup STOPPED/COMPLETED.")
    if session_symbol == "*":
        candidate = (symbol or "").strip().upper()
        if SYMBOL_PATTERN.fullmatch(candidate) is None:
            raise ValueError("Sesi wildcard wajib memakai --symbol, contoh: --symbol BUMI.")
        target_symbol = candidate
    else:
        target_symbol = session_symbol
        if symbol is not None and symbol.strip().upper() != session_symbol:
            raise ValueError(f"Sesi dedicated hanya berisi symbol {session_symbol}.")
    started_at = session["started_at"]
    ended_at = session["ended_at"]

    # 1. Fetch Done events
    q_trades = """
        SELECT seq, received_at, elapsed_ms, payload
        FROM stockbit_ws.events
        WHERE session_id = %s AND kind = 'done'
        ORDER BY seq ASC
    """
    rows_trades = conn.execute(q_trades, (session_id,)).fetchall()

    snapshot_trades = []
    live_trades = []
    excluded_trades = []
    seen: dict[tuple[Any, ...], tuple[Any, ...]] = {}
    duplicate_copies = 0
    missing_timestamp = 0

    for r in rows_trades:
        rec_at = r["received_at"]
        for batch_index, t in enumerate(r["payload"].get("trades", [])):
            code = t.get("symbol")
            if code != target_symbol:
                continue

            tid = t.get("tradeId")
            ts_str = t.get("timestamp")
            if not ts_str:
                missing_timestamp += 1
                continue
            ex_ts = utc_time(ts_str)

            # Deduplication key
            if tid is not None:
                key = (code, tid)
            else:
                key = (code, ts_str, t.get("price"), t.get("shares"), t.get("sideCode"))

            fingerprint = (ts_str, t.get("price"), t.get("shares"), t.get("sideCode"))
            previous = seen.get(key)
            if previous is not None:
                if previous != fingerprint:
                    raise ValueError(f"Trade ID konflik untuk {code}; analisis dihentikan.")
                duplicate_copies += 1
                continue
            seen[key] = fingerprint

            trade_obj = {
                "symbol": code,
                "tradeId": tid,
                "price": float(t.get("price", 0.0)),
                "shares": float(t.get("shares", 0.0)),
                "lot": float(t.get("lot", t.get("shares", 0.0) / 100)),
                "sideCode": int(t.get("sideCode", 0)),
                "value": float(t.get("transactionValue", t.get("price", 0.0) * t.get("shares", 0.0))),
                "exchange_time": ex_ts,
                "received_at": rec_at,
                "seq": r["seq"],
                "batch_index": batch_index,
            }

            # Separate snapshot: trades executed before session connection started
            if ex_ts < started_at:
                snapshot_trades.append(trade_obj)
            elif ex_ts >= ended_at:
                trade_obj["excluded_reason"] = "event_time_after_session"
                excluded_trades.append(trade_obj)
            elif rec_at < started_at or rec_at >= ended_at:
                trade_obj["excluded_reason"] = "received_outside_session"
                excluded_trades.append(trade_obj)
            else:
                live_trades.append(trade_obj)

    live_trades.sort(key=lambda t: (t["exchange_time"], t["seq"], t["batch_index"]))

    # 2. Fetch Order Book updates (only for dedicated sessions)
    book_updates = []
    if session_symbol != "*":
        q_books = """
            SELECT seq, received_at, elapsed_ms, kind, payload
            FROM stockbit_ws.events
            WHERE session_id = %s AND kind IN ('book', 'connection')
            ORDER BY seq ASC
        """
        rows_books = conn.execute(q_books, (session_id,)).fetchall()
        for r in rows_books:
            if r["kind"] == "connection":
                book_updates.append({
                    "seq": r["seq"], "received_at": r["received_at"],
                    "side": "CONNECTION", "state": r["payload"].get("state"), "levels": [],
                })
            else:
                p = r["payload"]
                if p.get("symbol") != target_symbol:
                    continue
                book_updates.append({
                    "seq": r["seq"], "received_at": r["received_at"],
                    "side": p.get("side"), "levels": p.get("levels", []),
                })

    return {
        "session": session,
        "target_symbol": target_symbol,
        "started_at": started_at,
        "ended_at": ended_at,
        "snapshot_trades": snapshot_trades,
        "live_trades": live_trades,
        "book_updates": book_updates,
        "duplicate_copies": duplicate_copies,
        "missing_timestamp": missing_timestamp,
        "excluded_trades": excluded_trades,
    }


def build_interval_bars(
    live_trades: list[dict[str, Any]],
    book_updates: list[dict[str, Any]],
    interval_seconds: int,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    stale_after: float = 15.0,
) -> list[dict[str, Any]]:
    """Aggregate event-time trades and receive-time book snapshots into fixed buckets."""
    if interval_seconds <= 0:
        raise ValueError("interval_seconds harus lebih besar dari 0.")
    if not math.isfinite(stale_after) or stale_after <= 0:
        raise ValueError("stale_after harus lebih besar dari 0.")

    ordered_trades = sorted(
        live_trades,
        key=lambda trade: (
            trade["exchange_time"], trade.get("seq", 0), trade.get("batch_index", 0)
        ),
    )
    buckets: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for t in ordered_trades:
        ex_ts = t["exchange_time"]
        epoch_sec = int(ex_ts.timestamp())
        bucket_sec = (epoch_sec // interval_seconds) * interval_seconds
        buckets[bucket_sec].append(t)

    if start_time is None:
        start_time = ordered_trades[0]["exchange_time"] if ordered_trades else None
    if end_time is None:
        end_time = ordered_trades[-1]["exchange_time"] + timedelta(microseconds=1) if ordered_trades else None
    if start_time is None or end_time is None:
        return []
    start_time, end_time = utc_time(start_time), utc_time(end_time)
    if end_time <= start_time:
        return []

    book_clock_valid = all(
        book_updates[index]["received_at"] >= book_updates[index - 1]["received_at"]
        for index in range(1, len(book_updates))
    )
    book_index = 0
    curr_bid = []
    curr_offer = []
    last_bid_at = last_offer_at = None
    connection_state = None

    first_bucket = (int(start_time.timestamp()) // interval_seconds) * interval_seconds
    last_instant = end_time - timedelta(microseconds=1)
    last_bucket = (int(last_instant.timestamp()) // interval_seconds) * interval_seconds

    bars = []
    for b_sec in range(first_bucket, last_bucket + 1, interval_seconds):
        t_list = buckets.get(b_sec, [])
        b_start = datetime.fromtimestamp(b_sec, tz=timezone.utc)
        b_end = b_start + timedelta(seconds=interval_seconds)
        observed_start = max(b_start, start_time)
        observed_end = min(b_end, end_time)
        observed_seconds = max(0.0, (observed_end - observed_start).total_seconds())

        # End is exclusive: an update exactly at the boundary belongs to the next bucket.
        while book_clock_valid and book_index < len(book_updates):
            bu = book_updates[book_index]
            if bu["received_at"] >= observed_end:
                break
            if bu["side"] == "CONNECTION":
                connection_state = bu.get("state")
                if connection_state == "DISCONNECTED":
                    curr_bid = curr_offer = []
                    last_bid_at = last_offer_at = None
            elif bu["side"] == "BID":
                curr_bid = sorted(bu["levels"], key=lambda level: level["price"], reverse=True)
                last_bid_at = bu["received_at"]
            elif bu["side"] == "OFFER":
                curr_offer = sorted(bu["levels"], key=lambda level: level["price"])
                last_offer_at = bu["received_at"]
            book_index += 1

        prices = [t["price"] for t in t_list]
        open_price = prices[0] if prices else None
        close_price = prices[-1] if prices else None
        high_price = max(prices) if prices else None
        low_price = min(prices) if prices else None
        price_change = close_price - open_price if prices else None
        price_change_pct = (price_change / open_price * 100) if prices and open_price > 0 else None
        total_lot = sum(t["lot"] for t in t_list)
        total_val = sum(t["value"] for t in t_list)
        haka_lot = sum(t["lot"] for t in t_list if t["sideCode"] == 1)
        haki_lot = sum(t["lot"] for t in t_list if t["sideCode"] == 2)
        haka_val = sum(t["value"] for t in t_list if t["sideCode"] == 1)
        haki_val = sum(t["value"] for t in t_list if t["sideCode"] == 2)
        haka_pct = round(haka_val / total_val * 100, 2) if total_val > 0 else None
        haki_pct = round(haki_val / total_val * 100, 2) if total_val > 0 else None
        net_flow_val = haka_val - haki_val
        net_flow_lot = haka_lot - haki_lot

        book_info = None
        book_invalid_reason = None
        if book_updates and not book_clock_valid:
            book_invalid_reason = "non_monotonic_received_at"
        elif book_updates and connection_state == "DISCONNECTED":
            book_invalid_reason = "disconnected"
        elif book_updates and (not curr_bid or not curr_offer or last_bid_at is None or last_offer_at is None):
            book_invalid_reason = "missing_side"
        elif curr_bid and curr_offer and last_bid_at is not None and last_offer_at is not None:
            bid_age = (observed_end - last_bid_at).total_seconds()
            offer_age = (observed_end - last_offer_at).total_seconds()
            if bid_age > stale_after or offer_age > stale_after:
                book_invalid_reason = "stale"
            else:
                best_bid = curr_bid[0]["price"]
                best_offer = curr_offer[0]["price"]
                spread = best_offer - best_bid
                crossed = spread < 0
                mid = (best_bid + best_offer) / 2
                b1_lot = curr_bid[0]["lot"]
                o1_lot = curr_offer[0]["lot"]
                b3_lot = sum(level["lot"] for level in curr_bid[:3])
                o3_lot = sum(level["lot"] for level in curr_offer[:3])
                book_info = {
                    "best_bid": best_bid,
                    "best_offer": best_offer,
                    "spread_pts": None if crossed else spread,
                    "spread_bps": None if crossed or mid <= 0 else round(spread / mid * 10000, 2),
                    "top1_bid_lot": b1_lot,
                    "top1_offer_lot": o1_lot,
                    "imbalance_top1": None if crossed else round((b1_lot - o1_lot) / max(1.0, b1_lot + o1_lot), 3),
                    "top3_bid_lot": b3_lot,
                    "top3_offer_lot": o3_lot,
                    "imbalance_top3": None if crossed else round((b3_lot - o3_lot) / max(1.0, b3_lot + o3_lot), 3),
                    "bid_age_ms": round(bid_age * 1000),
                    "offer_age_ms": round(offer_age * 1000),
                    "locked": spread == 0,
                    "crossed": crossed,
                    "time_basis": "received_at",
                }
                if crossed:
                    book_invalid_reason = "crossed"

        wib_time = b_start.astimezone(_WIB).strftime("%H:%M:%S")
        bars.append({
            "bucket_sec": b_sec,
            "time_wib": wib_time,
            "observed_seconds": observed_seconds,
            "partial_window": observed_seconds < interval_seconds,
            "trade_count": len(t_list),
            "trades_per_second": len(t_list) / observed_seconds if observed_seconds else 0.0,
            "open": open_price,
            "high": high_price,
            "low": low_price,
            "close": close_price,
            "price_change": price_change,
            "price_change_pct": round(price_change_pct, 2) if price_change_pct is not None else None,
            "total_lot": total_lot,
            "total_value_idr": total_val,
            "haka_lot": haka_lot,
            "haka_value_idr": haka_val,
            "haka_pct": haka_pct,
            "haki_lot": haki_lot,
            "haki_value_idr": haki_val,
            "haki_pct": haki_pct,
            "net_flow_val_idr": net_flow_val,
            "net_flow_lot": net_flow_lot,
            "order_book": book_info,
            "book_invalid_reason": book_invalid_reason,
        })

    return bars


def extract_activity_patterns(bars: list[dict[str, Any]]) -> dict[str, Any]:
    """Identify significant activity bursts, volume spikes, and order book dynamics."""
    if not bars:
        return {}

    active_bars = [bar for bar in bars if bar["trade_count"] > 0]
    if not active_bars:
        return {
            "top_inflows": [], "top_outflows": [], "top_velocities": [],
            "depth_imbalance_correlation": {
                "evaluated_instances": 0, "consistent_instances": 0,
                "alignment_rate_pct": None,
            },
        }

    # Descriptive ranking only; HAKA/HAKI does not identify investor intent.
    inflow_sorted = sorted(active_bars, key=lambda b: b["net_flow_val_idr"], reverse=True)
    top_inflows = inflow_sorted[:5]

    # Top 5 Outflow Bursts (highest Net Outflow / HAKI dominance)
    outflow_sorted = sorted(active_bars, key=lambda b: b["net_flow_val_idr"])
    top_outflows = outflow_sorted[:5]

    # Top 5 Velocity Spikes
    velocity_sorted = sorted(active_bars, key=lambda b: b["trade_count"], reverse=True)
    top_velocities = velocity_sorted[:5]

    # Imbalance vs Next Bar Price Change Correlation
    imbalance_predict_wins = 0
    imbalance_predict_total = 0
    for i in range(len(bars) - 1):
        ob = bars[i].get("order_book")
        next_close = bars[i + 1]["close"]
        if ob and ob.get("imbalance_top1") is not None and bars[i]["close"] is not None and next_close is not None:
            imb = ob["imbalance_top1"]
            next_dp = next_close - bars[i]["close"]
            if abs(imb) >= 0.2 and next_dp != 0:
                imbalance_predict_total += 1
                if (imb > 0 and next_dp > 0) or (imb < 0 and next_dp < 0):
                    imbalance_predict_wins += 1

    imb_win_rate = (
        round(imbalance_predict_wins / imbalance_predict_total * 100, 2)
        if imbalance_predict_total > 0
        else None
    )

    return {
        "top_inflows": top_inflows,
        "top_outflows": top_outflows,
        "top_velocities": top_velocities,
        "depth_imbalance_correlation": {
            "evaluated_instances": imbalance_predict_total,
            "consistent_instances": imbalance_predict_wins,
            "alignment_rate_pct": imb_win_rate,
        },
    }


def format_intervals_table(bars: list[dict[str, Any]], has_book: bool = True) -> str:
    """Format bars into a clean markdown table."""
    headers = [
        "Waktu (WIB)", "Trades", "Close", "ΔP", "Volume (Lot)", "Nilai (Rp)",
        "HAKA %", "HAKI %", "Net Flow (Rp)",
    ]
    if has_book:
        headers.extend(["Spread (pts)", "Top1 Imb", "Top3 Imb"])

    lines = []
    lines.append("| " + " | ".join(headers) + " |")
    lines.append("|" + "|".join(["---" for _ in headers]) + "|")

    for b in bars:
        net_val = b["net_flow_val_idr"]
        net_str = ("+" if net_val > 0 else "") + format_number(net_val, 0).replace(",", ".")
        price_change = b["price_change"]
        dp_str = "-" if price_change is None else ("+" if price_change > 0 else "") + f"{price_change:.1f}"

        row = [
            b["time_wib"],
            str(b["trade_count"]),
            "-" if b["close"] is None else f"{b['close']:.1f}",
            dp_str,
            format_number(b["total_lot"]),
            "Rp" + format_number(b["total_value_idr"], 0).replace(",", "."),
            "-" if b["haka_pct"] is None else f"{b['haka_pct']:.1f}%",
            "-" if b["haki_pct"] is None else f"{b['haki_pct']:.1f}%",
            net_str,
        ]

        if has_book:
            ob = b.get("order_book")
            if ob:
                row.extend([
                    "-" if ob["spread_pts"] is None else f"{ob['spread_pts']:.1f}",
                    "-" if ob["imbalance_top1"] is None else f"{ob['imbalance_top1']:+.2f}",
                    "-" if ob["imbalance_top3"] is None else f"{ob['imbalance_top3']:+.2f}",
                ])
            else:
                row.extend(["-", "-", "-"])

        lines.append("| " + " | ".join(row) + " |")

    return "\n".join(lines)


def generate_interval_report(
    session_id: str,
    interval_seconds: int = 5,
    symbol: str | None = None,
    all_intervals: bool = False,
) -> str:
    """Generate complete markdown report of activity patterns per interval."""
    conn = connect_database(readonly=True)
    try:
        verify_schema(conn)
        data = load_session_trades_and_books(conn, session_id, symbol)
    finally:
        conn.close()

    sym = data["target_symbol"]
    has_book = bool(data["book_updates"]) and sym != "*"
    snap_count = len(data["snapshot_trades"])
    live_count = len(data["live_trades"])
    excluded_count = len(data["excluded_trades"])

    intervals_to_run = [1, 5, 30] if all_intervals else [interval_seconds]

    lines = []
    lines.append(f"# Analisis Pola Aktivitas per Interval — {sym}")
    lines.append(f"**Session ID**: `{session_id}` | **Symbol**: `{sym}` | **Sesi**: {timestamp_text(data['started_at'])} s.d. {timestamp_text(data['ended_at'])}")
    lines.append(
        f"**Rekonsiliasi**: {snap_count} pra-sesi dipisahkan | {excluded_count} di luar batas sesi | "
        f"{data['duplicate_copies']} salinan duplikat | **{live_count} transaksi canonical dianalisis**."
    )
    lines.append("**Basis waktu**: transaksi memakai timestamp trade; order book memakai `received_at`. Keduanya tidak dianggap sebagai satu jam yang terbukti sinkron.")
    lines.append("")

    for iv in intervals_to_run:
        bars = build_interval_bars(
            data["live_trades"], data["book_updates"], iv,
            start_time=data["started_at"], end_time=data["ended_at"],
            stale_after=data["session"]["stale_after"],
        )
        patterns = extract_activity_patterns(bars)

        lines.append(f"## Interval {iv} Detik ({len(bars)} Bars)")
        active_count = sum(1 for bar in bars if bar["trade_count"] > 0)
        lines.append(f"Total {len(bars)} bucket waktu ({active_count} berisi transaksi).\n")

        # Top Inflows
        lines.append(f"### Pola Puncak Akumulasi (Top 5 Net Inflow HAKA)")
        lines.append(format_intervals_table(patterns["top_inflows"], has_book=has_book))
        lines.append("")

        # Top Outflows
        lines.append(f"### Pola Puncak Distribusi (Top 5 Net Outflow HAKI)")
        lines.append(format_intervals_table(patterns["top_outflows"], has_book=has_book))
        lines.append("")

        # Top Velocities
        lines.append(f"### Lonjakan Kecepatan Transaksi (Top 5 Velocity Spikes)")
        lines.append(format_intervals_table(patterns["top_velocities"], has_book=has_book))
        lines.append("")

        # Imbalance alignment
        imb_stat = patterns.get("depth_imbalance_correlation", {})
        if imb_stat.get("alignment_rate_pct") is not None:
            lines.append(f"> **Observasi Pola Buku Pesanan (Top-1 Imbalance vs Arah Harga Berikutnya):**")
            lines.append(
                f"> Dari {imb_stat['evaluated_instances']} interval dengan ketidakseimbangan antrean signifikan (|imb| $\\ge 0.2$), "
                f"sebanyak **{imb_stat['consistent_instances']} interval ({imb_stat['alignment_rate_pct']}%)** sejalan dengan arah perubahan harga pada interval berikutnya.\n"
            )

        # Sample recent intervals
        lines.append(f"### Sampel 10 Interval Terakhir")
        lines.append(format_intervals_table(bars[-10:], has_book=has_book))
        lines.append("")

    lines.append("## Kesimpulan Pola & Catatan Hipotesis")
    lines.append(
        f"1. **Pemisahan data**: {snap_count} transaksi pra-sesi dan {excluded_count} transaksi di luar batas tidak masuk agregasi.\n"
        "2. **HAKA/HAKI bersifat deskriptif**: net aggression tidak membuktikan akumulasi atau distribusi investor.\n"
        "3. **Order book bersifat as-of receive-time**: association terhadap bar berikutnya adalah hipotesis, bukan bukti prediksi atau profit."
    )

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analisis Pola Aktivitas per Interval (1s, 5s, 30s)")
    parser.add_argument("session_id", nargs="?", help="ID sesi yang ingin dianalisis")
    parser.add_argument("--interval", type=int, default=5, choices=[1, 5, 30], help="Ukuran interval detik (default: 5)")
    parser.add_argument("--all-intervals", action="store_true", help="Analisis sekaligus untuk 1s, 5s, dan 30s")
    parser.add_argument("--symbol", help="Kode saham spesifik (wajib jika menganalisis sesi wildcard *)")
    parser.add_argument("--output", help="Path file markdown output")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    conn = None
    try:
        conn = connect_database(readonly=True)
        verify_schema(conn)

        target_session = args.session_id
        if not target_session:
            row = conn.execute("SELECT id, symbol FROM stockbit_ws.sessions ORDER BY run_no DESC LIMIT 1").fetchone()
            if not row:
                print("Tidak ada sesi yang ditemukan.")
                return 1
            target_session = row["id"]

        print(f"Menganalisis pola aktivitas interval untuk sesi: {target_session}...")
        report_text = generate_interval_report(
            target_session,
            interval_seconds=args.interval,
            symbol=args.symbol,
            all_intervals=args.all_intervals,
        )

        print("\n" + report_text + "\n")

        # Save to markdown
        out_dir = Path("reports")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = Path(args.output) if args.output else out_dir / f"intervals_{target_session[:8]}.md"
        out_file.write_text(report_text, encoding="utf-8")
        print(f"Laporan pola aktivitas disimpan ke: {out_file.resolve()}")
        return 0

    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None and not conn.closed:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
