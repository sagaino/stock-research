"""Automated Recording Quality Report and Descriptive Market Analysis.

Produces reproducible reports answering:
1. True unique trades from DB (symbol + tradeId, fallback without ID, duplicate audit).
2. Strict comparison between dedicated symbol session and wildcard (*) session.
3. Recorder performance measurement (events/sec, burst deltas, storage verdict).
4. Descriptive market metrics (HAKA/HAKI volume/value, 1s/5s/30s velocity, spread, depth imbalance).
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import sys
from statistics import median
from typing import Any

from .events import timestamp_text, utc_time
from .orderbook import format_number
from .postgres import connect_database, verify_schema
from .recording import RecordingError


def analyze_session_uniqueness(conn, session_id: str) -> dict[str, Any]:
    """Audit trade uniqueness directly from database events, bypassing cache/window limits."""
    query = """
        SELECT seq, received_at, elapsed_ms, payload
        FROM stockbit_ws.events
        WHERE session_id = %s AND kind = 'done'
        ORDER BY seq ASC
    """
    rows = conn.execute(query, (session_id,)).fetchall()

    total_records = 0
    trades_with_id = 0
    trades_without_id = 0
    id_counts = Counter()
    fallback_counts = Counter()

    for row in rows:
        batch = row["payload"].get("trades", [])
        for t in batch:
            total_records += 1
            tid = t.get("tradeId")
            sym = t.get("symbol")
            if tid is not None:
                trades_with_id += 1
                id_counts[(sym, tid)] += 1
            else:
                trades_without_id += 1
                key = (
                    sym,
                    t.get("timestamp"),
                    t.get("price"),
                    t.get("shares"),
                    t.get("sideCode"),
                )
                fallback_counts[key] += 1

    unique_with_id = len(id_counts)
    unique_without_id = len(fallback_counts)
    total_unique = unique_with_id + unique_without_id

    duplicates_id = sum(c - 1 for c in id_counts.values() if c > 1)
    duplicates_fallback = sum(c - 1 for c in fallback_counts.values() if c > 1)
    total_duplicates = duplicates_id + duplicates_fallback

    # Top duplicates if any
    top_duplicates = []
    for (sym, tid), count in id_counts.most_common(5):
        if count > 1:
            top_duplicates.append({"symbol": sym, "tradeId": tid, "occurrences": count})

    return {
        "total_batches": len(rows),
        "total_trade_records": total_records,
        "unique_trades_total": total_unique,
        "trades_with_id": trades_with_id,
        "unique_with_id": unique_with_id,
        "trades_without_id": trades_without_id,
        "unique_without_id": unique_without_id,
        "duplicate_records": total_duplicates,
        "top_duplicates": top_duplicates,
    }


def compare_sessions_strict(
    conn, dedicated_id: str, wildcard_id: str, symbol: str
) -> dict[str, Any]:
    """Strict comparison between dedicated symbol session and wildcard session within exact overlap."""
    s_ded = conn.execute(
        "SELECT * FROM stockbit_ws.sessions WHERE id = %s", (dedicated_id,)
    ).fetchone()
    s_wld = conn.execute(
        "SELECT * FROM stockbit_ws.sessions WHERE id = %s", (wildcard_id,)
    ).fetchone()

    if not s_ded or not s_wld:
        raise ValueError("Sesi dedicated atau wildcard tidak ditemukan.")

    if dedicated_id == wildcard_id or s_ded["symbol"] != symbol or s_wld["symbol"] != "*":
        raise ValueError("Perbandingan memerlukan dedicated sesuai symbol dan wildcard berbeda.")
    if not s_ded["ended_at"] or not s_wld["ended_at"]:
        raise ValueError("Tutup kedua sesi sebelum audit.")

    # Transaction-time filter against local session boundaries; clocks uncorrected.
    start_overlap = max(s_ded["started_at"], s_wld["started_at"])
    end_overlap = min(
        s_ded["ended_at"] or datetime.now(timezone.utc),
        s_wld["ended_at"] or datetime.now(timezone.utc),
    )

    if start_overlap > end_overlap:
        raise ValueError("Tidak ada rentang waktu yang beririsan antara kedua sesi.")

    # Fetch trades for target symbol in both sessions
    def fetch_trades(sess_id):
        q = """
            SELECT seq, received_at, payload
            FROM stockbit_ws.events
            WHERE session_id = %s AND kind = 'done'
            ORDER BY seq ASC
        """
        result = {}
        no_id_list = []
        for r in conn.execute(q, (sess_id,)).fetchall():
            for t in r["payload"].get("trades", []):
                if t.get("symbol") != symbol:
                    continue
                ts_str = t.get("timestamp")
                ex_ts = datetime.fromisoformat(ts_str) if ts_str else None
                rec_ts = r["received_at"]
                if ex_ts and start_overlap <= ex_ts <= end_overlap:
                    tid = t.get("tradeId")
                    t_info = {
                        "tradeId": tid,
                        "symbol": symbol,
                        "price": t.get("price"),
                        "shares": t.get("shares"),
                        "lot": t.get("lot", t.get("shares", 0) / 100),
                        "sideCode": t.get("sideCode"),
                        "side": t.get("side"),
                        "exchange_time": ex_ts,
                        "received_at": rec_ts,
                        "delay_ms": round((rec_ts - ex_ts).total_seconds() * 1000, 1),
                    }
                    if tid is not None:
                        if tid in result:
                            if any(result[tid][key] != t_info[key] for key in ("price", "shares", "sideCode", "exchange_time")):
                                raise ValueError("Trade ID berulang memiliki nilai konflik.")
                        else:
                            result[tid] = t_info
                    else:
                        no_id_list.append(t_info)
        return result, no_id_list

    ded_trades, ded_no_id = fetch_trades(dedicated_id)
    wld_trades, wld_no_id = fetch_trades(wildcard_id)

    set_ded = set(ded_trades.keys())
    set_wld = set(wld_trades.keys())

    matched_ids = set_ded.intersection(set_wld)
    missing_in_wld = set_ded - set_wld
    missing_in_ded = set_wld - set_ded

    # Check value discrepancies among matched
    discrepancies = []
    for tid in matched_ids:
        t1, t2 = ded_trades[tid], wld_trades[tid]
        diffs = []
        if t1["price"] != t2["price"]:
            diffs.append(f"price ({t1['price']} vs {t2['price']})")
        if t1["shares"] != t2["shares"]:
            diffs.append(f"shares ({t1['shares']} vs {t2['shares']})")
        if t1["exchange_time"] != t2["exchange_time"]:
            diffs.append("timestamp")
        if t1["sideCode"] != t2["sideCode"]:
            diffs.append(f"side ({t1['sideCode']} vs {t2['sideCode']})")
        if diffs:
            discrepancies.append({"tradeId": tid, "differences": diffs})

    # Sample missing trades detail
    missing_in_wld_sample = [
        {
            "tradeId": tid,
            "exchange_time": timestamp_text(ded_trades[tid]["exchange_time"]),
            "received_at": timestamp_text(ded_trades[tid]["received_at"]),
            "price": ded_trades[tid]["price"],
            "lot": ded_trades[tid]["lot"],
            "side": ded_trades[tid]["side"],
        }
        for tid in sorted(missing_in_wld)[:10]
    ]

    # Delays comparison
    delays_ded = [t["delay_ms"] for t in ded_trades.values()]
    delays_wld = [t["delay_ms"] for t in wld_trades.values()]

    def stats(arr):
        if not arr:
            return {"mean": None, "min": None, "max": None, "median": None, "p95": None, "negative_count": 0}
        s = sorted(arr)
        return {
            "mean": round(sum(s) / len(s), 1),
            "median": round(median(s), 1),
            "negative_count": sum(value < 0 for value in s),
            "min": round(s[0], 1),
            "max": round(s[-1], 1),
            "p95": round(s[int(len(s) * 0.95)], 1),
        }

    return {
        "symbol": symbol,
        "overlap_window": {
            "start": timestamp_text(start_overlap),
            "end": timestamp_text(end_overlap),
            "duration_seconds": round((end_overlap - start_overlap).total_seconds(), 1),
        },
        "dedicated_total_unique": len(set_ded),
        "wildcard_total_unique": len(set_wld),
        "matched_trades": len(matched_ids),
        "match_percentage": round(len(matched_ids) / len(set_ded) * 100, 2) if set_ded else None,
        "dedicated_without_id_excluded": len(ded_no_id),
        "wildcard_without_id_excluded": len(wld_no_id),
        "missing_in_wildcard_count": len(missing_in_wld),
        "missing_in_dedicated_count": len(missing_in_ded),
        "missing_in_wildcard_sample": missing_in_wld_sample,
        "discrepancies_count": len(discrepancies),
        "discrepancies_details": discrepancies,
        "client_delay_stats_dedicated_ms": stats(delays_ded),
        "client_delay_stats_wildcard_ms": stats(delays_wld),
    }


def measure_recorder_performance(conn, session_id: str) -> dict[str, Any]:
    """Measure event throughput, inter-arrival times, burst peaks, and storage performance."""
    q = """
        SELECT seq, elapsed_ms, kind
        FROM stockbit_ws.events
        WHERE session_id = %s
        ORDER BY seq ASC
    """
    rows = conn.execute(q, (session_id,)).fetchall()

    total_events = len(rows)
    first_ms = rows[0]["elapsed_ms"] if rows else 0
    last_ms = rows[-1]["elapsed_ms"] if rows else 0
    duration_sec = max(1.0, (last_ms - first_ms) / 1000)

    # 1-second buckets
    sec_buckets = Counter()
    zero_delta_count = 0
    max_delta_ms = 0
    prev_ms = None
    sequence_errors = backwards = 0

    for expected, r in enumerate(rows, 1):
        sequence_errors += r["seq"] != expected
        ms = r["elapsed_ms"]
        sec_buckets[int(ms / 1000)] += 1
        delta = ms - prev_ms if prev_ms is not None else None
        if delta is not None and delta < 0:
            backwards += 1
        if delta == 0:
            zero_delta_count += 1
        if delta is not None and delta > max_delta_ms:
            max_delta_ms = delta
        prev_ms = ms

    counts = list(sec_buckets.values())
    counts.sort()

    peak_rate = counts[-1] if counts else 0
    mean_rate = round(total_events / duration_sec, 2)
    median_rate = counts[len(counts) // 2] if counts else 0
    p95_rate = counts[int(len(counts) * 0.95)] if counts else 0
    p99_rate = counts[int(len(counts) * 0.99)] if counts else 0

    # Arrival counts do not measure commit latency or spare capacity.

    return {
        "total_events": total_events,
        "duration_seconds": round(duration_sec, 1),
        "mean_events_per_sec": mean_rate,
        "median_events_per_sec": median(counts) if counts else 0,
        "rate_percentile_basis": "nonempty one-second event buckets",
        "sequence_errors": sequence_errors,
        "backwards_elapsed_events": backwards,
        "peak_events_per_sec": peak_rate,
        "p95_events_per_sec": p95_rate,
        "p99_events_per_sec": p99_rate,
        "simultaneous_events_zero_delta": zero_delta_count,
        "simultaneous_percentage": round(zero_delta_count / max(1, total_events - 1) * 100, 2),
        "max_inactivity_gap_ms": max_delta_ms,
        "needs_async_queue_and_batch": None,
        "verdict_storage": "BELUM TERUKUR: durasi commit, backlog, dan event-loop lag tidak direkam; jumlah event bukan bukti kapasitas I/O.",

    }


def compute_market_descriptive(
    conn, session_id: str, symbol: str
) -> dict[str, Any]:
    """Calculate trade volume/value, aggressive side proportion, trade velocity (1s, 5s, 30s), spread & imbalance."""
    # 1. Trades Descriptive
    q_trades = """
        SELECT elapsed_ms, payload
        FROM stockbit_ws.events
        WHERE session_id = %s AND kind = 'done'
        ORDER BY seq ASC
    """
    rows_trades = conn.execute(q_trades, (session_id,)).fetchall()

    haka_volume_lot = 0.0
    haki_volume_lot = 0.0
    haka_value = 0.0
    haki_value = 0.0
    haka_count = 0
    haki_count = 0

    trade_timestamps = []
    seen = set()

    for r in rows_trades:
        ms = r["elapsed_ms"]
        for t in r["payload"].get("trades", []):
            if symbol != "*" and t.get("symbol") != symbol:
                continue
            key = (t.get("symbol"), t["tradeId"]) if t.get("tradeId") is not None else (
                t.get("symbol"), t.get("timestamp"), t.get("price"), t.get("shares"), t.get("sideCode"))
            if key in seen:
                continue
            seen.add(key)
            lot = t.get("lot", (t.get("shares", 0) / 100))
            val = t.get("transactionValue", t.get("price", 0) * t.get("shares", 0))
            side = t.get("sideCode")

            trade_timestamps.append(ms)

            if side == 1:
                haka_count += 1
                haka_volume_lot += lot
                haka_value += val
            elif side == 2:
                haki_count += 1
                haki_volume_lot += lot
                haki_value += val

    total_trade_count = haka_count + haki_count
    total_volume_lot = haka_volume_lot + haki_volume_lot
    total_value = haka_value + haki_value

    haka_pct_value = round((haka_value / total_value * 100), 2) if total_value > 0 else 0.0
    haki_pct_value = round((haki_value / total_value * 100), 2) if total_value > 0 else 0.0

    # Trade velocity across 1s, 5s, and 30s windows
    def calculate_velocity(bucket_size_sec):
        if not trade_timestamps:
            return {"max": 0, "mean": 0, "p95": 0}
        buckets = Counter()
        for ms in trade_timestamps:
            buckets[int(ms / 1000 / bucket_size_sec)] += 1
        arr = sorted(buckets.values())
        return {
            "max": arr[-1] if arr else 0,
            "mean": round(sum(arr) / len(arr), 1) if arr else 0,
            "p95": arr[int(len(arr) * 0.95)] if arr else 0,
        }

    velocity_1s = calculate_velocity(1)
    velocity_5s = calculate_velocity(5)
    velocity_30s = calculate_velocity(30)

    # 2. Order Book Dynamics (Spread & Depth Imbalance)
    q_books = """
        SELECT elapsed_ms, payload
        FROM stockbit_ws.events
        WHERE session_id = %s AND kind = 'book'
        ORDER BY seq ASC
    """
    rows_books = conn.execute(q_books, (session_id,)).fetchall()

    book_stats = None
    if rows_books and symbol != "*":
        spreads = []
        spreads_bps = []
        top1_imbalances = []
        top3_imbalances = []
        crossed_book_count = 0
        locked_book_count = 0

        # Maintain running book to compute metrics after each update
        curr_bid = []
        curr_offer = []

        for r in rows_books:
            p = r["payload"]
            if p.get("symbol") != symbol:
                continue
            side = p.get("side")
            levels = p.get("levels", [])
            if side == "BID":
                curr_bid = sorted(levels, key=lambda level: level["price"], reverse=True)
            elif side == "OFFER":
                curr_offer = sorted(levels, key=lambda level: level["price"])

            if curr_bid and curr_offer:
                best_bid = curr_bid[0]["price"]
                best_offer = curr_offer[0]["price"]
                spread = best_offer - best_bid

                if spread == 0:
                    locked_book_count += 1
                if spread < 0:
                    crossed_book_count += 1
                elif best_bid > 0 and best_offer > 0:
                    mid = (best_bid + best_offer) / 2
                    bps = (spread / mid) * 10000
                    spreads.append(spread)
                    spreads_bps.append(bps)

                    # Top 1 Imbalance
                    b1_lot = curr_bid[0]["lot"]
                    o1_lot = curr_offer[0]["lot"]
                    imb1 = (b1_lot - o1_lot) / max(1.0, (b1_lot + o1_lot))
                    top1_imbalances.append(imb1)

                    # Top 3 Imbalance
                    b3_lot = sum(lvl["lot"] for lvl in curr_bid[:3])
                    o3_lot = sum(lvl["lot"] for lvl in curr_offer[:3])
                    imb3 = (b3_lot - o3_lot) / max(1.0, (b3_lot + o3_lot))
                    top3_imbalances.append(imb3)

        if spreads or crossed_book_count:
            def avg(lst):
                return round(sum(lst) / len(lst), 2) if lst else 0.0

            book_stats = {
                "total_book_updates": len(rows_books),
                "crossed_book_events": crossed_book_count,
                "locked_book_events": locked_book_count,
                "avg_spread_pts": avg(spreads),
                "min_spread_pts": min(spreads) if spreads else None,
                "max_spread_pts": max(spreads) if spreads else None,
                "avg_spread_bps": avg(spreads_bps),
                "avg_top1_imbalance": avg(top1_imbalances),
                "avg_top3_imbalance": avg(top3_imbalances),
            }

    return {
        "symbol": symbol,
        "total_trades": total_trade_count,
        "total_volume_lot": round(total_volume_lot, 1),
        "total_value_idr": round(total_value, 0),
        "haka_buy": {
            "count": haka_count,
            "volume_lot": round(haka_volume_lot, 1),
            "value_idr": round(haka_value, 0),
            "pct_value": haka_pct_value,
        },
        "haki_sell": {
            "count": haki_count,
            "volume_lot": round(haki_volume_lot, 1),
            "value_idr": round(haki_value, 0),
            "pct_value": haki_pct_value,
        },
        "net_flow_idr": round(haka_value - haki_value, 0),
        "net_flow_lot": round(haka_volume_lot - haki_volume_lot, 1),
        "trade_velocity": {
            "window_1s": velocity_1s,
            "window_5s": velocity_5s,
            "window_30s": velocity_30s,
        },
        "order_book_microstructure": book_stats,
    }


def generate_full_report(
    session_id: str,
    comparison_info: dict[str, Any] | None = None,
) -> str:
    """Generate comprehensive quality and descriptive markdown report."""
    with connect_database(readonly=True) as conn:
        verify_schema(conn)
        session = conn.execute(
            "SELECT * FROM stockbit_ws.sessions WHERE id = %s", (session_id,)
        ).fetchone()
        if not session:
            raise ValueError("Sesi tidak ditemukan.")
        symbol = session["symbol"]
        uniqueness = analyze_session_uniqueness(conn, session_id)
        perf = measure_recorder_performance(conn, session_id)
        market = compute_market_descriptive(conn, session_id, symbol)

    lines = []
    lines.append(f"# Laporan Kualitas Rekaman & Analisis Deskriptif")
    lines.append(f"**Session ID**: `{session['id']}` | **Symbol**: `{symbol}` | **Status**: `{session['status']}` | **Source**: `{session['source']}`")
    lines.append(f"**Waktu**: {timestamp_text(session['started_at'])} s.d. {timestamp_text(session['ended_at']) if session['ended_at'] else 'OPEN'} (Durasi: {perf.get('duration_seconds', 0)} detik)\n")

    # PILAR 1
    lines.append("## 1. Audit Transaksi Unik & Deduplikasi Database")
    lines.append(f"- **Total Batch Done Diterima**: {uniqueness['total_batches']:,}")
    lines.append(f"- **Total Record Transaksi Mentah**: {uniqueness['total_trade_records']:,}")
    lines.append(f"- **Transaksi Memiliki Trade ID**: {uniqueness['trades_with_id']:,} (Unik: {uniqueness['unique_with_id']:,})")
    lines.append(f"- **Transaksi Tanpa Trade ID**: {uniqueness['trades_without_id']:,} (Unik: {uniqueness['unique_without_id']:,})")
    lines.append(f"- **Duplikat di Database**: {uniqueness['duplicate_records']:,} record")
    if uniqueness["top_duplicates"]:
        lines.append("  - *Contoh duplikat berulang*: " + ", ".join(f"ID {d['tradeId']} ({d['occurrences']}x)" for d in uniqueness["top_duplicates"]))
    lines.append(f"- **Total Transaksi Unik Sebenarnya**: **{uniqueness['unique_trades_total']:,}**\n")

    # PILAR 2 (Jika ada perbandingan)
    if comparison_info:
        lines.append("## 2. Pembandingan Ketat (Dedicated vs Wildcard '*')")
        lines.append(f"- **Saham Diuji**: `{comparison_info['symbol']}`")
        lines.append(f"- **Irisan Waktu**: `{comparison_info['overlap_window']['start']}` s.d. `{comparison_info['overlap_window']['end']}` ({comparison_info['overlap_window']['duration_seconds']}s)")
        lines.append(f"- **Unique Trade ID Sesi Khusus**: {comparison_info['dedicated_total_unique']:,}")
        lines.append(f"- **Unique Trade ID Sesi Wildcard**: {comparison_info['wildcard_total_unique']:,}")
        lines.append(f"- **Tingkat Kecocokan (Intersection)**: **{comparison_info['matched_trades']:,} ({comparison_info['match_percentage']}%)**")
        lines.append(f"- **Ada di Khusus, Hilang di Wildcard**: **{comparison_info['missing_in_wildcard_count']} trade**")
        lines.append(f"- **Ada di Wildcard, Hilang di Khusus**: **{comparison_info['missing_in_dedicated_count']} trade**")
        lines.append(f"- **Perbedaan Nilai/Data pada Trade yang Cocok**: **{comparison_info['discrepancies_count']}**")
        
        lines.append(f"- **Selisih Timestamp (Received At minus timestamp transaksi; bukan latensi jaringan terverifikasi)**:")
        d_stat = comparison_info["client_delay_stats_dedicated_ms"]
        w_stat = comparison_info["client_delay_stats_wildcard_ms"]
        lines.append(f"  - Sesi Khusus  : Rata-rata {d_stat['mean']} ms | Median {d_stat['median']} ms | P95 {d_stat['p95']} ms")
        lines.append(f"  - Sesi Wildcard: Rata-rata {w_stat['mean']} ms | Median {w_stat['median']} ms | P95 {w_stat['p95']} ms")
        lines.append(f"  - Selisih negatif: dedicated={d_stat['negative_count']}, wildcard={w_stat['negative_count']}; perbedaan jam/makna timestamp belum dikoreksi.")
        lines.append(f"- Record tanpa ID dikecualikan: dedicated={comparison_info['dedicated_without_id_excluded']}, wildcard={comparison_info['wildcard_without_id_excluded']}")
        lines.append("- Irisan memakai timestamp transaksi terhadap batas sesi lokal; bukan jaminan cakupan server identik.")
        if comparison_info["missing_in_wildcard_sample"]:
            lines.append(f"\n  *Sampel Transaksi Hilang di Wildcard:*")
            lines.append("  | Trade ID | Waktu Bursa (UTC) | Waktu Terima (UTC) | Harga | Lot | Aksi |")
            lines.append("  |---|---|---|---|---|---|")
            for m in comparison_info["missing_in_wildcard_sample"][:5]:
                lines.append(f"  | {m['tradeId']} | {m['exchange_time']} | {m['received_at']} | {m['price']} | {m['lot']} | {m['side']} |")
        lines.append("\n  > *Catatan Faktual: Selisih adalah perbedaan rekaman; penyebab belum ditentukan. Kecocokan hanya berlaku untuk sampel ini, bukan kelengkapan seluruh pasar.*\n")

    # PILAR 3
    lines.append("## 3. Pengukuran Kemampuan & Throughput Recorder")
    lines.append(f"- **Total Event Database**: {perf['total_events']:,} event")
    lines.append(f"- **Throughput Rata-rata**: {perf['mean_events_per_sec']} event/detik (Median: {perf['median_events_per_sec']} event/s)")
    lines.append(f"- **Beban Puncak (Peak Throughput)**: **{perf['peak_events_per_sec']} event/detik** (P95: {perf['p95_events_per_sec']} e/s, P99: {perf['p99_events_per_sec']} e/s)")
    lines.append(f"- **Pasangan Event Bertimestamp Sama (dapat berasal dari satu pesan)**: {perf['simultaneous_events_zero_delta']:,} event ({perf['simultaneous_percentage']}%)")
    lines.append(f"- **Jeda Terpanjang Antar-event**: {perf['max_inactivity_gap_ms']} ms")
    lines.append(f"- **Evaluasi Kebutuhan Antrean & Batching**: `{perf['verdict_storage']}`\n")

    lines.append(f"- Anomali sequence lokal: {perf['sequence_errors']}; elapsed mundur: {perf['backwards_elapsed_events']}")
    lines.append("- Median/persentil event hanya bucket detik terisi; bukan kapasitas recorder.")

    # PILAR 4
    lines.append("## 4. Analisis Deskriptif Pasar & Mikrostruktur")
    lines.append(f"- **Total Volume Transaksi**: {format_number(market['total_volume_lot'])} lot | **Nilai Total**: Rp{format_number(market['total_value_idr'], 0).replace(',', '.')}")
    lines.append(f"- **Proporsi Agresi Transaksi**:")
    haka = market["haka_buy"]
    haki = market["haki_sell"]
    lines.append(f"  - **HAKA (Buy Agresif)** : {haka['count']:,} trade ({haka['pct_value']}%) | {format_number(haka['volume_lot'])} lot | Rp{format_number(haka['value_idr'], 0).replace(',', '.')}")
    lines.append(f"  - **HAKI (Sell Agresif)**: {haki['count']:,} trade ({haki['pct_value']}%) | {format_number(haki['volume_lot'])} lot | Rp{format_number(haki['value_idr'], 0).replace(',', '.')}")
    net_val = market["net_flow_idr"]
    net_prefix = "+" if net_val >= 0 else ""
    lines.append(f"  - **Net Aggression Flow**: **{net_prefix}Rp{format_number(net_val, 0).replace(',', '.')}** ({net_prefix}{format_number(market['net_flow_lot'])} lot)")
    
    lines.append("- Volume/nilai memakai salinan pertama transaksi unik; fallback tanpa ID bersifat perkiraan.")
    lines.append("- **Kecepatan teramati client**: bucket tetap dari waktu penerimaan, bukan waktu bursa; rata-rata/persentil hanya bucket terisi. Snapshot awal dapat menaikkan puncak.")
    v1 = market["trade_velocity"]["window_1s"]
    v5 = market["trade_velocity"]["window_5s"]
    v30 = market["trade_velocity"]["window_30s"]
    lines.append(f"  - Jendela 1 Detik : Maks {v1['max']} trade/s | Rata-rata {v1['mean']} trade/s | P95 {v1['p95']} trade/s")
    lines.append(f"  - Jendela 5 Detik : Maks {v5['max']} trade/5s | Rata-rata {v5['mean']} trade/5s | P95 {v5['p95']} trade/5s")
    lines.append(f"  - Jendela 30 Detik: Maks {v30['max']} trade/30s | Rata-rata {v30['mean']} trade/30s | P95 {v30['p95']} trade/30s")

    ob = market.get("order_book_microstructure")
    if ob:
        lines.append(f"- **Dinamika Buku Pesanan (Order Book)**:")
        lines.append(f"  - Total Update Order Book: {ob['total_book_updates']:,} update")
        lines.append(f"  - Rata-rata Spread: {ob['avg_spread_pts']} poin ({ob['avg_spread_bps']} bps) | Rentang: {ob['min_spread_pts']} - {ob['max_spread_pts']} poin")
        lines.append(f"  - Rata-rata Top-1 Depth Imbalance: {ob['avg_top1_imbalance']:+.3f} (Skala -1.0 s.d. +1.0)")
        lines.append(f"  - Rata-rata Top-3 Depth Imbalance: {ob['avg_top3_imbalance']:+.3f}")
        lines.append(f"  - Crossed book: {ob['crossed_book_events']}; Locked book: {ob['locked_book_events']}")
        lines.append("  - Rata-rata berbobot update, bukan durasi; sisi stale belum dikecualikan.")
    lines.append("")

    # VERDICT
    lines.append("## VERDICT: KONSISTENSI DATA & KELAYAKAN RISET SINYAL")
    problems = []
    if session["status"] not in ("STOPPED", "COMPLETED") or session["ended_at"] is None:
        problems.append("sesi belum selesai normal")
    if uniqueness["total_trade_records"] == 0:
        problems.append("tidak ada transaksi untuk dianalisis")
    if perf["sequence_errors"] or perf["backwards_elapsed_events"]:
        problems.append("anomali urutan lokal")
    if uniqueness["duplicate_records"] or uniqueness["trades_without_id"]:
        problems.append("duplikat atau transaksi tanpa ID")
    if comparison_info:
        if comparison_info["matched_trades"] == 0:
            problems.append("tidak ada transaksi yang cocok")
        if comparison_info["discrepancies_count"]:
            problems.append("nilai/timestamp transaksi berbeda")
        if comparison_info["missing_in_wildcard_count"] or comparison_info["missing_in_dedicated_count"]:
            problems.append("terdapat selisih cakupan antarsesi")
    verdict = "**PERLU PEMERIKSAAN**: " + "; ".join(problems) if problems else "**DESKRIPTIF TERSEDIA; KELENGKAPAN BELUM TERVERIFIKASI**"
    if not comparison_info:
        verdict += "\n\nPembandingan lintas feed belum dilakukan pada laporan ini."
    verdict += "\n\nUrutan lokal dan kesamaan nilai tidak membuktikan kelengkapan bursa. Kapasitas I/O, interpretasi timestamp/side, serta penyebab transaksi tidak ditemukan belum terverifikasi. Net aggression bukan bukti akumulasi/distribusi atau arus dana bersih."
    verdict += "\n\nCache deduplikasi tidak memangkas hitungan kumulatif; eviction hanya dapat membuat transaksi lama dihitung baru lagi bila dikirim ulang. Tidak menyimpulkan selisih berasal dari cache tanpa pembuktian."
    lines.append(verdict)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Laporan Kualitas Rekaman & Analisis Deskriptif Pasar")
    parser.add_argument("session_id", nargs="?", help="ID sesi yang ingin diaudit")
    parser.add_argument("--compare", nargs=3, metavar=("DEDICATED_ID", "WILDCARD_ID", "SYMBOL"),
                        help="Bandingkan sesi khusus vs wildcard (contoh: --compare <ded_id> <wld_id> BUMI)")
    parser.add_argument("--output", help="Path file output markdown (default: reports/quality_<session_id>.md)")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    conn = None
    try:
        conn = connect_database(readonly=True)
        verify_schema(conn)

        comparison_info = None
        target_session = args.session_id

        if args.compare:
            ded_id, wld_id, sym = args.compare
            target_session = ded_id
            print(f"Menganalisis perbandingan ketat {sym} (Dedicated {ded_id[:8]} vs Wildcard {wld_id[:8]})...")
            comparison_info = compare_sessions_strict(conn, ded_id, wld_id, sym.strip().upper())

        if not target_session:
            row = conn.execute("SELECT id FROM stockbit_ws.sessions ORDER BY run_no DESC LIMIT 1").fetchone()
            if not row:
                print("Tidak ada sesi yang ditemukan di database.")
                return 1
            target_session = row["id"]

        print(f"Membuat laporan kualitas untuk sesi: {target_session}...")
        report_text = generate_full_report(target_session, comparison_info=comparison_info)

        # Print to terminal
        print("\n" + report_text + "\n")

        # Save to markdown file
        out_dir = Path("reports")
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = Path(args.output) if args.output else out_dir / f"quality_{target_session[:8]}.md"
        out_path.write_text(report_text, encoding="utf-8")
        print(f"Laporan berhasil disimpan ke: {out_path.resolve()}")
        return 0

    except (RecordingError, ValueError, Exception) as exc:
        print(f"Error saat membuat laporan: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None and not conn.closed:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
