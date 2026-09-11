import unittest
from datetime import datetime, timedelta, timezone
from stockbit_ws.radar import RadarAlert
from stockbit_ws.sniper import SniperConfig, SniperManager, SniperState


class TestContinuousFlowSniper(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 9, 8, 3, 30, 0, tzinfo=timezone.utc)  # 10:30 WIB (UTC+7)

    def _make_alert(self, symbol="RAJA", price=1000.0, pattern="BREAKOUT_MOMENTUM", ts=None):
        return RadarAlert(
            timestamp=ts or self.t0,
            symbol=symbol,
            pattern=pattern,
            velocity=30,
            haka_pct=85.0,
            net_flow_idr=500_000_000.0,
            price_open=price - 10.0,
            price_close=price,
            delta_points=10.0,
            delta_pct=1.0,
            details="Test alert",
        )

    def test_split_fill_rejected_continuous_flow_required(self):
        """A split-fill (only 3 trades in 1s) must NOT trigger entry when 15 trades & 4s are required."""
        cfg = SniperConfig(
            min_observation_seconds=4.0,
            min_observing_done_trades=15,
            min_follow_through_haka_lots=50.0,
        )
        manager = SniperManager(config=cfg)
        alert = self._make_alert("RMKE", price=500.0)
        slot = manager.handle_radar_alert(alert)
        self.assertIsNotNone(slot)
        self.assertEqual(slot.state, SniperState.OBSERVING)

        # 3 quick trades in 0.5s with price > ref_price
        for i in range(3):
            manager.process_trade({
                "symbol": "RMKE",
                "price": 505.0,
                "lot": 20.0,
                "sideCode": 1,
                "exchange_time": self.t0 + timedelta(seconds=0.1 * i),
            })
        # Not enough trades (< 15) and not enough duration (< 4s) -> remains OBSERVING
        self.assertEqual(slot.state, SniperState.OBSERVING)
        self.assertEqual(slot.observing_done_count, 3)

        # Time reaches 10s timeout without new trades -> ABORTED
        manager.tick(self.t0 + timedelta(seconds=10.1))
        self.assertEqual(slot.state, SniperState.ABORTED)

    def test_continuous_flow_sustained_entry(self):
        """Continuous done flow meeting min trades, min duration, and HAKA value triggers entry."""
        cfg = SniperConfig(
            min_observation_seconds=4.0,
            min_observing_done_trades=10,
            min_observing_haka_value_idr=20_000_000.0,  # Rp 20 juta
            min_follow_through_haka_lots=100.0,
        )
        manager = SniperManager(config=cfg)
        alert = self._make_alert("RAJA", price=1000.0)
        slot = manager.handle_radar_alert(alert)

        # Feed 12 continuous HAKA trades across 4.5 seconds
        for i in range(12):
            t_trade = self.t0 + timedelta(seconds=0.4 * (i + 1))
            manager.process_trade({
                "symbol": "RAJA",
                "price": 1010.0,
                "lot": 20.0,  # 20 lot * 100 * 1010 = Rp 2.02 juta per trade -> 12 trades = Rp 24.24 juta
                "sideCode": 1,
                "exchange_time": t_trade,
            })

        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertEqual(slot.entry_price, 1010.0)
        self.assertGreaterEqual(slot.observing_done_count, 10)
        self.assertGreaterEqual(slot.observing_haka_value_idr, 20_000_000.0)

    def test_tape_silence_detector_aborts_early(self):
        """If tape goes silent for > 2.5s during observation, slot is immediately aborted."""
        cfg = SniperConfig(
            min_observation_seconds=4.0,
            min_observing_done_trades=10,
            max_tape_silence_seconds=2.5,
        )
        manager = SniperManager(config=cfg)
        alert = self._make_alert("ENRG", price=300.0)
        slot = manager.handle_radar_alert(alert)

        # Trade 1 at t0 + 0.5s
        manager.process_trade({
            "symbol": "ENRG",
            "price": 302.0,
            "lot": 10.0,
            "sideCode": 1,
            "exchange_time": self.t0 + timedelta(seconds=0.5),
        })
        self.assertEqual(slot.state, SniperState.OBSERVING)

        # Trade 2 arrives at t0 + 3.5s (silence = 3.0s > 2.5s limit)
        manager.process_trade({
            "symbol": "ENRG",
            "price": 302.0,
            "lot": 10.0,
            "sideCode": 1,
            "exchange_time": self.t0 + timedelta(seconds=3.5),
        })
        self.assertEqual(slot.state, SniperState.ABORTED)
        self.assertIn("Tape hening", slot.reason)
        self.assertEqual(manager.history[-1]["outcome"], "ABORTED_TAPE_SILENCE")

    def test_stagnant_bep_cut_at_90_seconds(self):
        """Holding position mandek di BEP (pnl <= 0.8%) is cut at 90s instead of waiting 900s."""
        cfg = SniperConfig(
            stagnant_timeout_seconds=90.0,
            max_holding_seconds=900.0,
            enable_hybrid_mode=True,
        )
        manager = SniperManager(config=cfg)
        alert = self._make_alert("MDIA", price=200.0)
        slot = manager.handle_radar_alert(alert)

        # Enter at t0 + 1s
        t_entry = self.t0 + timedelta(seconds=1.0)
        manager.process_trade({
            "symbol": "MDIA",
            "price": 202.0,
            "lot": 120.0,
            "sideCode": 1,
            "exchange_time": t_entry,
        })
        self.assertEqual(slot.state, SniperState.ENTERED)

        # Price ticks at 202.0 (0.0% PnL) at t_entry + 89s -> Still ENTERED
        manager.process_trade({
            "symbol": "MDIA",
            "price": 202.0,
            "lot": 10.0,
            "sideCode": 1,
            "exchange_time": t_entry + timedelta(seconds=89.0),
        })
        manager.tick(t_entry + timedelta(seconds=89.0))
        self.assertEqual(slot.state, SniperState.ENTERED)

        # At t_entry + 91s, stagnant cut triggers
        manager.tick(t_entry + timedelta(seconds=91.0))
        self.assertEqual(slot.state, SniperState.EXIT_TIMEOUT)
        self.assertIn("Stagnant Cut 90s", slot.reason)

    def test_stagnant_cut_does_not_cut_active_runner(self):
        """Once Tranche 1 is FILLED (profit secured), Tranche 2 Runner is NOT cut by 90s stagnant cut."""
        cfg = SniperConfig(
            stagnant_timeout_seconds=90.0,
            hybrid_runner_max_hold_seconds=900.0,
            enable_hybrid_mode=True,
            target_tp_pct=2.0,
        )
        manager = SniperManager(config=cfg)
        alert = self._make_alert("RAJA", price=1000.0)
        slot = manager.handle_radar_alert(alert)

        # Enter at 1000
        t_entry = self.t0 + timedelta(seconds=1.0)
        manager.process_trade({
            "symbol": "RAJA",
            "price": 1005.0,
            "lot": 120.0,
            "sideCode": 1,
            "exchange_time": t_entry,
        })
        self.assertEqual(slot.state, SniperState.ENTERED)

        # Tranche 1 hits TP (+2.5%) at t_entry + 20s
        manager.process_trade({
            "symbol": "RAJA",
            "price": 1030.0,
            "lot": 20.0,
            "sideCode": 1,
            "exchange_time": t_entry + timedelta(seconds=20.0),
        })
        self.assertEqual(slot.tranche1_status, "FILLED")

        # Advance to 100s (> 90s). Price is at 1020 (above trailing stop 1015).
        manager.process_trade({
            "symbol": "RAJA",
            "price": 1020.0,
            "lot": 10.0,
            "sideCode": 1,
            "exchange_time": t_entry + timedelta(seconds=100.0),
        })
        manager.tick(t_entry + timedelta(seconds=100.0))
        # Runner must NOT be cut by stagnant cut because T1 was already filled!
        self.assertEqual(slot.state, SniperState.ENTERED)

    def test_l2_pre_entry_guard(self):
        """L2 pre-entry guard prevents entry when bid fortification < 1.2x or bid < 1,500 lots."""
        cfg = SniperConfig(
            enable_l2_pre_entry_guard=True,
            l2_pre_entry_min_bid_ratio=1.2,
            l2_pre_entry_min_bid_lots=1500.0,
        )
        manager = SniperManager(config=cfg)
        alert = self._make_alert("COCO", price=400.0)
        slot = manager.handle_radar_alert(alert)

        # Case A: Thin / Weak Bid (Bid: 500 lot, Offer: 2,000 lot -> ratio 0.25x)
        manager.process_book({
            "symbol": "COCO",
            "bid_vol": 500.0,
            "offer_vol": 2000.0,
            "bids": {398.0: 500.0},
            "offers": {402.0: 2000.0},
        }, current_time=self.t0 + timedelta(seconds=0.5))
        manager.process_trade({
            "symbol": "COCO",
            "price": 402.0,
            "lot": 20.0,
            "sideCode": 1,
            "exchange_time": self.t0 + timedelta(seconds=1.0),
        })
        # Must NOT enter because L2 orderbook is weak
        self.assertEqual(slot.state, SniperState.OBSERVING)

        # Case B: Orderbook thickens (Bid: 3,000 lot, Offer: 1,500 lot -> ratio 2.0x >= 1.2x)
        manager.process_book({
            "symbol": "COCO",
            "bid_vol": 3000.0,
            "offer_vol": 1500.0,
            "bids": {400.0: 2000.0, 398.0: 1000.0},
            "offers": {404.0: 1500.0},
        }, current_time=self.t0 + timedelta(seconds=1.5))
        manager.process_trade({
            "symbol": "COCO",
            "price": 404.0,
            "lot": 120.0,
            "sideCode": 1,
            "exchange_time": self.t0 + timedelta(seconds=2.0),
        })
        # Now enters!
        self.assertEqual(slot.state, SniperState.ENTERED)

    def test_l2_pre_entry_guard_rejects_stale_book(self):
        cfg = SniperConfig(enable_l2_pre_entry_guard=True, l2_stale_seconds=2.0)
        manager = SniperManager(config=cfg)
        slot = manager.handle_radar_alert(self._make_alert("COCO", price=400.0))
        manager.process_book({
            "symbol": "COCO", "bid_vol": 3000.0, "offer_vol": 1000.0,
            "bids": {400.0: 3000.0}, "offers": {402.0: 1000.0},
        }, current_time=self.t0)
        manager.process_trade({
            "symbol": "COCO", "price": 402.0, "lot": 120.0, "sideCode": 1,
            "exchange_time": self.t0 + timedelta(seconds=3),
        }, current_time=self.t0 + timedelta(seconds=3))
        self.assertEqual(slot.state, SniperState.OBSERVING)

    def test_trading_hours_guard(self):
        """Radar alerts after 15:35 WIB or before 09:02 WIB must be rejected."""
        cfg = SniperConfig(enable_trading_hours_guard=True)
        manager = SniperManager(config=cfg)

        # 1. Alert at 15:40 WIB (08:40 UTC) -> Rejected
        t_late = datetime(2026, 9, 8, 8, 40, 0, tzinfo=timezone.utc)
        alert_late = self._make_alert("AUTO", price=2000.0, ts=t_late)
        slot_late = manager.handle_radar_alert(alert_late)
        self.assertIsNone(slot_late)

        # 2. Alert at 08:59 WIB (01:59 UTC) -> Rejected
        t_early = datetime(2026, 9, 8, 1, 59, 0, tzinfo=timezone.utc)
        alert_early = self._make_alert("AUTO", price=2000.0, ts=t_early)
        slot_early = manager.handle_radar_alert(alert_early)
        self.assertIsNone(slot_early)

        # 3. Alert at 10:15 WIB (03:15 UTC) -> Accepted
        t_active = datetime(2026, 9, 8, 3, 15, 0, tzinfo=timezone.utc)
        alert_active = self._make_alert("AUTO", price=2000.0, ts=t_active)
        slot_active = manager.handle_radar_alert(alert_active)
        self.assertIsNotNone(slot_active)
        self.assertEqual(slot_active.symbol, "AUTO")


    def test_non_hybrid_dynamic_trailing_and_bep_floor(self):
        """In non-hybrid mode, once peak >= entry + 2 ticks, SL moves to BEP+1 tick and trails peak-3 ticks."""
        cfg = SniperConfig(
            enable_hybrid_mode=False,
            hybrid_runner_trailing_ticks=3,
            hybrid_runner_be_buffer_ticks=1,
            target_tp_pct=10.0,  # Far target so dynamic trailing triggers first
        )
        manager = SniperManager(config=cfg)
        alert = self._make_alert("RAJA", price=1000.0)
        slot = manager.handle_radar_alert(alert)

        # Enter at 1005 (> ref_price 1000)
        t_entry = self.t0 + timedelta(seconds=1.0)
        manager.process_trade({
            "symbol": "RAJA",
            "price": 1005.0,
            "lot": 120.0,
            "sideCode": 1,
            "exchange_time": t_entry,
        })
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertEqual(slot.entry_price, 1005.0)

        # Price ticks up to 1015 (+2 ticks for price 1005 where tick is 5)
        manager.process_trade({
            "symbol": "RAJA",
            "price": 1015.0,
            "lot": 20.0,
            "sideCode": 1,
            "exchange_time": t_entry + timedelta(seconds=5.0),
        })
        # Stop loss must be raised to at least BEP + 1 tick (1005 + 5 = 1010)
        self.assertGreaterEqual(slot.stop_loss_price, 1010.0)

        # Price advances further to 1030 (+5 ticks)
        manager.process_trade({
            "symbol": "RAJA",
            "price": 1030.0,
            "lot": 20.0,
            "sideCode": 1,
            "exchange_time": t_entry + timedelta(seconds=10.0),
        })
        # Peak is 1030. Tick at 1030 is 5.
        # Trailing 3 ticks: 1030 - (3 * 5) = 1015
        self.assertEqual(slot.stop_loss_price, 1015.0)
        self.assertEqual(slot.peak_price, 1030.0)

        # Price retreats to 1015
        manager.process_trade({
            "symbol": "RAJA",
            "price": 1015.0,
            "lot": 20.0,
            "sideCode": 2,
            "exchange_time": t_entry + timedelta(seconds=15.0),
        })
        # Trailing stop hit in profit! Must exit as EXIT_TP and record TAKE_PROFIT
        self.assertEqual(slot.state, SniperState.EXIT_TP)
        self.assertGreater(slot.pnl_pct, 0)
        self.assertEqual(manager.history[-1]["outcome"], "TAKE_PROFIT")
        self.assertEqual(manager.cooldowns["RAJA"], t_entry + timedelta(seconds=15.0 + cfg.cooldown_seconds))

    def test_non_hybrid_bid_wall_trailing(self):
        """In non-hybrid mode, large bid walls (>= 20k lots) raise trailing stop to wall price - 1 tick."""
        cfg = SniperConfig(
            enable_hybrid_mode=False,
            target_tp_pct=10.0,
        )
        manager = SniperManager(config=cfg)
        alert = self._make_alert("MDIA", price=200.0)
        slot = manager.handle_radar_alert(alert)

        # Enter at 202 (> ref_price 200)
        t_entry = self.t0 + timedelta(seconds=1.0)
        manager.process_trade({
            "symbol": "MDIA",
            "price": 202.0,
            "lot": 120.0,
            "sideCode": 1,
            "exchange_time": t_entry,
        })
        self.assertEqual(slot.state, SniperState.ENTERED)

        # Feed Order Book with huge bid wall at 208 (25,000 lot)
        manager.process_book({
            "symbol": "MDIA",
            "bid_vol": 30000.0,
            "offer_vol": 5000.0,
            "bids": {208.0: 25000.0, 204.0: 5000.0},
            "offers": {212.0: 5000.0},
        }, current_time=t_entry + timedelta(seconds=4.0))

        # Trade at 210 (+4 ticks, peak = 210)
        manager.process_trade({
            "symbol": "MDIA",
            "price": 210.0,
            "lot": 20.0,
            "sideCode": 1,
            "exchange_time": t_entry + timedelta(seconds=5.0),
        })
        # Peak 210 - 3 ticks (3*2=6) = 204.
        # But Benteng Bid at 208 raises stop loss to 208 - 2 = 206!
        self.assertEqual(slot.stop_loss_price, 206.0)

    def test_non_hybrid_dynamic_tp_iceberg_offer_refill(self):
        """In non-hybrid mode, massive iceberg refill on offer wall triggers Dynamic TP for 100% position."""
        cfg = SniperConfig(
            enable_hybrid_mode=False,
            dynamic_tp_refill_lots=10_000.0,
            target_tp_pct=10.0,
        )
        manager = SniperManager(config=cfg)
        alert = self._make_alert("COCO", price=500.0)
        slot = manager.handle_radar_alert(alert)

        # Enter at 505 (> ref_price 500)
        t_entry = self.t0 + timedelta(seconds=1.0)
        manager.process_trade({
            "symbol": "COCO",
            "price": 505.0,
            "lot": 120.0,
            "sideCode": 1,
            "exchange_time": t_entry,
        })
        self.assertEqual(slot.state, SniperState.ENTERED)

        # Price rises to 520 (peak 520)
        manager.process_trade({
            "symbol": "COCO",
            "price": 520.0,
            "lot": 50.0,
            "sideCode": 1,
            "exchange_time": t_entry + timedelta(seconds=5.0),
        })

        # Order book has best bid at 515, and initial offer at 525 (20,000 lot)
        manager.process_book({
            "symbol": "COCO",
            "side": "OFFER",
            "levels": [{"price": 525.0, "lot": 20000.0}],
        }, current_time=t_entry + timedelta(seconds=5.0))
        manager.process_book({
            "symbol": "COCO",
            "side": "BID",
            "levels": [{"price": 515.0, "lot": 5000.0}],
        }, current_time=t_entry + timedelta(seconds=5.0))

        # Refill #1 at 525 (+8,000 lot -> 28,000 lot)
        manager.process_book({
            "symbol": "COCO",
            "side": "OFFER",
            "levels": [{"price": 525.0, "lot": 28000.0}],
        }, current_time=t_entry + timedelta(seconds=5.5))

        # Price retreats on HAKI (sideCode=2) after Strike 1:
        # Must NOT exit yet because dynamic_tp_min_refill_strikes = 2 (Chance 1 given to buyer!)
        manager.process_trade({
            "symbol": "COCO",
            "price": 515.0,
            "lot": 10.0,
            "sideCode": 2,
            "exchange_time": t_entry + timedelta(seconds=6.0),
        })
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertEqual(slot.active_offer_refill_strikes.get(525.0), 1)

        # Buyer eats 525 offer down to 2,000 lot
        manager.process_book({
            "symbol": "COCO",
            "side": "OFFER",
            "levels": [{"price": 525.0, "lot": 2000.0}],
        }, current_time=t_entry + timedelta(seconds=6.2))

        # Seller refills again at 525 (+12,000 lot -> 14,000 lot, Strike 2!)
        manager.process_book({
            "symbol": "COCO",
            "side": "OFFER",
            "levels": [{"price": 525.0, "lot": 14000.0}],
        }, current_time=t_entry + timedelta(seconds=6.5))
        self.assertEqual(slot.active_offer_refill_strikes.get(525.0), 2)
        self.assertGreaterEqual(slot.active_offer_refills[525.0], 10000.0)

        # Price retreats again on HAKI after Strike 2
        manager.process_trade({
            "symbol": "COCO",
            "price": 515.0,
            "lot": 10.0,
            "sideCode": 2,
            "exchange_time": t_entry + timedelta(seconds=7.0),
        })

        # Should trigger Dynamic TP for 100% position after 2 strikes!
        self.assertEqual(slot.state, SniperState.EXIT_TP)
        self.assertIn("Dynamic TP", slot.reason)
        self.assertEqual(manager.history[-1]["outcome"], "TAKE_PROFIT")

    def test_non_hybrid_support_absorption_defense(self):
        """When price hits support/SL, if bid support >= 25k lots, do NOT panic sell; hold for absorption."""
        cfg = SniperConfig(
            enable_hybrid_mode=False,
            stop_loss_pct=2.0,
        )
        manager = SniperManager(config=cfg)
        alert = self._make_alert("COCO", price=100.0)
        slot = manager.handle_radar_alert(alert)

        # Enter at 102 (> ref_price 100) -> the nearest risk limit is 100.
        t_entry = self.t0 + timedelta(seconds=1.0)
        manager.process_trade({
            "symbol": "COCO",
            "price": 102.0,
            "lot": 120.0,
            "sideCode": 1,
            "exchange_time": t_entry,
        })
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertEqual(slot.stop_loss_price, 100.0)

        # Order book has massive bid support at 100.0 (30,000 lots)
        manager.process_book({
            "symbol": "COCO",
            "bid_vol": 40000.0,
            "offer_vol": 10000.0,
            "bids": {100.0: 30000.0},
            "offers": {103.0: 5000.0},
        }, current_time=t_entry + timedelta(seconds=4.0))

        # Price touches 100.0 (<= effective_stop_p)
        manager.process_trade({
            "symbol": "COCO",
            "price": 100.0,
            "lot": 50.0,
            "sideCode": 2,
            "exchange_time": t_entry + timedelta(seconds=5.0),
        })

        # Must NOT cut loss! Holds position because bid is absorbed
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertIn("Support diabsorpsi", slot.reason)

    def test_dashboard_sidecar_book_recording_in_wildcard_session(self):
        """Sidecar L2 Order Book events are forwarded to recorder in wildcard session."""
        from io import StringIO
        from stockbit_ws import cli
        from stockbit_ws.logger import SafeLogger
        from stockbit_ws.quality import Clock

        class MockRecorder:
            def __init__(self):
                self.records = []

            def append(self, kind, payload, received_at, elapsed):
                self.records.append((kind, payload, received_at, elapsed))

        mock_recorder = MockRecorder()
        output = StringIO()
        dashboard = cli.Dashboard("*", SafeLogger(output=StringIO()), output=output, clock=Clock(), recorder=mock_recorder)

        # Dispatch sidecar book event for MDIA
        book_payload = {
            "type": "#O",
            "symbol": "MDIA",
            "side": "BID",
            "levels": [
                {"price": 100.0, "shares": 5000, "frequency": 10},
            ],
        }
        dashboard.on_sidecar_book(book_payload)

        # Verify recorder received the book event
        self.assertEqual(len(mock_recorder.records), 1)
        kind, payload, received_at, elapsed = mock_recorder.records[0]
        self.assertEqual(kind, "book")
        self.assertEqual(payload["symbol"], "MDIA")
        self.assertEqual(payload["side"], "BID")
        self.assertEqual(dashboard.book_updates, 1)
    def test_two_strike_iceberg_offer_refill_exact_flow(self):
        """User scenario: 250 has 100k offer, HAKA leaves 100, refilled +50k (Strike 1: tolerated).
        Buyer HAKAs 45k leaving 5k, then refilled +30k (Strike 2). Then on retreat, Dynamic TP triggers at Best Bid.
        """
        cfg = SniperConfig(
            enable_hybrid_mode=False,
            dynamic_tp_refill_lots=20_000.0,
            dynamic_tp_min_refill_strikes=2,
            target_tp_pct=15.0,
        )
        manager = SniperManager(config=cfg)
        alert = self._make_alert("RAJA", price=238.0)
        slot = manager.handle_radar_alert(alert)

        # 1. Enter at 240
        t_entry = self.t0 + timedelta(seconds=1.0)
        manager.process_trade({
            "symbol": "RAJA",
            "price": 240.0,
            "lot": 100.0,
            "sideCode": 1,
            "exchange_time": t_entry,
        })
        self.assertEqual(slot.state, SniperState.ENTERED)

        # 2. Price rallies to 250 (peak 250)
        t_peak = t_entry + timedelta(seconds=5.0)
        manager.process_trade({
            "symbol": "RAJA",
            "price": 250.0,
            "lot": 50.0,
            "sideCode": 1,
            "exchange_time": t_peak,
        })
        self.assertEqual(slot.peak_price, 250.0)

        # 3. Initial offer book at 250: 100,000 lot; Best bid at 248: 15,000 lot
        manager.process_book({
            "symbol": "RAJA",
            "side": "OFFER",
            "levels": [{"price": 250.0, "lot": 100_000.0}],
        }, current_time=t_peak)
        manager.process_book({
            "symbol": "RAJA",
            "side": "BID",
            "levels": [{"price": 248.0, "lot": 15_000.0}],
        }, current_time=t_peak)

        # 4. Market HAKAs aggressively: 250 offer drops to 100 lot
        manager.process_book({
            "symbol": "RAJA",
            "side": "OFFER",
            "levels": [{"price": 250.0, "lot": 100.0}],
        }, current_time=t_peak + timedelta(seconds=0.5))
        self.assertTrue(slot.offer_was_consumed.get(250.0))

        # 5. Refill Wave #1: Seller adds 50,000 lot -> 50,100 lot (Strike 1)
        manager.process_book({
            "symbol": "RAJA",
            "side": "OFFER",
            "levels": [{"price": 250.0, "lot": 50_100.0}],
        }, current_time=t_peak + timedelta(seconds=1.0))
        self.assertEqual(slot.active_offer_refill_strikes.get(250.0), 1)
        self.assertEqual(slot.active_offer_refills.get(250.0), 50_000.0)

        # 6. Price retreats slightly to 248 on HAKI:
        # System gives buyer Chance 1 -> MUST NOT EXIT!
        manager.process_trade({
            "symbol": "RAJA",
            "price": 248.0,
            "lot": 10.0,
            "sideCode": 2,
            "exchange_time": t_peak + timedelta(seconds=2.0),
        })
        self.assertEqual(slot.state, SniperState.ENTERED)

        # 7. Buyer HAKAs again! Eats 45,000 lot -> leaves 5,100 lot
        manager.process_book({
            "symbol": "RAJA",
            "side": "OFFER",
            "levels": [{"price": 250.0, "lot": 5_100.0}],
        }, current_time=t_peak + timedelta(seconds=3.0))
        self.assertTrue(slot.offer_was_consumed.get(250.0))

        # 8. Refill Wave #2: Seller adds another 30,000 lot -> 35,100 lot (Strike 2!)
        manager.process_book({
            "symbol": "RAJA",
            "side": "OFFER",
            "levels": [{"price": 250.0, "lot": 35_100.0}],
        }, current_time=t_peak + timedelta(seconds=4.0))
        self.assertEqual(slot.active_offer_refill_strikes.get(250.0), 2)
        self.assertEqual(slot.active_offer_refills.get(250.0), 80_000.0)

        # 9. Price retreats again to 248 on HAKI after Strike 2:
        # NOW 2-strike confirmation is complete -> MUST TRIGGER DYNAMIC TP @ 248!
        manager.process_trade({
            "symbol": "RAJA",
            "price": 248.0,
            "lot": 10.0,
            "sideCode": 2,
            "exchange_time": t_peak + timedelta(seconds=5.0),
        })
        self.assertEqual(slot.state, SniperState.EXIT_TP)
        self.assertEqual(slot.current_price, 248.0)
        self.assertIn("Dynamic TP", slot.reason)
        self.assertIn("2x refill", slot.reason)
        self.assertEqual(manager.history[-1]["outcome"], "TAKE_PROFIT")


if __name__ == "__main__":
    unittest.main()
