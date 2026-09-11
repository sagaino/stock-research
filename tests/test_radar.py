"""Unit tests for stockbit_ws.radar (Real-Time & Replay Market Radar)."""

from datetime import datetime, timedelta, timezone
import unittest

from stockbit_ws.radar import (
    MarketRadar,
    RadarAlert,
    RadarConfig,
    RollingTradeWindow,
    format_radar_report,
)


class TestRollingTradeWindow(unittest.TestCase):
    def test_window_metrics_and_pruning(self):
        window = RollingTradeWindow(max_retention_seconds=30.0)
        t0 = datetime(2026, 9, 7, 8, 30, 0, tzinfo=timezone.utc)

        # 1. Add 10 trades over 2 seconds
        for i in range(10):
            window.append({
                "symbol": "MDIA",
                "price": 230.0 + (i // 5) * 2.0,  # 230 then 232
                "shares": 1000.0,
                "lot": 10.0,
                "value": 230_000.0,
                "sideCode": 1,  # HAKA
                "exchange_time": t0 + timedelta(milliseconds=i * 200),
            })

        metrics = window.get_window_metrics(t0 + timedelta(seconds=2.0), window_seconds=5.0)
        self.assertIsNotNone(metrics)
        self.assertEqual(metrics["count"], 10)
        self.assertEqual(metrics["open"], 230.0)
        self.assertEqual(metrics["close"], 232.0)
        self.assertEqual(metrics["delta_points"], 2.0)
        self.assertEqual(metrics["haka_pct"], 100.0)
        self.assertEqual(metrics["haki_pct"], 0.0)
        self.assertEqual(metrics["net_flow_val"], 2_300_000.0)

        # 2. Add an event 35 seconds later -> old trades should be pruned
        t_late = t0 + timedelta(seconds=35.0)
        window.append({
            "symbol": "MDIA",
            "price": 240.0,
            "shares": 500.0,
            "lot": 5.0,
            "value": 120_000.0,
            "sideCode": 1,
            "exchange_time": t_late,
        })
        self.assertEqual(len(window.trades), 1)
        self.assertEqual(window.trades[0]["price"], 240.0)


class TestMarketRadarRules(unittest.TestCase):
    def setUp(self):
        self.config = RadarConfig(
            window_seconds=5.0,
            cooldown_seconds=30.0,
            breakout_min_trades=50,
            breakout_min_haka_pct=85.0,
            breakout_min_net_flow=500_000_000.0,
            breakout_min_delta_points=2.0,
            squeeze_min_trades=30,
            squeeze_min_haka_pct=75.0,
            squeeze_min_net_flow=250_000_000.0,
            squeeze_min_delta_points=4.0,
            absorption_min_trades=30,
            absorption_min_value=500_000_000.0,
            absorption_max_delta_points=0.0,
        )

    def test_breakout_momentum_trigger(self):
        radar = MarketRadar(config=self.config)
        t0 = datetime(2026, 9, 7, 8, 34, 0, tzinfo=timezone.utc)

        # 50 trades in 3 seconds with high HAKA and +2 points
        trades = []
        for i in range(50):
            p = 232.0 if i < 20 else 234.0
            trades.append({
                "symbol": "MDIA",
                "price": p,
                "shares": 50_000.0,
                "lot": 500.0,
                "value": 11_600_000.0,  # 50 trades * 11.6M = 580 Juta
                "sideCode": 1,  # 100% HAKA
                "exchange_time": t0 + timedelta(milliseconds=i * 60),
            })

        alerts = radar.process_batch(trades)
        self.assertGreaterEqual(len(alerts), 1)
        first_alert = alerts[0]
        self.assertEqual(first_alert.symbol, "MDIA")
        self.assertEqual(first_alert.pattern, "BREAKOUT_MOMENTUM")
        self.assertGreaterEqual(first_alert.velocity, 40)
        self.assertGreaterEqual(first_alert.haka_pct, 85.0)
        self.assertGreaterEqual(first_alert.delta_points, 2.0)
        self.assertIn("MDIA", first_alert.format_banner())

    def test_high_priced_single_tick_is_not_a_percentage_breakout(self):
        radar = MarketRadar(config=self.config)
        t0 = datetime(2026, 9, 7, 8, 34, 0, tzinfo=timezone.utc)
        trades = [{
            "symbol": "PTRO", "tradeId": i, "price": 5650.0 if i < 20 else 5675.0,
            "shares": 10_000.0, "lot": 100.0, "value": 56_500_000.0,
            "sideCode": 1, "exchange_time": t0 + timedelta(milliseconds=i * 50),
        } for i in range(50)]
        self.assertEqual(radar.process_batch(trades), [])

    def test_squeeze_blitz_trigger(self):
        radar = MarketRadar(config=self.config)
        t0 = datetime(2026, 9, 7, 8, 49, 0, tzinfo=timezone.utc)

        # 35 trades in 3 seconds with +6.0 points leap
        trades = []
        for i in range(35):
            p = 200.0 if i < 10 else 206.0
            trades.append({
                "symbol": "NZIA",
                "price": p,
                "shares": 50_000.0,
                "lot": 500.0,
                "value": 10_000_000.0,  # 35 * 10M = 350 Juta
                "sideCode": 1,  # 100% HAKA
                "exchange_time": t0 + timedelta(milliseconds=i * 80),
            })

        alerts = radar.process_batch(trades)
        self.assertGreaterEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.symbol, "NZIA")
        self.assertEqual(alert.pattern, "SQUEEZE_BLITZ")
        self.assertGreaterEqual(alert.delta_points, 4.0)

    def test_heavy_absorption_trigger(self):
        cfg = RadarConfig(
            enable_absorption=True,
            absorption_min_trades=30,
            absorption_min_value=500_000_000.0,
            absorption_max_delta_points=0.0,
        )
        radar = MarketRadar(config=cfg)
        t0 = datetime(2026, 9, 7, 8, 0, 0, tzinfo=timezone.utc)

        # 35 trades in 2 seconds at fixed price 5550.0 (delta = 0) with total value > 500 Juta
        trades = []
        for i in range(35):
            trades.append({
                "symbol": "PTRO",
                "price": 5550.0,
                "shares": 4_000.0,
                "lot": 40.0,
                "value": 22_200_000.0,  # 35 * 22.2M = ~777 Juta
                "sideCode": 2,  # HAKI absorption
                "exchange_time": t0 + timedelta(milliseconds=i * 50),
            })

        alerts = radar.process_batch(trades)
        self.assertGreaterEqual(len(alerts), 1)
        alert = alerts[0]
        self.assertEqual(alert.symbol, "PTRO")
        self.assertEqual(alert.pattern, "HEAVY_ABSORPTION")
        self.assertEqual(alert.delta_points, 0.0)

    def test_cooldown_prevents_spam(self):
        radar = MarketRadar(config=self.config)
        t0 = datetime(2026, 9, 7, 8, 34, 0, tzinfo=timezone.utc)

        def make_burst(start_time):
            res = []
            for i in range(55):
                res.append({
                    "symbol": "MDIA",
                    "price": 232.0 if i < 15 else 236.0,
                    "shares": 60_000.0,
                    "lot": 600.0,
                    "value": 14_000_000.0,
                    "sideCode": 1,
                    "exchange_time": start_time + timedelta(milliseconds=i * 50),
                })
            return res

        # First burst -> triggers
        alerts_1 = radar.process_batch(make_burst(t0))
        self.assertEqual(len(alerts_1), 1)

        # Second burst 5 seconds later (within 30s cooldown) -> suppressed
        t_soon = t0 + timedelta(seconds=5.0)
        alerts_2 = radar.process_batch(make_burst(t_soon))
        self.assertEqual(len(alerts_2), 0)

        # Third burst 35 seconds later (past cooldown) -> triggers
        t_later = t0 + timedelta(seconds=35.0)
        alerts_3 = radar.process_batch(make_burst(t_later))
        self.assertEqual(len(alerts_3), 1)

    def test_duplicate_historical_and_late_trades_do_not_change_window(self):
        t0 = datetime(2026, 9, 7, 8, 34, 0, tzinfo=timezone.utc)
        radar = MarketRadar(config=self.config, start_time=t0)
        historical = {"symbol": "MDIA", "tradeId": 1, "price": 100.0, "shares": 1000.0, "sideCode": 1, "exchange_time": t0 - timedelta(seconds=1)}
        live = {"symbol": "MDIA", "tradeId": 2, "price": 102.0, "shares": 1000.0, "sideCode": 1, "exchange_time": t0 + timedelta(seconds=2)}
        late = {"symbol": "MDIA", "tradeId": 3, "price": 101.0, "shares": 1000.0, "sideCode": 1, "exchange_time": t0 + timedelta(seconds=1)}

        radar.process_trade(historical)
        radar.process_trade(live)
        radar.process_trade(dict(live))
        radar.process_trade(late)

        self.assertEqual(len(radar.windows["MDIA"].trades), 1)
        self.assertEqual(radar.historical_ignored, 1)
        self.assertEqual(radar.duplicates_ignored, 1)
        self.assertEqual(radar.late_ignored, 1)


class TestFormatRadarReport(unittest.TestCase):
    def test_format_report(self):
        alert = RadarAlert(
            timestamp=datetime(2026, 9, 7, 8, 34, 30, tzinfo=timezone.utc),
            symbol="MDIA",
            pattern="BREAKOUT_MOMENTUM",
            velocity=50,
            haka_pct=95.0,
            net_flow_idr=1_200_000_000.0,
            price_open=232.0,
            price_close=236.0,
            delta_points=4.0,
            delta_pct=1.72,
            details="Test detail",
        )
        scan_res = {
            "session_id": "test12345678",
            "session_symbol": "*",
            "started_at": datetime(2026, 9, 7, 8, 0, 0, tzinfo=timezone.utc),
            "ended_at": datetime(2026, 9, 7, 9, 0, 0, tzinfo=timezone.utc),
            "total_alerts": 1,
            "alerts": [alert.to_dict()],
            "raw_alerts": [alert],
        }

        report = format_radar_report(scan_res)
        self.assertIn("MDIA", report)
        self.assertIn("BREAKOUT_MOMENTUM", report)
        self.assertIn("15:34:30", report)
        self.assertIn("Total Anomali Terdeteksi", report)


class TestRadarDatabaseAndAPI(unittest.TestCase):
    def setUp(self):
        import os
        from stockbit_ws.postgres import connect_database, verify_schema
        if not os.environ.get("STOCKBIT_TEST_POSTGRES"):
            self.skipTest("STOCKBIT_TEST_POSTGRES tidak diaktifkan")
        try:
            self.conn = connect_database()
            verify_schema(self.conn)
        except Exception as exc:
            self.skipTest(f"Database tidak tersedia: {exc}")

        from fastapi.testclient import TestClient
        from stockbit_ws.api import app
        self.client = TestClient(app)

    def tearDown(self):
        if hasattr(self, "conn") and self.conn and not self.conn.closed:
            self.conn.close()

    def test_scan_session_and_api_endpoint(self):
        from stockbit_ws.postgres import PostgresRecorder
        from stockbit_ws.radar import scan_session_radar

        start_time = datetime(2026, 9, 7, 8, 30, 0, tzinfo=timezone.utc)
        writer = PostgresRecorder("*", start_time, 15.0)

        # Write 55 trades for MDIA triggering BREAKOUT_MOMENTUM
        trades = []
        for i in range(55):
            trades.append({
                "symbol": "MDIA",
                "tradeId": 99000 + i,
                "price": 232.0 if i < 15 else 234.0,
                "shares": 60_000.0,
                "lot": 600.0,
                "transactionValue": 14_000_000.0,
                "sideCode": 1,
                "timestamp": (start_time + timedelta(milliseconds=i * 50)).isoformat(),
            })

        writer.append("done", {"trades": trades}, start_time, 0.5)
        writer.close(start_time + timedelta(seconds=10), 10.0, "COMPLETED")

        # 1. Test scan_session_radar
        scan_res = scan_session_radar(writer.session_id, conn=self.conn)
        self.assertEqual(scan_res["session_id"], writer.session_id)
        self.assertGreaterEqual(scan_res["total_alerts"], 1)
        self.assertEqual(scan_res["alerts"][0]["symbol"], "MDIA")
        self.assertEqual(scan_res["alerts"][0]["pattern"], "BREAKOUT_MOMENTUM")

        # 2. Test GET /api/sessions/{session_id}/radar
        resp = self.client.get(f"/api/sessions/{writer.session_id}/radar")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["session_id"], writer.session_id)
        self.assertGreaterEqual(data["total_alerts"], 1)
        self.assertIn("alerts", data)
        self.assertIn("markdown_report", data)


if __name__ == "__main__":
    unittest.main()
