"""Unit tests for the automated recording quality and market descriptive report module.

Run: STOCKBIT_TEST_POSTGRES=1 uv run python -m unittest discover -s tests -p 'test_report.py' -v
"""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
import unittest
import warnings

from fastapi.testclient import TestClient

from stockbit_ws.api import app
from stockbit_ws.postgres import connect_database
from stockbit_ws.report import (
    analyze_session_uniqueness,
    compare_sessions_strict,
    compute_market_descriptive,
    generate_full_report,
    measure_recorder_performance,
)
from test_postgres import PostgresTestMixin
from test_quality import START
from test_quality import book, done


class ReportTests(PostgresTestMixin, unittest.TestCase):
    def test_empty_report_and_storage_never_claim_unmeasured_integrity(self):
        writer = self.writer()
        report = generate_full_report(writer.session_id)
        self.assertIn("PERLU PEMERIKSAAN", report)
        self.assertIn("sesi belum selesai", report)
        self.assertIn("BELUM TERUKUR", report)
        self.assertNotIn("HIGH INTEGRITY", report)
        with connect_database(readonly=True) as conn:
            perf = measure_recorder_performance(conn, writer.session_id)
        self.assertEqual(perf["total_events"], 0)
        self.assertIsNone(perf["needs_async_queue_and_batch"])

    def test_comparison_checks_timestamp_negative_offset_and_empty_samples(self):
        dedicated, wildcard = self.writer(), self.writer("*")
        dedicated.append("done", {"trades": [done(seconds=0)]}, START, 0)
        wildcard.append("done", {"trades": [{**done(), "timestamp": START + timedelta(seconds=1)}]}, START, 0)
        dedicated.close(START + timedelta(seconds=2), 2)
        wildcard.close(START + timedelta(seconds=2), 2)
        with connect_database(readonly=True) as conn:
            comparison = compare_sessions_strict(conn, dedicated.session_id, wildcard.session_id, "COCO")
            self.assertEqual(comparison["discrepancies_count"], 1)
            self.assertIn("timestamp", comparison["discrepancies_details"][0]["differences"])
            self.assertEqual(comparison["client_delay_stats_wildcard_ms"]["negative_count"], 1)
            with self.assertRaises(ValueError):
                compare_sessions_strict(conn, wildcard.session_id, dedicated.session_id, "COCO")
        report = generate_full_report(dedicated.session_id, comparison)
        self.assertIn("nilai/timestamp transaksi berbeda", report)
        empty = self.writer()
        empty.close(START + timedelta(seconds=2), 2)
        with connect_database(readonly=True) as conn:
            comparison = compare_sessions_strict(conn, empty.session_id, wildcard.session_id, "COCO")
        self.assertIsNone(comparison["match_percentage"])
        self.assertIsNone(comparison["client_delay_stats_dedicated_ms"]["p95"])
        self.assertIn("PERLU PEMERIKSAAN", generate_full_report(empty.session_id, comparison))

    def test_locked_crossed_dedup_and_sequence_are_measured_separately(self):
        writer = self.writer()
        writer.append("done", {"trades": [done(), done()]}, START, 0)
        writer.append("book", book("BID", 135), START, 0)
        writer.append("book", book("OFFER", 135), START, 0)
        writer.append("book", book("BID", 136), START, 0)
        writer.close(START, 0)
        with connect_database(readonly=True) as conn:
            market = compute_market_descriptive(conn, writer.session_id, "COCO")
            perf = measure_recorder_performance(conn, writer.session_id)
        self.assertEqual(market["total_trades"], 1)
        self.assertEqual(market["order_book_microstructure"]["locked_book_events"], 1)
        self.assertEqual(market["order_book_microstructure"]["crossed_book_events"], 1)
        self.assertEqual(perf["simultaneous_events_zero_delta"], 3)
        self.assertEqual(perf["sequence_errors"], 0)
        with connect_database() as conn:
            conn.execute("DELETE FROM stockbit_ws.events WHERE session_id=%s AND seq=2", (writer.session_id,))
        with connect_database(readonly=True) as conn:
            self.assertGreater(measure_recorder_performance(conn, writer.session_id)["sequence_errors"], 0)
        self.assertIn("anomali urutan lokal", generate_full_report(writer.session_id))

    @classmethod
    def setUpClass(cls):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        cls.client = TestClient(app)

    def test_uniqueness_detects_trades_with_and_without_ids_and_duplicates(self):
        writer = self.writer(symbol="COCO", started_at=START)
        
        # Batch 1: Two trades with unique IDs
        t1 = {
            "symbol": "COCO", "tradeId": 1001, "price": 100.0, "shares": 1000.0,
            "lot": 10.0, "sideCode": 1, "timestamp": START.isoformat(),
        }
        t2 = {
            "symbol": "COCO", "tradeId": 1002, "price": 105.0, "shares": 500.0,
            "lot": 5.0, "sideCode": 2, "timestamp": START.isoformat(),
        }
        writer.append("done", {"trades": [t1, t2]}, START, 0.1)

        # Batch 2: Duplicate of t1, plus one trade WITHOUT tradeId
        t3_no_id = {
            "symbol": "COCO", "tradeId": None, "price": 102.0, "shares": 2000.0,
            "lot": 20.0, "sideCode": 1, "timestamp": START.isoformat(),
        }
        writer.append("done", {"trades": [t1, t3_no_id]}, START, 0.2)
        writer.close(START, 1.0, "COMPLETED")

        with connect_database(readonly=True) as conn:
            res = analyze_session_uniqueness(conn, writer.session_id)

        self.assertEqual(res["total_trade_records"], 4)
        self.assertEqual(res["trades_with_id"], 3)
        self.assertEqual(res["unique_with_id"], 2)  # 1001 and 1002
        self.assertEqual(res["trades_without_id"], 1)
        self.assertEqual(res["unique_without_id"], 1)
        self.assertEqual(res["unique_trades_total"], 3)
        self.assertEqual(res["duplicate_records"], 1)
        self.assertEqual(len(res["top_duplicates"]), 1)
        self.assertEqual(res["top_duplicates"][0]["tradeId"], 1001)

    def test_recorder_performance_computes_throughput_and_bursts(self):
        writer = self.writer(symbol="BBRI", started_at=START)
        # Append 10 events across 2 seconds
        for i in range(5):
            writer.append("message", {"format": "binary", "size": 50}, START, 0.0)  # delta 0
        for i in range(5):
            writer.append("message", {"format": "binary", "size": 50}, START, 1.0)
        writer.close(START, 2.0, "COMPLETED")

        with connect_database(readonly=True) as conn:
            perf = measure_recorder_performance(conn, writer.session_id)

        self.assertEqual(perf["total_events"], 10)
        self.assertGreaterEqual(perf["peak_events_per_sec"], 5)
        self.assertGreaterEqual(perf["simultaneous_events_zero_delta"], 4)
        self.assertIn("verdict_storage", perf)

    def test_market_descriptive_calculates_haka_haki_and_orderbook_metrics(self):
        writer = self.writer(symbol="ASII", started_at=START)
        
        # 1 HAKA (buy) and 1 HAKI (sell)
        t_buy = {
            "symbol": "ASII", "tradeId": 501, "price": 5000.0, "shares": 10000.0,
            "lot": 100.0, "sideCode": 1, "timestamp": START.isoformat(),
            "transactionValue": 50_000_000.0,
        }
        t_sell = {
            "symbol": "ASII", "tradeId": 502, "price": 4990.0, "shares": 5000.0,
            "lot": 50.0, "sideCode": 2, "timestamp": START.isoformat(),
            "transactionValue": 24_950_000.0,
        }
        writer.append("done", {"trades": [t_buy, t_sell]}, START, 0.5)

        # Orderbook BID and OFFER
        book_bid = {
            "type": "#O", "symbol": "ASII", "side": "BID",
            "levels": [{"price": 4990.0, "shares": 20000, "frequency": 5, "lot": 200.0}],
        }
        book_offer = {
            "type": "#O", "symbol": "ASII", "side": "OFFER",
            "levels": [{"price": 5000.0, "shares": 10000, "frequency": 3, "lot": 100.0}],
        }
        writer.append("book", book_bid, START, 0.6)
        writer.append("book", book_offer, START, 0.7)
        writer.close(START, 1.0, "COMPLETED")

        with connect_database(readonly=True) as conn:
            market = compute_market_descriptive(conn, writer.session_id, "ASII")

        self.assertEqual(market["total_trades"], 2)
        self.assertEqual(market["total_volume_lot"], 150.0)
        self.assertEqual(market["haka_buy"]["count"], 1)
        self.assertEqual(market["haki_sell"]["count"], 1)
        self.assertGreater(market["haka_buy"]["value_idr"], market["haki_sell"]["value_idr"])
        self.assertGreater(market["net_flow_idr"], 0)

        # Check orderbook microstructure
        ob = market["order_book_microstructure"]
        self.assertIsNotNone(ob)
        self.assertEqual(ob["avg_spread_pts"], 10.0)
        self.assertGreater(ob["avg_top1_imbalance"], 0)  # more bid than offer

    def test_strict_comparison_matches_and_detects_missing(self):
        writer_ded = self.writer(symbol="BUMI", started_at=START)
        writer_wld = self.writer(symbol="*", started_at=START)

        # Common trade
        t_common = {
            "symbol": "BUMI", "tradeId": 9001, "price": 200.0, "shares": 1000.0,
            "lot": 10.0, "sideCode": 1, "timestamp": START.isoformat(),
        }
        # Dedicated only trade
        t_ded_only = {
            "symbol": "BUMI", "tradeId": 9002, "price": 200.0, "shares": 2000.0,
            "lot": 20.0, "sideCode": 2, "timestamp": START.isoformat(),
        }

        writer_ded.append("done", {"trades": [t_common, t_ded_only]}, START, 0.1)
        writer_wld.append("done", {"trades": [t_common]}, START, 0.1)

        from datetime import timedelta
        end_time = START + timedelta(seconds=2)
        writer_ded.close(end_time, 2.0, "COMPLETED")
        writer_wld.close(end_time, 2.0, "COMPLETED")

        with connect_database(readonly=True) as conn:
            comp = compare_sessions_strict(conn, writer_ded.session_id, writer_wld.session_id, "BUMI")

        self.assertEqual(comp["matched_trades"], 1)
        self.assertEqual(comp["missing_in_wildcard_count"], 1)
        self.assertEqual(comp["missing_in_wildcard_sample"][0]["tradeId"], 9002)
        self.assertEqual(comp["discrepancies_count"], 0)

    def test_full_markdown_report_generation(self):
        writer = self.writer(symbol="COCO", started_at=START)
        writer.append("connection", {"state": "CONNECTED"}, START, 0.0)
        writer.close(START, 1.0, "COMPLETED")

        report = generate_full_report(writer.session_id)
        self.assertIn("1. Audit Transaksi Unik & Deduplikasi Database", report)
        self.assertIn("3. Pengukuran Kemampuan & Throughput Recorder", report)
        self.assertIn("4. Analisis Deskriptif Pasar & Mikrostruktur", report)
        self.assertIn("VERDICT: KONSISTENSI DATA & KELAYAKAN RISET SINYAL", report)

    def test_api_report_endpoint_returns_json_and_markdown(self):
        writer = self.writer(symbol="COCO", started_at=START)
        writer.append("connection", {"state": "CONNECTED"}, START, 0.0)
        writer.close(START, 1.0, "COMPLETED")

        resp = self.client.get(f"/api/sessions/{writer.session_id}/report")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["session_id"], writer.session_id)
        self.assertIn("uniqueness", data)
        self.assertIn("recorder_performance", data)
        self.assertIn("market_descriptive", data)
        self.assertIn("markdown_report", data)


if __name__ == "__main__":
    unittest.main()
