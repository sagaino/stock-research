"""Unit tests for stockbit_ws.sniper (Scout & Sniper Architecture)."""

from datetime import datetime, timedelta, timezone
from io import StringIO
import unittest

from stockbit_ws.cli import Dashboard
from stockbit_ws.logger import SafeLogger
from stockbit_ws.quality import Clock
from stockbit_ws.radar import RadarAlert
from stockbit_ws.sniper import (
    SniperConfig,
    SniperManager,
    SniperSlot,
    SniperState,
)


class TestSniperLifecycle(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 9, 7, 8, 30, 0, tzinfo=timezone.utc)
        self.config = SniperConfig(
            max_slots=5,
            observation_timeout_seconds=10.0,
            auto_release_delay_seconds=3.0,
            target_tp_pct=3.0,
            stop_loss_pct=1.5,
            stop_loss_ticks=2,
            cooldown_seconds=30.0,
            min_follow_through_haka_lots=0.0,
            min_stock_price=0.0,
        )
        self.events = []
        self.manager = SniperManager(
            config=self.config,
            on_event=lambda msg, slot: self.events.append(msg),
        )

    def _make_alert(self, symbol: str, price: float = 100.0, offset_sec: float = 0.0) -> RadarAlert:
        return RadarAlert(
            timestamp=self.t0 + timedelta(seconds=offset_sec),
            symbol=symbol,
            pattern="BREAKOUT_MOMENTUM",
            velocity=50,
            haka_pct=95.0,
            net_flow_idr=1_000_000_000,
            price_open=price - 2,
            price_close=price,
            delta_points=2.0,
            delta_pct=2.0,
            details="Test alert",
        )

    def test_slot_allocation_up_to_5_slots(self):
        # 1. Allocate 5 slots
        symbols = ["MDIA", "NZIA", "KOTA", "IMPC", "PTRO"]
        for i, sym in enumerate(symbols):
            alert = self._make_alert(sym, price=200.0 + i * 10)
            slot = self.manager.handle_radar_alert(alert)
            self.assertIsNotNone(slot)
            self.assertEqual(slot.slot_id, i + 1)
            self.assertEqual(slot.symbol, sym)
            self.assertEqual(slot.state, SniperState.OBSERVING)

        self.assertEqual(self.manager.active_count(), 5)

        # 2. 6th candidate must be rejected because slots are full
        alert_6 = self._make_alert("FAST", price=150.0)
        slot_6 = self.manager.handle_radar_alert(alert_6)
        self.assertIsNone(slot_6)
        self.assertTrue(any("Semua 5 slot penuh" in e for e in self.events))

    def test_radar_reinforcement_reuses_existing_slot(self):
        alert1 = self._make_alert("MDIA", price=230.0, offset_sec=0.0)
        slot1 = self.manager.handle_radar_alert(alert1)
        self.assertIsNotNone(slot1)
        self.assertEqual(slot1.slot_id, 1)

        # Second alert for MDIA 3 seconds later
        alert2 = self._make_alert("MDIA", price=234.0, offset_sec=3.0)
        slot2 = self.manager.handle_radar_alert(alert2)
        self.assertEqual(slot2.slot_id, 1)
        self.assertEqual(self.manager.active_count(), 1)
        self.assertIn("reinforcement", slot1.reason)

    def test_observation_timeout_auto_aborts_and_releases(self):
        alert = self._make_alert("MDIA", price=230.0, offset_sec=0.0)
        slot = self.manager.handle_radar_alert(alert)
        self.assertEqual(slot.state, SniperState.OBSERVING)

        # Advance time by 5s -> still observing
        t_5 = self.t0 + timedelta(seconds=5.0)
        self.manager.tick(t_5)
        self.assertEqual(slot.state, SniperState.OBSERVING)
        self.assertAlmostEqual(slot.ttl_seconds, 5.0)

        # Advance time by 10s (timeout) -> ABORTED
        t_10 = self.t0 + timedelta(seconds=10.0)
        self.manager.tick(t_10)
        self.assertEqual(slot.state, SniperState.ABORTED)
        self.assertIn("Timeout 10s", slot.reason)

        # Advance time by another 3.1s (auto_release_delay_seconds) -> reset to IDLE
        t_13 = self.t0 + timedelta(seconds=13.1)
        self.manager.tick(t_13)
        self.assertEqual(slot.state, SniperState.IDLE)
        self.assertIsNone(slot.symbol)
        self.assertEqual(self.manager.active_count(), 0)
        self.assertEqual(len(self.manager.history), 1)
        self.assertEqual(self.manager.history[0]["outcome"], "ABORTED_TIMEOUT")

    def test_entry_and_take_profit_flow(self):
        alert = self._make_alert("MDIA", price=230.0, offset_sec=0.0)
        slot = self.manager.handle_radar_alert(alert)

        # Trade breaks above ref_price (232 > 230) -> ENTERED
        t_entry = self.t0 + timedelta(seconds=2.0)
        self.manager.process_trade({
            "symbol": "MDIA",
            "price": 232.0,
            "sideCode": 1,  # HAKA
            "exchange_time": t_entry,
        })
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertEqual(slot.entry_price, 232.0)
        self.assertGreater(slot.target_price, 232.0)
        self.assertLess(slot.stop_loss_price, 232.0)

        # Price hits target (e.g. 240 >= target_price) -> EXIT_TP
        t_tp = self.t0 + timedelta(seconds=8.0)
        self.manager.process_trade({
            "symbol": "MDIA",
            "price": 240.0,
            "sideCode": 1,
            "exchange_time": t_tp,
        })
        self.assertEqual(slot.state, SniperState.EXIT_TP)
        self.assertGreater(slot.pnl_pct, 3.0)
        self.assertIn("TP HIT", slot.reason)
        self.assertEqual(self.manager.history[-1]["outcome"], "TAKE_PROFIT")

    def test_entry_and_cut_loss_flow(self):
        alert = self._make_alert("MDIA", price=230.0, offset_sec=0.0)
        slot = self.manager.handle_radar_alert(alert)

        # Repeated HAKA at the reference price is not confirmation.
        t_entry = self.t0 + timedelta(seconds=1.0)
        self.manager.process_trade({"symbol": "MDIA", "price": 230.0, "sideCode": 1, "exchange_time": t_entry})
        self.manager.process_trade({"symbol": "MDIA", "price": 230.0, "sideCode": 1, "exchange_time": t_entry})
        self.assertEqual(slot.state, SniperState.OBSERVING)
        self.manager.process_trade({"symbol": "MDIA", "price": 232.0, "sideCode": 1, "exchange_time": t_entry})
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertEqual(slot.entry_price, 232.0)

        # Price drops below stop_loss_price (e.g. 226 <= 228) -> EXIT_CL
        t_cl = self.t0 + timedelta(seconds=4.0)
        self.manager.process_trade({
            "symbol": "MDIA",
            "price": 226.0,
            "sideCode": 2,  # HAKI
            "exchange_time": t_cl,
        })
        self.assertEqual(slot.state, SniperState.EXIT_CL)
        self.assertLess(slot.pnl_pct, 0.0)
        self.assertIn("CL HIT", slot.reason)
        self.assertEqual(self.manager.history[-1]["outcome"], "CUT_LOSS")

    def test_slot_recycling_allows_new_candidate(self):
        # Fill slot 0 at t0
        self.manager.handle_radar_alert(self._make_alert("SYM0", price=100, offset_sec=0.0))
        # Fill slots 1-4 at t0 + 5s
        for i in range(1, 5):
            self.manager.handle_radar_alert(self._make_alert(f"SYM{i}", price=100, offset_sec=5.0))
        self.assertEqual(self.manager.active_count(), 5)

        # At t0 + 11s: slot 0 (elapsed 11s) aborts, slots 1-4 (elapsed 6s) still observing
        t_abort = self.t0 + timedelta(seconds=11.0)
        self.manager.tick(t_abort)
        self.assertEqual(self.manager.slots[0].state, SniperState.ABORTED)
        self.assertEqual(self.manager.slots[1].state, SniperState.OBSERVING)

        # Auto release delay 3s later (at t0 + 14.5s): slot 0 is released to IDLE
        t_release = self.t0 + timedelta(seconds=14.5)
        self.manager.tick(t_release)
        self.assertEqual(self.manager.slots[0].state, SniperState.IDLE)
        self.assertEqual(self.manager.active_count(), 4)

        # Now slot 0 should accept a new candidate
        new_slot = self.manager.handle_radar_alert(self._make_alert("NEW1", price=500, offset_sec=14.5))
        self.assertIsNotNone(new_slot)
        self.assertEqual(new_slot.symbol, "NEW1")
        self.assertEqual(self.manager.active_count(), 5)

    def test_order_book_depth_reinforcement(self):
        alert = self._make_alert("MDIA", price=230.0)
        slot = self.manager.handle_radar_alert(alert)
        self.manager.process_book({
            "symbol": "MDIA",
            "bids": [{"lot": 5000}, {"lot": 4000}, {"lot": 3000}],
            "offers": [{"lot": 1000}, {"lot": 1000}, {"lot": 1000}],
        })
    def test_entered_max_holding_timeout_auto_exits(self):
        alert = self._make_alert("MDIA", price=230.0)
        slot = self.manager.handle_radar_alert(alert)

        # Trigger entry at t0 + 1s
        t_entry = self.t0 + timedelta(seconds=1.0)
        self.manager.process_trade({
            "symbol": "MDIA",
            "price": 232.0,
            "sideCode": 1,
            "exchange_time": t_entry,
        })
        self.assertEqual(slot.state, SniperState.ENTERED)

        # Advance time by 100s (below 180s holding limit) -> still ENTERED
        t_100 = t_entry + timedelta(seconds=100.0)
        self.manager.tick(t_100)
        self.assertEqual(slot.state, SniperState.ENTERED)

        # Advance time by 181s (exceeds 180s holding limit) -> EXIT_TIMEOUT
        t_timeout = t_entry + timedelta(seconds=181.0)
        self.manager.tick(t_timeout)
        self.assertEqual(slot.state, SniperState.EXIT_TIMEOUT)
        self.assertIn("Stagnan", slot.reason)
        self.assertEqual(self.manager.history[-1]["outcome"], "EXIT_TIMEOUT")

        # Auto release delay 3s later -> reset to IDLE
        t_release = t_timeout + timedelta(seconds=3.5)
        self.manager.tick(t_release)
        self.assertEqual(slot.state, SniperState.IDLE)
        self.assertEqual(self.manager.active_count(), 0)

    def test_exclude_big_caps(self):
        # By default exclude_big_caps is True
        alert_bbca = self._make_alert("BBCA", price=6600.0)
        slot_bbca = self.manager.handle_radar_alert(alert_bbca)
        self.assertIsNone(slot_bbca)

        alert_bumi = self._make_alert("BUMI", price=220.0)
        slot_bumi = self.manager.handle_radar_alert(alert_bumi)
        self.assertIsNone(slot_bumi)

        # When disabled, big caps should be accepted
        cfg_allow = SniperConfig(exclude_big_caps=False)
        mgr_allow = SniperManager(config=cfg_allow)
        slot = mgr_allow.handle_radar_alert(alert_bbca)
        self.assertIsNotNone(slot)
        self.assertEqual(slot.symbol, "BBCA")

    def test_cut_loss_cooldown_prevents_revenge_trading(self):
        alert = self._make_alert("NZIA", price=190.0)
        slot = self.manager.handle_radar_alert(alert)
        self.assertIsNotNone(slot)

        # Trigger entry
        t_entry = self.t0 + timedelta(seconds=1.0)
        self.manager.process_trade({"symbol": "NZIA", "price": 192.0, "sideCode": 1, "exchange_time": t_entry})
        self.assertEqual(slot.state, SniperState.ENTERED)

        # Trigger CL
        t_cl = self.t0 + timedelta(seconds=5.0)
        self.manager.process_trade({"symbol": "NZIA", "price": 185.0, "sideCode": 2, "exchange_time": t_cl})
        self.assertEqual(slot.state, SniperState.EXIT_CL)

        # Reset slot
        self.manager.tick(t_cl + timedelta(seconds=5.0))
        self.assertEqual(slot.state, SniperState.IDLE)

        # New alert 60 seconds later (within 1800s cl cooldown) must be ignored
        alert_again = self._make_alert("NZIA", price=190.0, offset_sec=65.0)
        slot_again = self.manager.handle_radar_alert(alert_again)
        self.assertIsNone(slot_again)

    def test_focus_pattern_filtering(self):
        alert_breakout = self._make_alert("MDIA", price=230.0)
        slot_bo = self.manager.handle_radar_alert(alert_breakout)
        self.assertIsNotNone(slot_bo)

        # Squeeze alert should be filtered out under default BREAKOUT_MOMENTUM focus
        alert_sq = RadarAlert(
            timestamp=self.t0,
            symbol="KOTA",
            pattern="SQUEEZE_BLITZ",
            velocity=50,
            haka_pct=95.0,
            net_flow_idr=1_000_000,
            price_open=200,
            price_close=202,
            delta_points=2,
            delta_pct=1.0,
            details="Squeeze",
        )
        slot_sq = self.manager.handle_radar_alert(alert_sq)
        self.assertIsNone(slot_sq)

    def test_financial_accounting_in_history(self):
        alert = self._make_alert("EKAD", price=430.0)
        slot = self.manager.handle_radar_alert(alert)
        self.assertIsNotNone(slot)

        # Enter @ 430
        t_in = self.t0 + timedelta(seconds=1.0)
        self.manager.process_trade({"symbol": "EKAD", "price": 432.0, "sideCode": 1, "exchange_time": t_in})
        self.assertEqual(slot.state, SniperState.ENTERED)

        # TP hit @ 446
        t_out = self.t0 + timedelta(seconds=10.0)
        self.manager.process_trade({"symbol": "EKAD", "price": 450.0, "sideCode": 1, "exchange_time": t_out})
        self.assertEqual(slot.state, SniperState.EXIT_TP)

        record = self.manager.history[-1]
        self.assertIn("lots", record)
        self.assertIn("fee_total", record)
        self.assertIn("gross_idr", record)
        self.assertIn("net_idr", record)
        self.assertGreater(record["lots"], 0)
        self.assertGreater(record["fee_total"], 0)
        self.assertGreater(record["net_idr"], 0)
        self.assertEqual(record["alert_velocity"], 50)
        self.assertEqual(record["alert_haka_pct"], 95.0)
        self.assertEqual(record["alert_delta_pct"], 2.0)
        self.assertEqual(record["observing_done_count"], 1)
        self.assertIn("observing_total_value_idr", record)

    def test_follow_through_haka_lots_filter(self):
        cfg = SniperConfig(
            max_slots=5,
            observation_timeout_seconds=10.0,
            min_follow_through_haka_lots=100.0,
        )
        mgr = SniperManager(config=cfg)
        alert = self._make_alert("MDIA", price=230.0)
        slot = mgr.handle_radar_alert(alert)
        self.assertIsNotNone(slot)

        # 1. Trade with small HAKA (20 lots) -> price condition met, but lots (20 < 100) -> stays OBSERVING
        t1 = self.t0 + timedelta(seconds=1.0)
        mgr.process_trade({
            "symbol": "MDIA",
            "price": 232.0,
            "sideCode": 1,
            "lot": 20.0,
            "exchange_time": t1,
        })
        self.assertEqual(slot.state, SniperState.OBSERVING)
        self.assertEqual(slot.observing_haka_lots, 20.0)

        # 2. Trade with another small HAKA (30 lots) -> total 50 lots (< 100) -> stays OBSERVING
        t2 = self.t0 + timedelta(seconds=2.0)
        mgr.process_trade({
            "symbol": "MDIA",
            "price": 232.0,
            "sideCode": 1,
            "lot": 30.0,
            "exchange_time": t2,
        })
        self.assertEqual(slot.state, SniperState.OBSERVING)
        self.assertEqual(slot.observing_haka_lots, 50.0)

        # 3. Trade with big HAKA (60 lots) -> total 110 lots (>= 100) -> transitions to ENTERED!
        t3 = self.t0 + timedelta(seconds=3.0)
        mgr.process_trade({
            "symbol": "MDIA",
            "price": 232.0,
            "sideCode": 1,
            "lot": 60.0,
            "exchange_time": t3,
        })
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertEqual(slot.entry_price, 232.0)
        self.assertEqual(slot.observing_haka_lots, 110.0)

    def test_stock_price_band_filtering(self):
        # Default config has min_stock_price=200.0
        cfg = SniperConfig(min_stock_price=200.0, max_stock_price=1000.0)
        mgr = SniperManager(config=cfg)

        # 1. Alert with price < 200 (e.g. 150) must be rejected
        alert_low = self._make_alert("FAST", price=150.0)
        slot_low = mgr.handle_radar_alert(alert_low)
        self.assertIsNone(slot_low)

        # 2. Alert with price > 1000 (e.g. 1500) must be rejected
        alert_high = self._make_alert("IMPC", price=1500.0)
        slot_high = mgr.handle_radar_alert(alert_high)
        self.assertIsNone(slot_high)

        # 3. Alert within band (200 <= price <= 1000, e.g. 250) must be accepted
        alert_ok = self._make_alert("MDIA", price=250.0)
        slot_ok = mgr.handle_radar_alert(alert_ok)
        self.assertIsNotNone(slot_ok)
        self.assertEqual(slot_ok.symbol, "MDIA")

    def test_default_min_stock_price_is_50(self):
        cfg = SniperConfig()
        self.assertEqual(cfg.min_stock_price, 50.0)
        mgr = SniperManager(config=cfg)

        # Price < 50 (e.g. 48) rejected
        alert_below_50 = self._make_alert("PENY", price=48.0)
        self.assertIsNone(mgr.handle_radar_alert(alert_below_50))

        # Price >= 50 (e.g. 75) accepted
        alert_75 = self._make_alert("GULA", price=75.0)
        self.assertIsNotNone(mgr.handle_radar_alert(alert_75))



class TestDashboardSniperIntegration(unittest.TestCase):
    def test_dashboard_with_sniper_updates_table(self):
        logger = SafeLogger(output=StringIO())
        clock = Clock()
        config = SniperConfig(max_slots=5)
        sniper = SniperManager(config=config)
        output = StringIO()
        dashboard = Dashboard("COCO", logger, output=output, clock=clock, sniper=sniper)

        # Trigger radar alert
        alert = RadarAlert(
            timestamp=clock.now(),
            symbol="MDIA",
            pattern="BREAKOUT_MOMENTUM",
            velocity=60,
            haka_pct=90.0,
            net_flow_idr=500_000_000,
            price_open=230,
            price_close=232,
            delta_points=2,
            delta_pct=0.9,
            details="Test",
        )
        sniper.handle_radar_alert(alert)

        # Render dashboard
        dashboard.render()
        out = output.getvalue()
        self.assertIn("SNIPER ACTIVE SLOTS (1/5 AKTIF)", out)
        self.assertIn("MDIA", out)
        self.assertIn("OBSERVING", out)

        # Summary
        dashboard.summary()


class TestTapeReadingFeatures(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 9, 7, 8, 30, 0, tzinfo=timezone.utc)
        self.config = SniperConfig(
            max_slots=1,
            enable_orderbook_tape_reading=True,
            dynamic_tp_refill_lots=20_000.0,
            dynamic_cl_absorb_lots=15_000.0,
            absorption_hold_extension_seconds=180.0,
            max_holding_seconds=130.0,
            min_follow_through_haka_lots=0.0,
            min_haka_streak=1,
            min_stock_price=0.0,
        )
        self.events = []
        self.manager = SniperManager(config=self.config, on_event=lambda msg, slot: self.events.append(msg))

    def _make_alert(self, symbol: str = "MDIA", price: float = 236.0) -> RadarAlert:
        return RadarAlert(
            timestamp=self.t0,
            symbol=symbol,
            pattern="BREAKOUT_MOMENTUM",
            velocity=60,
            haka_pct=95.0,
            net_flow_idr=500_000_000,
            price_open=price - 4,
            price_close=price - 2,
            delta_points=2.0,
            delta_pct=0.9,
            details="Alert",
        )

    def test_dynamic_tp_on_iceberg_offer_refill(self):
        slot = self.manager.handle_radar_alert(self._make_alert("MDIA", 236.0))
        # Enter at 236
        self.manager.process_trade({"symbol": "MDIA", "price": 236.0, "sideCode": 1, "exchange_time": self.t0})
        self.assertEqual(slot.state, SniperState.ENTERED)

        # Price rallies to 240
        t1 = self.t0 + timedelta(seconds=10.0)
        self.manager.process_trade({"symbol": "MDIA", "price": 240.0, "sideCode": 1, "exchange_time": t1})
        self.assertEqual(slot.peak_price, 240.0)

        # Offer book receives initial snapshot at 240 (30,000 lot)
        self.manager.process_book({
            "symbol": "MDIA", "side": "OFFER",
            "levels": [{"price": 240.0, "lot": 30_000.0, "shares": 3_000_000, "frequency": 50}],
        }, current_time=t1)

        # Offer book receives iceberg refill #1 at 240 (+35,000 lot -> 65,000 lot)
        t2 = self.t0 + timedelta(seconds=20.0)
        self.manager.process_book({
            "symbol": "MDIA", "side": "OFFER",
            "levels": [{"price": 240.0, "lot": 65_000.0, "shares": 6_500_000, "frequency": 100}],
        }, current_time=t2)
        # Also provide best bid at 238
        self.manager.process_book({
            "symbol": "MDIA", "side": "BID",
            "levels": [{"price": 238.0, "lot": 20_000.0, "shares": 2_000_000, "frequency": 40}],
        }, current_time=t2)

        # Price retreats to 238 with HAKI after Strike 1:
        # Must NOT exit yet because min_refill_strikes = 2 (Chance 1 given to buyer!)
        t3 = self.t0 + timedelta(seconds=25.0)
        self.manager.process_trade({"symbol": "MDIA", "price": 238.0, "sideCode": 2, "exchange_time": t3})
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertEqual(slot.active_offer_refill_strikes.get(240.0), 1)

        # Buyer HAKAs aggressively, consuming 240 offer down to 5,000 lot:
        t4 = self.t0 + timedelta(seconds=28.0)
        self.manager.process_book({
            "symbol": "MDIA", "side": "OFFER",
            "levels": [{"price": 240.0, "lot": 5_000.0, "shares": 500_000, "frequency": 10}],
        }, current_time=t4)

        # Seller refills again at 240 (+30,000 lot -> 35,000 lot, Strike 2!):
        t5 = self.t0 + timedelta(seconds=30.0)
        self.manager.process_book({
            "symbol": "MDIA", "side": "OFFER",
            "levels": [{"price": 240.0, "lot": 35_000.0, "shares": 3_500_000, "frequency": 80}],
        }, current_time=t5)
        self.assertEqual(slot.active_offer_refill_strikes.get(240.0), 2)

        # Price retreats again to 238 with HAKI:
        t6 = self.t0 + timedelta(seconds=35.0)
        self.manager.process_trade({"symbol": "MDIA", "price": 238.0, "sideCode": 2, "exchange_time": t6})

        # Now 2-strike confirmation is complete -> Must trigger Dynamic TP at 238!
        self.assertEqual(slot.state, SniperState.EXIT_TP)
        self.assertIn("Dynamic TP", slot.reason)
        self.assertEqual(slot.current_price, 238.0)
        self.assertAlmostEqual(slot.pnl_pct, 0.85, places=2)

    def test_support_absorption_defends_position_and_extends_hold(self):
        slot = self.manager.handle_radar_alert(self._make_alert("MDIA", 238.0))
        # Enter at 238
        self.manager.process_trade({"symbol": "MDIA", "price": 238.0, "sideCode": 1, "exchange_time": self.t0})
        self.assertEqual(slot.state, SniperState.ENTERED)

        # Feed bid support at the tick-aligned 236 stop with massive lot, then refill.
        t1 = self.t0 + timedelta(seconds=30.0)
        self.manager.process_book({
            "symbol": "MDIA", "side": "BID",
            "levels": [{"price": 236.0, "lot": 50_000.0, "shares": 5_000_000, "frequency": 80}],
        }, current_time=t1)
        t2 = self.t0 + timedelta(seconds=40.0)
        self.manager.process_book({
            "symbol": "MDIA", "side": "BID",
            "levels": [{"price": 236.0, "lot": 90_000.0, "shares": 9_000_000, "frequency": 150}],
        }, current_time=t2)

        # Price drops to support 236 with HAKI
        t3 = self.t0 + timedelta(seconds=50.0)
        self.manager.process_trade({"symbol": "MDIA", "price": 236.0, "sideCode": 2, "exchange_time": t3})

        # Position must NOT be cut loss because support is absorbed!
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertIn("diabsorpsi", slot.reason)

        # Advance holding time to 110s (approaching 130s base limit)
        t4 = self.t0 + timedelta(seconds=115.0)
        self.manager.process_book({
            "symbol": "MDIA", "side": "BID",
            "levels": [{"price": 236.0, "lot": 90_000.0, "shares": 9_000_000, "frequency": 150}],
        }, current_time=t4)
        self.manager.process_trade({"symbol": "MDIA", "price": 236.0, "sideCode": 1, "exchange_time": t4})
        # Holding time should be extended by +180s!
        self.assertTrue(slot.hold_extended)
        self.assertEqual(slot.effective_max_holding_seconds, 130.0 + 180.0)

        # At t0 + 140s (which would normally timeout under 130s), slot must STILL BE ENTERED
        t5 = self.t0 + timedelta(seconds=140.0)
        self.manager.tick(t5)
        self.assertEqual(slot.state, SniperState.ENTERED)


class TestSniperHybridMode(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 9, 7, 8, 30, 0, tzinfo=timezone.utc)
        self.config = SniperConfig(
            max_slots=5,
            observation_timeout_seconds=10.0,
            auto_release_delay_seconds=3.0,
            target_tp_pct=3.0,
            stop_loss_pct=1.5,
            stop_loss_ticks=2,
            min_follow_through_haka_lots=0.0,
            min_haka_streak=1,
            min_stock_price=0.0,
            enable_orderbook_tape_reading=True,
            enable_hybrid_mode=True,
            hybrid_scalp_ratio=0.5,
            hybrid_runner_max_hold_seconds=900.0,
            trade_capital_idr=550_000.0,
        )
        self.events = []
        self.manager = SniperManager(
            config=self.config,
            on_event=lambda msg, slot: self.events.append(msg),
        )

    def _make_alert(self, symbol: str, price: float) -> RadarAlert:
        return RadarAlert(
            timestamp=self.t0,
            symbol=symbol,
            pattern="BREAKOUT_MOMENTUM",
            velocity=50,
            haka_pct=95.0,
            net_flow_idr=1_000_000_000,
            price_open=price - 4,
            price_close=price - 2,
            delta_points=2.0,
            delta_pct=0.9,
            details="Alert",
        )

    def test_hybrid_lot_allocation_50_50(self):
        slot = self.manager.handle_radar_alert(self._make_alert("MDIA", 236.0))
        self.manager.process_trade({"symbol": "MDIA", "price": 236.0, "sideCode": 1, "exchange_time": self.t0})
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertTrue(slot.is_hybrid)
        # 550,000 / (236 * 100) = 23 lots
        self.assertEqual(slot.total_lots, 23)
        self.assertEqual(slot.tranche1_lots, 12)  # 50% rounded
        self.assertEqual(slot.tranche2_lots, 11)  # remaining
        self.assertEqual(slot.tranche1_status, "PENDING")
        self.assertEqual(slot.tranche2_status, "PENDING")

    def test_hybrid_lot_allocation_70_30(self):
        self.config.hybrid_scalp_ratio = 0.7
        slot = self.manager.handle_radar_alert(self._make_alert("MDIA", 236.0))
        self.manager.process_trade({"symbol": "MDIA", "price": 236.0, "sideCode": 1, "exchange_time": self.t0})
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertTrue(slot.is_hybrid)
        self.assertEqual(slot.total_lots, 23)
        self.assertEqual(slot.tranche1_lots, 16)  # 23 * 0.7 = 16.1 -> 16
        self.assertEqual(slot.tranche2_lots, 7)

    def test_hybrid_fallback_on_single_lot(self):
        # Set small capital so only 1 lot is purchased
        self.config.trade_capital_idr = 25_000.0
        slot = self.manager.handle_radar_alert(self._make_alert("MDIA", 236.0))
        self.manager.process_trade({"symbol": "MDIA", "price": 236.0, "sideCode": 1, "exchange_time": self.t0})
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertFalse(slot.is_hybrid)  # Fallback to single-tranche
        self.assertEqual(slot.total_lots, 1)

    def test_hybrid_partial_tp_and_runner_completion(self):
        slot = self.manager.handle_radar_alert(self._make_alert("MDIA", 236.0))
        self.manager.process_trade({"symbol": "MDIA", "price": 236.0, "sideCode": 1, "exchange_time": self.t0})
        self.assertEqual(slot.state, SniperState.ENTERED)

        # 1. Price reaches 242 and iceberg refill occurs at 242
        t1 = self.t0 + timedelta(seconds=20.0)
        self.manager.process_trade({"symbol": "MDIA", "price": 242.0, "sideCode": 1, "exchange_time": t1})
        self.manager.process_book({
            "symbol": "MDIA", "side": "OFFER",
            "levels": [{"price": 242.0, "lot": 50_000.0, "shares": 5_000_000, "frequency": 100}],
        }, current_time=t1)
        # Refill #1 at 242 (+45,000 lot -> 95,000 lot)
        t2 = self.t0 + timedelta(seconds=25.0)
        self.manager.process_book({
            "symbol": "MDIA", "side": "OFFER",
            "levels": [{"price": 242.0, "lot": 95_000.0, "shares": 9_500_000, "frequency": 150}],
        }, current_time=t2)
        self.manager.process_book({
            "symbol": "MDIA", "side": "BID",
            "levels": [{"price": 240.0, "lot": 30_000.0, "shares": 3_000_000, "frequency": 50}],
        }, current_time=t2)

        # Strike 1 tolerated: price dips to 240 with HAKI, T1 must remain PENDING!
        t3 = self.t0 + timedelta(seconds=30.0)
        self.manager.process_trade({"symbol": "MDIA", "price": 240.0, "sideCode": 2, "exchange_time": t3})
        self.assertEqual(slot.tranche1_status, "PENDING")

        # Buyer eats 242 offer down to 5,000 lot
        t3_b = self.t0 + timedelta(seconds=32.0)
        self.manager.process_book({
            "symbol": "MDIA", "side": "OFFER",
            "levels": [{"price": 242.0, "lot": 5_000.0, "shares": 500_000, "frequency": 10}],
        }, current_time=t3_b)

        # Seller refills again at 242 (+35,000 lot -> 40,000 lot, Strike 2!)
        t3_c = self.t0 + timedelta(seconds=35.0)
        self.manager.process_book({
            "symbol": "MDIA", "side": "OFFER",
            "levels": [{"price": 242.0, "lot": 40_000.0, "shares": 4_000_000, "frequency": 90}],
        }, current_time=t3_c)
        self.assertEqual(slot.active_offer_refill_strikes.get(242.0), 2)

        # Price retreats again to 240 with HAKI after Strike 2
        t3_d = self.t0 + timedelta(seconds=38.0)
        self.manager.process_trade({"symbol": "MDIA", "price": 240.0, "sideCode": 2, "exchange_time": t3_d})

        # Tranche 1 must now be FILLED at 240!
        self.assertEqual(slot.tranche1_status, "FILLED")
        self.assertEqual(slot.tranche1_exit_price, 240.0)
        self.assertAlmostEqual(slot.tranche1_pnl_pct, 1.69, places=2)
        self.assertGreater(slot.tranche1_net_idr, 0)
        # BUT slot must remain ENTERED for Tranche 2!
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertEqual(slot.tranche2_status, "PENDING")

        # 2. Price dips to 234, but 234 has massive bid absorption
        t4 = self.t0 + timedelta(seconds=60.0)
        self.manager.process_book({
            "symbol": "MDIA", "side": "BID",
            "levels": [
                {"price": 234.0, "lot": 50_000.0, "shares": 5_000_000, "frequency": 80},
                {"price": 236.0, "lot": 10_000.0, "shares": 1_000_000, "frequency": 20},
            ],
        }, current_time=t4)
        t5 = self.t0 + timedelta(seconds=70.0)
        self.manager.process_book({
            "symbol": "MDIA", "side": "BID",
            "levels": [
                {"price": 234.0, "lot": 92_000.0, "shares": 9_200_000, "frequency": 140},
            ],
        }, current_time=t5)
        # Price trades at 234
        self.manager.process_trade({"symbol": "MDIA", "price": 234.0, "sideCode": 2, "exchange_time": t5})
        # Runner MUST NOT cut loss!
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertEqual(slot.tranche2_status, "PENDING")

        # 3. Session ends with market rally at 246
        t_end = self.t0 + timedelta(seconds=800.0)
        self.manager.process_book({
            "symbol": "MDIA", "side": "BID",
            "levels": [{"price": 246.0, "lot": 20_000.0, "shares": 2_000_000, "frequency": 50}],
        }, current_time=t_end)
        self.manager.process_trade({"symbol": "MDIA", "price": 246.0, "sideCode": 1, "exchange_time": t_end})
        self.manager.close_all(t_end)

        # Slot must now be finalized with TAKE_PROFIT
        self.assertEqual(slot.state, SniperState.EXIT_TP)
        self.assertEqual(len(self.manager.history), 1)
        hist = self.manager.history[0]
        self.assertTrue(hist["is_hybrid"])
        self.assertEqual(hist["tranche1_lots"], 12)
        self.assertEqual(hist["tranche1_exit_price"], 240.0)
        self.assertEqual(hist["tranche2_lots"], 11)
        self.assertEqual(hist["tranche2_exit_price"], 246.0)
        self.assertGreater(hist["net_idr"], 10_000.0)  # Cuan solid > 10k IDR!

    def test_hybrid_stop_loss_before_tp(self):
        slot = self.manager.handle_radar_alert(self._make_alert("MDIA", 236.0))
        self.manager.process_trade({"symbol": "MDIA", "price": 236.0, "sideCode": 1, "exchange_time": self.t0})
        self.assertEqual(slot.state, SniperState.ENTERED)

        # Price dumps to 228 with no absorption
        t1 = self.t0 + timedelta(seconds=15.0)
        self.manager.process_trade({"symbol": "MDIA", "price": 228.0, "sideCode": 2, "exchange_time": t1})

        # Both tranches must exit at stop loss!
        self.assertEqual(slot.state, SniperState.EXIT_CL)
        self.assertEqual(len(self.manager.history), 1)
        hist = self.manager.history[0]
        self.assertEqual(hist["outcome"], "CUT_LOSS")


if __name__ == "__main__":
    unittest.main()
