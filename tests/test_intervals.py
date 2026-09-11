"""Unit tests for the interval activity analysis (1s, 5s, 30s) module.

Run: STOCKBIT_TEST_POSTGRES=1 uv run python -m unittest discover -s tests -p 'test_intervals.py' -v
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest
import warnings

from fastapi.testclient import TestClient

from stockbit_ws.api import app
from stockbit_ws.intervals import (
    build_interval_bars,
    extract_activity_patterns,
    generate_interval_report,
    load_session_trades_and_books,
)
from stockbit_ws.postgres import connect_database
from test_postgres import PostgresTestMixin
from test_quality import START


class IntervalTests(PostgresTestMixin, unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        cls.client = TestClient(app)

    def test_separates_snapshot_from_live_trades_and_deduplicates(self):
        session_start = START
        writer = self.writer(symbol="COCO", started_at=session_start)

        # Pre-connection snapshot trade (timestamp < session_start)
        t_snap = {
            "symbol": "COCO", "tradeId": 101, "price": 100.0, "shares": 1000.0,
            "lot": 10.0, "sideCode": 1, "timestamp": (session_start - timedelta(seconds=10)).isoformat(),
        }
        # Live trade (timestamp >= session_start)
        t_live1 = {
            "symbol": "COCO", "tradeId": 102, "price": 105.0, "shares": 2000.0,
            "lot": 20.0, "sideCode": 2, "timestamp": (session_start + timedelta(seconds=1)).isoformat(),
        }
        # Duplicate of live trade
        t_live1_dup = dict(t_live1)

        writer.append("done", {"trades": [t_snap, t_live1, t_live1_dup]}, session_start, 0.1)
        writer.close(session_start + timedelta(seconds=10), 10.0, "COMPLETED")

        with connect_database(readonly=True) as conn:
            res = load_session_trades_and_books(conn, writer.session_id, "COCO")

        self.assertEqual(len(res["snapshot_trades"]), 1)
        self.assertEqual(res["snapshot_trades"][0]["tradeId"], 101)
        self.assertEqual(len(res["live_trades"]), 1)
        self.assertEqual(res["live_trades"][0]["tradeId"], 102)

    def test_builds_interval_bars_with_ohlc_haka_haki_and_orderbook(self):
        t0 = START
        live_trades = [
            # Bucket 1 (second 0..4)
            {
                "symbol": "BUMI", "tradeId": 1, "price": 200.0, "shares": 1000.0,
                "lot": 10.0, "sideCode": 1, "value": 200_000.0, "exchange_time": t0, "received_at": t0,
            },
            {
                "symbol": "BUMI", "tradeId": 2, "price": 202.0, "shares": 500.0,
                "lot": 5.0, "sideCode": 1, "value": 101_000.0, "exchange_time": t0 + timedelta(seconds=2), "received_at": t0 + timedelta(seconds=2),
            },
            # Bucket 2 (second 5..9)
            {
                "symbol": "BUMI", "tradeId": 3, "price": 201.0, "shares": 3000.0,
                "lot": 30.0, "sideCode": 2, "value": 603_000.0, "exchange_time": t0 + timedelta(seconds=6), "received_at": t0 + timedelta(seconds=6),
            },
        ]

        book_updates = [
            {
                "seq": 1, "received_at": t0 + timedelta(seconds=1), "side": "BID",
                "levels": [{"price": 200.0, "shares": 10000, "lot": 100.0}],
            },
            {
                "seq": 2, "received_at": t0 + timedelta(seconds=1), "side": "OFFER",
                "levels": [{"price": 202.0, "shares": 5000, "lot": 50.0}],
            },
        ]

        bars = build_interval_bars(live_trades, book_updates, interval_seconds=5)
        self.assertEqual(len(bars), 2)

        # Bar 1 checks
        b1 = bars[0]
        self.assertEqual(b1["trade_count"], 2)
        self.assertEqual(b1["open"], 200.0)
        self.assertEqual(b1["close"], 202.0)
        self.assertEqual(b1["price_change"], 2.0)
        self.assertEqual(b1["total_lot"], 15.0)
        self.assertEqual(b1["haka_lot"], 15.0)
        self.assertEqual(b1["haki_lot"], 0.0)
        self.assertEqual(b1["haka_pct"], 100.0)
        self.assertEqual(b1["net_flow_val_idr"], 301_000.0)

        # Order book on Bar 1
        self.assertIsNotNone(b1["order_book"])
        self.assertEqual(b1["order_book"]["best_bid"], 200.0)
        self.assertEqual(b1["order_book"]["best_offer"], 202.0)
        self.assertEqual(b1["order_book"]["spread_pts"], 2.0)
        self.assertGreater(b1["order_book"]["imbalance_top1"], 0.0)  # 100 bid vs 50 offer

        # Bar 2 checks
        b2 = bars[1]
        self.assertEqual(b2["trade_count"], 1)
        self.assertEqual(b2["haki_lot"], 30.0)
        self.assertEqual(b2["haki_pct"], 100.0)
        self.assertEqual(b2["net_flow_val_idr"], -603_000.0)

    def test_extract_activity_patterns(self):
        bars = [
            {"bucket_sec": 1, "net_flow_val_idr": 500_000, "trade_count": 10, "close": 100, "order_book": {"imbalance_top1": 0.5}},
            {"bucket_sec": 2, "net_flow_val_idr": -300_000, "trade_count": 5, "close": 102, "order_book": {"imbalance_top1": -0.4}},
            {"bucket_sec": 3, "net_flow_val_idr": 100_000, "trade_count": 2, "close": 101, "order_book": None},
        ]
        patterns = extract_activity_patterns(bars)
        self.assertEqual(patterns["top_inflows"][0]["bucket_sec"], 1)
        self.assertEqual(patterns["top_outflows"][0]["bucket_sec"], 2)
        self.assertEqual(patterns["top_velocities"][0]["bucket_sec"], 1)

    def test_generate_interval_report_markdown(self):
        writer = self.writer(symbol="COCO", started_at=START)
        t_live = {
            "symbol": "COCO", "tradeId": 201, "price": 100.0, "shares": 1000.0,
            "lot": 10.0, "sideCode": 1, "timestamp": START.isoformat(),
        }
        writer.append("done", {"trades": [t_live]}, START, 0.1)
        writer.close(START + timedelta(seconds=10), 10.0, "COMPLETED")

        report = generate_interval_report(writer.session_id, interval_seconds=5)
        self.assertIn("Analisis Pola Aktivitas per Interval", report)
        self.assertIn("Interval 5 Detik", report)
        self.assertIn("Pola Puncak Akumulasi", report)

    def test_api_interval_endpoint_returns_bars_and_patterns(self):
        writer = self.writer(symbol="COCO", started_at=START)
        t_live = {
            "symbol": "COCO", "tradeId": 301, "price": 100.0, "shares": 1000.0,
            "lot": 10.0, "sideCode": 1, "timestamp": START.isoformat(),
        }
        writer.append("done", {"trades": [t_live]}, START, 0.1)
        writer.close(START + timedelta(seconds=10), 10.0, "COMPLETED")

        resp = self.client.get(f"/api/sessions/{writer.session_id}/intervals?interval=5")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["session_id"], writer.session_id)
        self.assertEqual(data["interval_seconds"], 5)
        self.assertIn("bars", data)
        self.assertIn("patterns", data)

    def test_wildcard_requires_one_symbol_and_never_mixes_prices(self):
        writer = self.writer(symbol="*", started_at=START)
        writer.append("done", {"trades": [
            {"symbol": "BUMI", "tradeId": 1, "price": 200.0, "shares": 1000.0, "sideCode": 1, "timestamp": START.isoformat()},
            {"symbol": "PTRO", "tradeId": 1, "price": 5000.0, "shares": 1000.0, "sideCode": 2, "timestamp": START.isoformat()},
        ]}, START, 0.1)
        writer.close(START + timedelta(seconds=5), 5.0, "COMPLETED")

        with connect_database(readonly=True) as conn:
            with self.assertRaisesRegex(ValueError, "wajib memakai --symbol"):
                load_session_trades_and_books(conn, writer.session_id)
            data = load_session_trades_and_books(conn, writer.session_id, "BUMI")
        self.assertEqual([trade["symbol"] for trade in data["live_trades"]], ["BUMI"])

    def test_empty_bucket_boundary_and_stale_book_are_explicit(self):
        trades = [{
            "symbol": "BUMI", "tradeId": 1, "price": 200.0, "shares": 1000.0,
            "lot": 10.0, "sideCode": 1, "value": 200_000.0,
            "exchange_time": START, "received_at": START,
        }]
        boundary = START + timedelta(seconds=5)
        books = [
            {"seq": 1, "received_at": boundary, "side": "BID", "levels": [{"price": 199.0, "lot": 10.0}]},
            {"seq": 2, "received_at": boundary, "side": "OFFER", "levels": [{"price": 201.0, "lot": 10.0}]},
        ]
        bars = build_interval_bars(
            trades, books, 5, start_time=START,
            end_time=START + timedelta(seconds=15), stale_after=5,
        )
        self.assertEqual(len(bars), 3)
        self.assertIsNone(bars[0]["order_book"])
        self.assertEqual(bars[1]["trade_count"], 0)
        self.assertIsNotNone(bars[1]["order_book"])
        self.assertEqual(bars[2]["book_invalid_reason"], "stale")


if __name__ == "__main__":
    unittest.main()
