"""Automated BSJP & Momentum Market Microstructure Screener & Report Generator.

Executes quantitative screening based on:
1. Minimum turnover & trade frequency (default: >= Rp 5B & >= 3,000 trades)
2. Non-proxy exclusion (avoids heavy index banking anchors)
3. Aggressor flow imbalance (Net Buy > 0, HAKA dominance)
4. Multi-window time-slicing (14:00+ Late-Session, 15:00+ Power-Hour, 15:35+ Sprint)
5. Close-to-HOD price strength (Close >= 95% - 98% of High of Day)
6. Absorption accumulation detection
"""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path
import sys
from typing import Any

from .postgres import connect_database


def resolve_sessions(conn, date_str: str | None = None, session_ids: list[str] | None = None) -> tuple[list[str], str]:
    """Resolve session IDs for the target date or explicit session list."""
    if session_ids:
        return session_ids, "custom"

    cur = conn.cursor()
    if date_str:
        try:
            target_date = datetime.date.fromisoformat(date_str)
        except ValueError:
            raise ValueError(f"Format tanggal tidak valid: '{date_str}'. Gunakan format YYYY-MM-DD.")
    else:
        # Default to the most recent date available in sessions
        row = cur.execute("SELECT started_at::date as d FROM stockbit_ws.sessions ORDER BY started_at DESC LIMIT 1").fetchone()
        if not row or not row.get("d"):
            raise ValueError("Tidak ada sesi yang ditemukan di database.")
        target_date = row["d"]

    start_utc = datetime.datetime.combine(target_date, datetime.time.min, tzinfo=datetime.timezone.utc) - datetime.timedelta(hours=7)
    end_utc = start_utc + datetime.timedelta(days=1)

    rows = cur.execute("""
        SELECT id, symbol, started_at, duration_ms, status 
        FROM stockbit_ws.sessions 
        WHERE started_at >= %s AND started_at < %s
        ORDER BY started_at ASC
    """, (start_utc, end_utc)).fetchall()

    if not rows:
        raise ValueError(f"Tidak ada sesi rekaman pada tanggal {target_date.isoformat()}.")

    # Prefer wildcard '*' sessions if available, otherwise take all sessions
    wildcards = [r["id"] for r in rows if r.get("symbol") == "*"]
    resolved = wildcards if wildcards else [r["id"] for r in rows]
    return resolved, target_date.isoformat()


def run_screening(
    conn,
    session_ids: list[str],
    min_val_idr: float = 5_000_000_000,
    min_trades: int = 3000,
    min_hod_pct: float = 95.0,
    exclude_index_banks: bool = True,
) -> dict[str, Any]:
    """Run tick-level microstructure SQL query across the designated sessions."""
    cur = conn.cursor()

    cur.execute("""
    WITH trades_raw AS (
        SELECT 
            t->>'symbol' as symbol,
            (t->>'price')::numeric as price,
            (t->>'shares')::numeric as shares,
            (t->>'sideCode')::int as side_code,
            (t->>'transactionValue')::numeric as val,
            (t->>'timestamp')::timestamptz as ts
        FROM stockbit_ws.events e,
             jsonb_array_elements(e.payload->'trades') t
        WHERE e.session_id = ANY(%s)
          AND e.kind = 'done'
    ),
    day_summary AS (
        SELECT 
            symbol,
            min(price) as low_p,
            max(price) as high_p,
            count(*) as total_trades,
            sum(shares)/100 as total_lots,
            sum(val) as total_val,
            sum(CASE WHEN side_code = 1 THEN val ELSE 0 END) as total_haka,
            sum(CASE WHEN side_code = 2 THEN val ELSE 0 END) as total_haki,
            -- Window 14:00+ WIB (07:00:00 UTC)
            sum(CASE WHEN (ts AT TIME ZONE 'Asia/Jakarta')::time >= '14:00:00' THEN val ELSE 0 END) as val_14,
            sum(CASE WHEN (ts AT TIME ZONE 'Asia/Jakarta')::time >= '14:00:00' AND side_code = 1 THEN val ELSE 0 END) as haka_14,
            sum(CASE WHEN (ts AT TIME ZONE 'Asia/Jakarta')::time >= '14:00:00' AND side_code = 2 THEN val ELSE 0 END) as haki_14,
            -- Window 15:00+ WIB (08:00:00 UTC)
            sum(CASE WHEN (ts AT TIME ZONE 'Asia/Jakarta')::time >= '15:00:00' THEN val ELSE 0 END) as val_15,
            sum(CASE WHEN (ts AT TIME ZONE 'Asia/Jakarta')::time >= '15:00:00' AND side_code = 1 THEN val ELSE 0 END) as haka_15,
            sum(CASE WHEN (ts AT TIME ZONE 'Asia/Jakarta')::time >= '15:00:00' AND side_code = 2 THEN val ELSE 0 END) as haki_15,
            -- Window 15:35+ WIB (08:35:00 UTC)
            sum(CASE WHEN (ts AT TIME ZONE 'Asia/Jakarta')::time >= '15:35:00' AND side_code = 1 THEN val ELSE 0 END) as haka_1535,
            sum(CASE WHEN (ts AT TIME ZONE 'Asia/Jakarta')::time >= '15:35:00' AND side_code = 2 THEN val ELSE 0 END) as haki_1535
        FROM trades_raw
        GROUP BY symbol
    ),
    last_tick AS (
        SELECT DISTINCT ON (symbol)
            symbol,
            price as close_p
        FROM trades_raw
        ORDER BY symbol, ts DESC
    )
    SELECT 
        d.symbol,
        l.close_p,
        d.low_p,
        d.high_p,
        ROUND((l.close_p / NULLIF(d.high_p, 0) * 100.0), 1) as hod_pct,
        d.total_trades,
        d.total_val / 1e9 as total_val_b,
        (d.total_haka - d.total_haki) / 1e9 as total_net_b,
        ROUND((d.total_haka / NULLIF(d.total_val, 0) * 100.0), 1) as total_haka_pct,
        -- 14:00+ stats
        d.val_14 / 1e9 as val_14_b,
        ROUND((d.haka_14 / NULLIF(d.val_14, 0) * 100.0), 1) as haka_14_pct,
        (d.haka_14 - d.haki_14) / 1e9 as net_14_b,
        -- 15:00+ stats
        d.val_15 / 1e9 as val_15_b,
        ROUND((d.haka_15 / NULLIF(d.val_15, 0) * 100.0), 1) as haka_15_pct,
        (d.haka_15 - d.haki_15) / 1e9 as net_15_b,
        -- 15:35+ stats
        (d.haka_1535 - d.haki_1535) / 1e9 as net_1535_b
    FROM day_summary d
    JOIN last_tick l ON d.symbol = l.symbol
    WHERE d.total_val >= %s
      AND d.total_trades >= %s;
    """, (session_ids, min_val_idr, min_trades))

    raw_rows = cur.fetchall()

    INDEX_BANKS = {"BBCA", "BBRI", "BMRI", "BBNI", "TLKM", "ASII"}
    BIG_CAP_THRESHOLD_VAL = 90.0  # Rp 90 Miliar+

    trading_candidates = []
    big_cap_candidates = []
    absorption_candidates = []

    for r in raw_rows:
        sym = r["symbol"]
        hod = float(r["hod_pct"] or 0)
        net_day = float(r["total_net_b"] or 0)
        val_day = float(r["total_val_b"] or 0)
        haka_pct = float(r["total_haka_pct"] or 0)
        low_p = float(r["low_p"] or 0)
        high_p = float(r["high_p"] or 0)
        px_range_pct = ((high_p - low_p) / low_p * 100.0) if low_p > 0 else 0

        # Absorption check: HAKI heavy (haka < 45%), but price resilient (range <= 2.5% or hod >= 97%)
        if haka_pct < 45.0 and net_day < 0 and (px_range_pct <= 2.5 or hod >= 97.0):
            absorption_candidates.append(r)
            continue

        # Standard momentum criteria
        if hod < min_hod_pct or net_day <= 0:
            continue

        if exclude_index_banks and sym in INDEX_BANKS:
            continue

        # Split into Big Cap vs Mid/Small Cap Trading
        if val_day >= BIG_CAP_THRESHOLD_VAL or sym in {"AMMN", "ANTM", "UNTR", "AADI"}:
            big_cap_candidates.append(r)
        else:
            trading_candidates.append(r)

    # Sort trading candidates by Net Buy 15:00+ (closing urgency), fallback to Net 14:00+
    trading_candidates.sort(key=lambda x: (float(x["net_15_b"] or 0), float(x["net_14_b"] or 0)), reverse=True)
    big_cap_candidates.sort(key=lambda x: (float(x["net_15_b"] or 0), float(x["net_14_b"] or 0)), reverse=True)
    absorption_candidates.sort(key=lambda x: float(x["total_val_b"] or 0), reverse=True)

    return {
        "trading_candidates": trading_candidates,
        "big_cap_candidates": big_cap_candidates,
        "absorption_candidates": absorption_candidates[:5],
        "total_analyzed": len(raw_rows),
    }


def generate_recommendations(top_picks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build actionable trading plans for top picks."""
    recs = []
    for r in top_picks[:5]:
        sym = r["symbol"]
        close_p = float(r["close_p"])
        net_15 = float(r["net_15_b"] or 0)
        haka_15 = float(r["haka_15_pct"] or 0)

        # Tactical parameters
        entry_low = close_p
        entry_high = round(close_p * 1.008, 0 if close_p >= 200 else 1)
        tp1 = round(close_p * 1.035, 0 if close_p >= 200 else 1)
        tp2 = round(close_p * 1.060, 0 if close_p >= 200 else 1)
        sl = round(close_p * 0.982, 0 if close_p >= 200 else 1)

        thesis = (
            f"Akumulasi penutupan solid: net inflow sore Rp {net_15:+.2f} B dengan HAKA {haka_15:.1f}%. "
            f"Ditutup di level {close_p:.0f} ({float(r['hod_pct']):.1f}% HOD), siap akselerasi di sesi pembukaan."
        )

        recs.append({
            "symbol": sym,
            "close": close_p,
            "entry": f"{entry_low:.0f} - {entry_high:.0f}",
            "tp1": f"{tp1:.0f} (+3.5%)",
            "tp2": f"{tp2:.0f} (+6.0%)",
            "sl": f"{sl:.0f} (-1.8%)",
            "thesis": thesis,
        })
    return recs


def format_report_markdown(date_str: str, results: dict[str, Any], recommendations: list[dict[str, Any]]) -> str:
    """Format complete markdown report."""
    tc = results["trading_candidates"]
    bc = results["big_cap_candidates"]
    ab = results["absorption_candidates"]

    lines = [
        f"# 📊 Laporan Analisis BSJP & Momentum Market Microstructure",
        f"**Tanggal Observasi**: {date_str} | **Metode**: Order Flow Imbalance & Multi-Window Slicing (14:00+ vs 15:00+)",
        f"",
        f"---",
        f"",
        f"### 🎯 Rekomendasi Taktis Saham Pilihan (Top Actionable Picks)",
        f"",
    ]

    for i, rec in enumerate(recommendations, 1):
        lines.append(f"#### {i}. **{rec['symbol']}** (Close: {rec['close']:.0f})")
        lines.append(f"- **Area Beli (Entry)**: `{rec['entry']}`")
        lines.append(f"- **Target Profit 1**: `{rec['tp1']}` | **Target Profit 2**: `{rec['tp2']}`")
        lines.append(f"- **Stop Loss (Ketat)**: `{rec['sl']}`")
        lines.append(f"- **Analisis Tape Reading**: {rec['thesis']}")
        lines.append(f"")

    lines.extend([
        f"---",
        f"",
        f"### 🥇 Tabel Saham Trading / Scalping Lolos Filter (Mid & Small Cap)",
        f"*Kriteria: Omset >= Rp 5 Miliar, Trades >= 3.000, Net Buy Harian > 0, Close >= 95% HOD*",
        f"",
        f"| Rank | Symbol | Close (% HOD) | Trades | Total Val | Net Harian | Val 14:00+ | HAKA 14+ | Net 14:00+ | Val 15:00+ | HAKA 15+ | Net 15:00+ | Net 15m Akhir |",
        f"| :---: | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ])

    for i, r in enumerate(tc, 1):
        rank_badge = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}"
        lines.append(
            f"| {rank_badge} | **{r['symbol']}** | {float(r['close_p']):.0f} *({float(r['hod_pct']):.1f}%)* | "
            f"{r['total_trades']:,} | Rp {float(r['total_val_b']):.2f} B | +Rp {float(r['total_net_b']):.2f} B | "
            f"Rp {float(r['val_14_b'] or 0):.2f} B | {float(r['haka_14_pct'] or 0):.1f}% | +Rp {float(r['net_14_b'] or 0):.2f} B | "
            f"Rp {float(r['val_15_b'] or 0):.2f} B | **{float(r['haka_15_pct'] or 0):.1f}%** | **+Rp {float(r['net_15_b'] or 0):.2f} B** | "
            f"{float(r['net_1535_b'] or 0):+.2f} B |"
        )

    if bc:
        lines.extend([
            f"",
            f"---",
            f"",
            f"### 🏛️ Kategori Khusus: Big Cap Inflow Raksasa (> Rp 90 Miliar)",
            f"*Saham berkapitalisasi besar dengan likuiditas institusi raksasa untuk kapasitas modal besar:*",
            f"",
            f"| Symbol | Close (% HOD) | Trades | Total Val | Net Harian | Val 14:00+ | HAKA 14+ | Net 14:00+ | Val 15:00+ | HAKA 15+ | Net 15:00+ | Net 15m Akhir |",
            f"| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
        ])
        for r in bc:
            lines.append(
                f"| **{r['symbol']}** | {float(r['close_p']):.0f} *({float(r['hod_pct']):.1f}%)* | "
                f"{r['total_trades']:,} | Rp {float(r['total_val_b']):.2f} B | +Rp {float(r['total_net_b']):.2f} B | "
                f"Rp {float(r['val_14_b'] or 0):.2f} B | {float(r['haka_14_pct'] or 0):.1f}% | +Rp {float(r['net_14_b'] or 0):.2f} B | "
                f"Rp {float(r['val_15_b'] or 0):.2f} B | **{float(r['haka_15_pct'] or 0):.1f}%** | **+Rp {float(r['net_15_b'] or 0):.2f} B** | "
                f"{float(r['net_1535_b'] or 0):+.2f} B |"
            )

    if ab:
        lines.extend([
            f"",
            f"---",
            f"",
            f"### 🛡️ Kategori Khusus: Setup Absorption Accumulation (Iceberg Bid)",
            f"*Saham yang dihantam HAKI deras tapi harga tidak jebol dan ditampung rapat:*",
            f"",
            f"| Symbol | Close | Low - High | Range % | Total Val | Total HAKI % | Net Flow | Indikasi Benteng |",
            f"| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
        ])
        for r in ab:
            low_p = float(r['low_p'])
            high_p = float(r['high_p'])
            rng = ((high_p - low_p) / low_p * 100.0) if low_p > 0 else 0
            haki_pct = 100.0 - float(r['total_haka_pct'] or 0)
            lines.append(
                f"| **{r['symbol']}** | {float(r['close_p']):.0f} | {low_p:.0f} - {high_p:.0f} | "
                f"{rng:.2f}% | Rp {float(r['total_val_b']):.2f} B | {haki_pct:.1f}% HAKI | "
                f"{float(r['total_net_b']):.2f} B | Penyerapan tebal di support tanpa breakdown |"
            )

    lines.extend([
        f"",
        f"---",
        f"**Catatan Disiplin Trading**: Pasang Stop Loss 1–2 tick di bawah area beli. Amankan profit secara bertahap saat pembukaan pasar pagi.",
    ])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Stockbit BSJP & Momentum Market Microstructure Screener")
    parser.add_argument("--date", type=str, help="Target tanggal observasi (format YYYY-MM-DD, default: tanggal sesi terbaru)")
    parser.add_argument("--session", type=str, help="Session ID spesifik (pisahkan koma jika lebih dari 1)")
    parser.add_argument("--min-val", type=float, default=5.0, help="Minimal omset transaksi dalam Miliar Rupiah (default: 5.0)")
    parser.add_argument("--min-trades", type=int, default=3000, help="Minimal frekuensi trades (default: 3000)")
    parser.add_argument("--min-hod", type=float, default=95.0, help="Minimal rasio Close terhadap High of Day persen (default: 95.0)")
    parser.add_argument("--out", type=str, help="Lokasi file output report markdown (default: reports/bsjp_<date>.md)")
    parser.add_argument("--no-save", action="store_true", help="Jangan simpan file markdown, hanya cetak di terminal")

    args = parser.parse_args()

    conn = connect_database(readonly=True)
    try:
        session_list = [s.strip() for s in args.session.split(",")] if args.session else None
        session_ids, date_str = resolve_sessions(conn, args.date, session_list)

        print(f"\n🔍 Menjalankan Skrining BSJP Microstructure...")
        print(f"📅 Tanggal / Sesi : {date_str} ({len(session_ids)} sesi terpilih)")
        print(f"⚙️ Parameter     : Omset >= Rp {args.min_val:.1f}B | Trades >= {args.min_trades:,} | Close >= {args.min_hod:.1f}% HOD\n")

        results = run_screening(
            conn=conn,
            session_ids=session_ids,
            min_val_idr=args.min_val * 1e9,
            min_trades=args.min_trades,
            min_hod_pct=args.min_hod,
            exclude_index_banks=True,
        )

        all_top = results["trading_candidates"] + results["big_cap_candidates"]
        recs = generate_recommendations(all_top)

        report_md = format_report_markdown(date_str, results, recs)

        # Output to console
        print(report_md)

        # Save to file
        if not args.no_save:
            out_file = Path(args.out) if args.out else Path("reports") / f"bsjp_{date_str.replace('-', '')}.md"
            out_file.parent.mkdir(parents=True, exist_ok=True)
            out_file.write_text(report_md, encoding="utf-8")
            print(f"\n💾 Laporan lengkap berhasil disimpan ke: {out_file.resolve()}\n")

    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        return 1
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
