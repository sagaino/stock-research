"""Real-Time & Replay Market Radar / Anomaly Scanner for Wildcard WebSocket (*).

Scans running trade streams across all symbols in real time or from recorded
sessions to detect:
1. BREAKOUT_MOMENTUM (MDIA-style step-ladder volume breakout)
2. SQUEEZE_BLITZ (NZIA-style late power-hour squeeze / acceleration)
3. HEAVY_ABSORPTION (massive volume executed at fixed price tick)

Pure Python, deterministic, memory-bounded, zero AI tokens.
"""

from __future__ import annotations

import argparse
from collections import defaultdict, deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable

from .events import timestamp_text
from .orderbook import format_number
from .postgres import connect_database, verify_schema

_WIB = timezone(timedelta(hours=7), "WIB")


@dataclass
class RadarConfig:
    window_seconds: float = 5.0
    cooldown_seconds: float = 30.0
    enable_breakout: bool = True
    enable_squeeze: bool = True
    enable_absorption: bool = False  # Default nonaktif: fokus ke Breakout & Squeeze
    # Rule 1: Breakout Momentum (MDIA-style)
    breakout_min_trades: int = 50
    breakout_min_haka_pct: float = 85.0
    breakout_min_net_flow: float = 500_000_000.0  # Rp500 Juta
    breakout_min_delta_points: float = 2.0
    breakout_min_delta_pct: float = 0.75
    # Rule 2: Squeeze Blitz (NZIA-style)
    squeeze_min_trades: int = 30
    squeeze_min_haka_pct: float = 75.0
    squeeze_min_net_flow: float = 250_000_000.0  # Rp250 Juta
    squeeze_min_delta_points: float = 4.0  # Fast leap
    squeeze_min_delta_pct: float = 1.0
    # Rule 3: Heavy Absorption
    absorption_min_trades: int = 30
    absorption_min_value: float = 500_000_000.0  # Rp500 Juta
    absorption_max_delta_points: float = 0.0


@dataclass
class RadarAlert:
    timestamp: datetime
    symbol: str
    pattern: str  # BREAKOUT_MOMENTUM | SQUEEZE_BLITZ | HEAVY_ABSORPTION
    velocity: int  # trades in window
    haka_pct: float
    net_flow_idr: float
    price_open: float
    price_close: float
    delta_points: float
    delta_pct: float
    details: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["timestamp"] = self.timestamp.isoformat()
        d["time_wib"] = self.timestamp.astimezone(_WIB).strftime("%H:%M:%S")
        return d

    def format_banner(self) -> str:
        wib = self.timestamp.astimezone(_WIB).strftime("%H:%M:%S")
        sign = "+" if self.net_flow_idr >= 0 else ""
        flow_str = f"{sign}Rp{self.net_flow_idr:,.0f}".replace(",", ".")
        dp_sign = "+" if self.delta_points > 0 else ""
        return (
            f"🚨 [RADAR] {self.symbol:<5} | {self.pattern:<17} | {wib} WIB | "
            f"Vel: {self.velocity} tr/5s | HAKA: {self.haka_pct:.1f}% ({flow_str}) | "
            f"P: {self.price_open:.0f} -> {self.price_close:.0f} ({dp_sign}{self.delta_points:.0f} pts, {dp_sign}{self.delta_pct:.1f}%)"
        )


class RollingTradeWindow:
    """Bounded in-memory trade window for a single symbol."""

    def __init__(self, max_retention_seconds: float = 60.0):
        self.max_retention_seconds = max_retention_seconds
        self.trades: deque[dict[str, Any]] = deque()

    def append(self, trade: dict[str, Any]):
        self.trades.append(trade)
        self.prune(trade["exchange_time"])

    def prune(self, current_time: datetime):
        cutoff = current_time - timedelta(seconds=self.max_retention_seconds)
        while self.trades and self.trades[0]["exchange_time"] < cutoff:
            self.trades.popleft()

    def get_window_metrics(self, current_time: datetime, window_seconds: float = 5.0) -> dict[str, Any] | None:
        cutoff = current_time - timedelta(seconds=window_seconds)
        trades_in_window = [t for t in self.trades if t["exchange_time"] >= cutoff]
        if not trades_in_window:
            return None

        prices = [t["price"] for t in trades_in_window]
        open_price = prices[0]
        close_price = prices[-1]
        delta_points = close_price - open_price
        delta_pct = (delta_points / open_price * 100) if open_price > 0 else 0.0

        total_value = sum(t["value"] for t in trades_in_window)
        total_lot = sum(t["lot"] for t in trades_in_window)

        haka_val = sum(t["value"] for t in trades_in_window if t["sideCode"] == 1)
        haki_val = sum(t["value"] for t in trades_in_window if t["sideCode"] == 2)
        haka_pct = (haka_val / total_value * 100) if total_value > 0 else 0.0
        haki_pct = (haki_val / total_value * 100) if total_value > 0 else 0.0
        net_flow_val = haka_val - haki_val

        return {
            "count": len(trades_in_window),
            "open": open_price,
            "close": close_price,
            "high": max(prices),
            "low": min(prices),
            "delta_points": delta_points,
            "delta_pct": delta_pct,
            "total_value": total_value,
            "total_lot": total_lot,
            "haka_val": haka_val,
            "haki_val": haki_val,
            "haka_pct": haka_pct,
            "haki_pct": haki_pct,
            "net_flow_val": net_flow_val,
        }


class MarketRadar:
    """Real-time anomaly detector running across multi-symbol trade streams."""

    def __init__(
        self,
        config: RadarConfig | None = None,
        on_alert: Callable[[RadarAlert], None] | None = None,
        start_time: datetime | None = None,
        end_time: datetime | None = None,
    ):
        self.config = config or RadarConfig()
        self.on_alert = on_alert
        self.windows: dict[str, RollingTradeWindow] = defaultdict(RollingTradeWindow)
        self.start_time = start_time
        self.end_time = end_time
        self.last_alert_time: dict[str, datetime] = {}
        self.last_trade_time: dict[str, datetime] = {}
        self.seen_trades: set[tuple[Any, ...]] = set()
        self.duplicates_ignored = 0
        self.historical_ignored = 0
        self.late_ignored = 0
        self.alerts: list[RadarAlert] = []

    def process_trade(self, trade: dict[str, Any]) -> list[RadarAlert]:
        """Process a single trade and evaluate detection rules."""
        sym = trade.get("symbol")
        if not sym or sym == "*":
            return []

        ex_ts = trade.get("exchange_time")
        if not ex_ts:
            raw_ts = trade.get("timestamp")
            if isinstance(raw_ts, str):
                ex_ts = datetime.fromisoformat(raw_ts)
            elif isinstance(raw_ts, datetime):
                ex_ts = raw_ts
            else:
                return []
            trade["exchange_time"] = ex_ts

        tid = trade.get("tradeId")
        key = (
            (sym, tid) if tid is not None else
            (sym, ex_ts.isoformat(), trade.get("price"), trade.get("shares"), trade.get("sideCode"))
        )
        if key in self.seen_trades:
            self.duplicates_ignored += 1
            return []
        self.seen_trades.add(key)
        if (self.start_time is not None and ex_ts < self.start_time) or (
            self.end_time is not None and ex_ts >= self.end_time
        ):
            self.historical_ignored += 1
            return []
        previous_time = self.last_trade_time.get(sym)
        if previous_time is not None and ex_ts < previous_time:
            self.late_ignored += 1
            return []
        self.last_trade_time[sym] = ex_ts

        # Ensure numeric fields
        if "value" not in trade:
            price = float(trade.get("price", 0.0))
            shares = float(trade.get("shares", 0.0))
            trade["value"] = float(trade.get("transactionValue", price * shares))
        if "lot" not in trade:
            trade["lot"] = float(trade.get("shares", 0.0)) / 100

        window = self.windows[sym]
        window.append(trade)

        metrics = window.get_window_metrics(ex_ts, window_seconds=self.config.window_seconds)
        if not metrics:
            return []

        new_alerts = []
        cooldown_delta = timedelta(seconds=self.config.cooldown_seconds)
        last_time = self.last_alert_time.get(sym)
        if last_time is not None and (ex_ts - last_time) < cooldown_delta:
            return []

        # Rule 1: BREAKOUT_MOMENTUM (MDIA-style)
        if (
            self.config.enable_breakout
            and metrics["count"] >= self.config.breakout_min_trades
            and metrics["haka_pct"] >= self.config.breakout_min_haka_pct
            and metrics["net_flow_val"] >= self.config.breakout_min_net_flow
            and metrics["delta_points"] >= self.config.breakout_min_delta_points
            and metrics["delta_pct"] >= self.config.breakout_min_delta_pct
        ):
            pattern = "BREAKOUT_MOMENTUM"
            alert = RadarAlert(
                timestamp=ex_ts,
                symbol=sym,
                pattern=pattern,
                velocity=metrics["count"],
                haka_pct=round(metrics["haka_pct"], 1),
                net_flow_idr=metrics["net_flow_val"],
                price_open=metrics["open"],
                price_close=metrics["close"],
                delta_points=metrics["delta_points"],
                delta_pct=round(metrics["delta_pct"], 2),
                details=(
                    f"Akumulasi HAKA masif {metrics['haka_pct']:.1f}% (+Rp{metrics['net_flow_val']:,.0f}) "
                    f"mendorong harga +{metrics['delta_points']:.0f} pts dengan kecepatan {metrics['count']} tr/5s."
                ),
            )
            self.last_alert_time[sym] = ex_ts
            self.alerts.append(alert)
            new_alerts.append(alert)
            if self.on_alert:
                self.on_alert(alert)

        # Rule 2: SQUEEZE_BLITZ (NZIA-style)
        elif (
            self.config.enable_squeeze
            and metrics["count"] >= self.config.squeeze_min_trades
            and metrics["haka_pct"] >= self.config.squeeze_min_haka_pct
            and metrics["net_flow_val"] >= self.config.squeeze_min_net_flow
            and metrics["delta_points"] >= self.config.squeeze_min_delta_points
            and metrics["delta_pct"] >= self.config.squeeze_min_delta_pct
        ):
            pattern = "SQUEEZE_BLITZ"
            alert = RadarAlert(
                timestamp=ex_ts,
                symbol=sym,
                pattern=pattern,
                velocity=metrics["count"],
                haka_pct=round(metrics["haka_pct"], 1),
                net_flow_idr=metrics["net_flow_val"],
                price_open=metrics["open"],
                price_close=metrics["close"],
                delta_points=metrics["delta_points"],
                delta_pct=round(metrics["delta_pct"], 2),
                details=(
                    f"Lompatan harga kilat +{metrics['delta_points']:.0f} pts ({metrics['delta_pct']:+.1f}%) "
                    f"dengan velocity {metrics['count']} tr/5s dan HAKA {metrics['haka_pct']:.1f}% (+Rp{metrics['net_flow_val']:,.0f})."
                ),
            )
            self.last_alert_time[sym] = ex_ts
            self.alerts.append(alert)
            new_alerts.append(alert)
            if self.on_alert:
                self.on_alert(alert)

        # Rule 3: HEAVY_ABSORPTION (default: disabled)
        elif (
            self.config.enable_absorption
            and metrics["count"] >= self.config.absorption_min_trades
            and metrics["total_value"] >= self.config.absorption_min_value
            and abs(metrics["delta_points"]) <= self.config.absorption_max_delta_points
        ):
            pattern = "HEAVY_ABSORPTION"
            alert = RadarAlert(
                timestamp=ex_ts,
                symbol=sym,
                pattern=pattern,
                velocity=metrics["count"],
                haka_pct=round(metrics["haka_pct"], 1),
                net_flow_idr=metrics["net_flow_val"],
                price_open=metrics["open"],
                price_close=metrics["close"],
                delta_points=metrics["delta_points"],
                delta_pct=round(metrics["delta_pct"], 2),
                details=(
                    f"Penyerapan volume raksasa Rp{metrics['total_value']:,.0f} pada harga tetap {metrics['close']:.0f} "
                    f"dengan kecepatan {metrics['count']} tr/5s."
                ),
            )
            self.last_alert_time[sym] = ex_ts
            self.alerts.append(alert)
            new_alerts.append(alert)
            if self.on_alert:
                self.on_alert(alert)

        return new_alerts

    @staticmethod
    def ordered_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return one batch in event-time order without changing the caller's list."""
        def sort_time(trade):
            value = trade.get("exchange_time") or trade.get("timestamp")
            if isinstance(value, str):
                try:
                    return datetime.fromisoformat(value)
                except ValueError:
                    pass
            return value if isinstance(value, datetime) else datetime.min.replace(tzinfo=timezone.utc)

        return sorted(
            trades,
            key=lambda trade: (
                sort_time(trade),
                trade.get("tradeId") if trade.get("tradeId") is not None else -1,
            ),
        )

    def process_batch(self, trades: list[dict[str, Any]]) -> list[RadarAlert]:
        """Process a list of trades and return any triggered alerts."""
        alerts = []
        for trade in self.ordered_trades(trades):
            new_alerts = self.process_trade(trade)
            if new_alerts:
                alerts.extend(new_alerts)
        return alerts


def scan_session_radar(
    session_id: str,
    config: RadarConfig | None = None,
    conn=None,
    on_alert: Callable[[RadarAlert], None] | None = None,
) -> dict[str, Any]:
    """Scan a recorded session from PostgreSQL for anomaly patterns."""
    should_close = False
    if conn is None:
        conn = connect_database(readonly=True)
        verify_schema(conn)
        should_close = True

    try:
        session = conn.execute(
            "SELECT * FROM stockbit_ws.sessions WHERE id = %s", (session_id,)
        ).fetchone()
        if not session:
            raise ValueError(f"Sesi {session_id} tidak ditemukan.")

        radar = MarketRadar(
            config=config, on_alert=on_alert,
            start_time=session["started_at"], end_time=session["ended_at"],
        )

        q = """
            SELECT seq, received_at, payload
            FROM stockbit_ws.events
            WHERE session_id = %s AND kind = 'done'
            ORDER BY seq ASC
        """
        rows = conn.execute(q, (session_id,)).fetchall()

        for r in rows:
            for t in r["payload"].get("trades", []):
                code = t.get("symbol")
                tid = t.get("tradeId")
                ts_str = t.get("timestamp")
                if not code or not ts_str:
                    continue

                trade_obj = {
                    "symbol": code,
                    "tradeId": tid,
                    "price": float(t.get("price", 0.0)),
                    "shares": float(t.get("shares", 0.0)),
                    "lot": float(t.get("lot", t.get("shares", 0.0) / 100)),
                    "sideCode": int(t.get("sideCode", 0)),
                    "value": float(t.get("transactionValue", t.get("price", 0.0) * t.get("shares", 0.0))),
                    "timestamp": ts_str,
                    "exchange_time": datetime.fromisoformat(ts_str),
                }
                radar.process_trade(trade_obj)

        return {
            "session_id": session_id,
            "session_symbol": session["symbol"],
            "started_at": session["started_at"],
            "ended_at": session["ended_at"],
            "total_alerts": len(radar.alerts),
            "alerts": [a.to_dict() for a in radar.alerts],
            "raw_alerts": radar.alerts,
            "duplicates_ignored": radar.duplicates_ignored,
            "historical_ignored": radar.historical_ignored,
            "late_ignored": radar.late_ignored,
        }
    finally:
        if should_close and conn is not None and not conn.closed:
            conn.close()


def format_radar_report(scan_res: dict[str, Any]) -> str:
    """Format scan results into a readable Markdown report."""
    sid = scan_res["session_id"]
    sym = scan_res["session_symbol"]
    start_str = timestamp_text(scan_res["started_at"])
    end_str = timestamp_text(scan_res["ended_at"])
    total = scan_res["total_alerts"]
    alerts = scan_res["raw_alerts"]

    lines = [
        f"# Laporan Deteksi Radar Anomali Pasar (Wildcard WS)",
        f"**Session ID**: `{sid}` | **Symbol Filter**: `{sym}` | **Rentang Sesi**: {start_str} s.d. {end_str}",
        f"**Total Anomali Terdeteksi**: **{total} alert**",
        "",
        "## Ringkasan Anomali per Kode Saham",
    ]

    by_sym: dict[str, list[RadarAlert]] = defaultdict(list)
    for a in alerts:
        by_sym[a.symbol].append(a)

    if not by_sym:
        lines.append("Tidak ada anomali yang memicu kriteria deteksi pada sesi ini.")
        return "\n".join(lines)

    lines.append("| Saham | Total Alert | Pola Utama | Detik Alert Pertama (WIB) | Puncak Net Flow (Rp) | Max Velocity |")
    lines.append("|---|:---:|---|:---:|---|:---:|")

    for s, s_alerts in sorted(by_sym.items(), key=lambda item: len(item[1]), reverse=True):
        first_wib = s_alerts[0].timestamp.astimezone(_WIB).strftime("%H:%M:%S")
        patterns = ", ".join(sorted(set(a.pattern for a in s_alerts)))
        max_flow = max(a.net_flow_idr for a in s_alerts)
        max_vel = max(a.velocity for a in s_alerts)
        lines.append(f"| **{s}** | {len(s_alerts)} | {patterns} | {first_wib} | Rp{max_flow:,.0f} | {max_vel} tr/5s |")

    lines.append("")
    lines.append("## Kronologi Log Alert Lengkap")
    lines.append("| Waktu (WIB) | Saham | Pola | Velocity | HAKA % | Net Flow (Rp) | Price (Open -> Close) | ΔP | Rincian |")
    lines.append("|---|:---:|---|:---:|:---:|---|:---:|:---:|---|")

    for a in alerts:
        wib = a.timestamp.astimezone(_WIB).strftime("%H:%M:%S")
        sign = "+" if a.net_flow_idr >= 0 else ""
        flow_str = f"{sign}Rp{a.net_flow_idr:,.0f}".replace(",", ".")
        dp_sign = "+" if a.delta_points > 0 else ""
        lines.append(
            f"| {wib} | **{a.symbol}** | `{a.pattern}` | {a.velocity} tr/5s | {a.haka_pct:.1f}% | {flow_str} | "
            f"{a.price_open:.0f} -> {a.price_close:.0f} | {dp_sign}{a.delta_points:.0f} ({dp_sign}{a.delta_pct:.1f}%) | {a.details} |"
        )

    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stockbit Market Radar & Anomaly Detector")
    parser.add_argument("session_id", nargs="?", help="ID sesi rekaman wildcard yang ingin dipindai (default: sesi terakhir)")
    parser.add_argument("--enable-absorption", action="store_true", help="Aktifkan deteksi HEAVY_ABSORPTION (default: false, fokus ke Breakout & Squeeze)")
    parser.add_argument("--output", help="Path file output untuk menyimpan laporan Markdown/JSON")
    parser.add_argument("--json", action="store_true", help="Cetak output dalam format JSON")
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
            row = conn.execute(
                "SELECT id, symbol FROM stockbit_ws.sessions WHERE symbol = '*' ORDER BY run_no DESC LIMIT 1"
            ).fetchone()
            if not row:
                row = conn.execute(
                    "SELECT id, symbol FROM stockbit_ws.sessions ORDER BY run_no DESC LIMIT 1"
                ).fetchone()
            if not row:
                print("Tidak ada sesi yang ditemukan.")
                return 1
            target_session = row["id"]

        print(f"Memindai anomali pasar dengan Radar untuk sesi: {target_session}...")
        cfg = RadarConfig(enable_absorption=args.enable_absorption)

        def _print_live_alert(a: RadarAlert):
            print(a.format_banner())

        scan_res = scan_session_radar(target_session, config=cfg, conn=conn, on_alert=_print_live_alert)

        if args.json:
            print(json.dumps(scan_res["alerts"], indent=2))
        else:
            report_text = format_radar_report(scan_res)
            print("\n" + report_text + "\n")

            if args.output:
                out_path = Path(args.output)
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(report_text, encoding="utf-8")
                print(f"Laporan radar disimpan ke: {out_path.resolve()}")
            else:
                out_dir = Path("reports")
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / f"radar_{target_session[:8]}.md"
                out_path.write_text(report_text, encoding="utf-8")
                print(f"Laporan radar otomatis disimpan ke: {out_path.resolve()}")

        return 0
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if conn is not None and not conn.closed:
            conn.close()


if __name__ == "__main__":
    sys.exit(main())
