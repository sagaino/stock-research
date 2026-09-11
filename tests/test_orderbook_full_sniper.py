from datetime import datetime, timedelta, timezone
import unittest

from stockbit_ws import cli
from stockbit_ws.radar import RadarAlert
from stockbit_ws.sniper import SniperConfig, SniperManager, SniperState, format_sniper_report


class FullOrderBookSniperTests(unittest.TestCase):
    def setUp(self):
        self.t0 = datetime(2026, 9, 9, 3, 30, tzinfo=timezone.utc)
        self.config = SniperConfig(orderbook_exit_mode="full", min_stock_price=0.0)

    def _alert(self, symbol="TEST", price=206.0, seconds=0.0):
        return RadarAlert(
            timestamp=self.t0 + timedelta(seconds=seconds), symbol=symbol,
            pattern="BREAKOUT_MOMENTUM", velocity=10, haka_pct=90.0,
            net_flow_idr=100_000_000.0, price_open=price - 2,
            price_close=price, delta_points=2.0, delta_pct=1.0, details="test",
        )

    def _seed_watch(self, manager):
        slot = manager.handle_radar_alert(self._alert())
        manager.process_book({"symbol": "TEST", "side": "OFFER", "levels": [{"price": 208.0, "lot": 5_000.0}]}, self.t0)
        manager.process_book({"symbol": "TEST", "side": "BID", "levels": [{"price": 204.0, "lot": 20_000.0}, {"price": 202.0, "lot": 5_000.0}]}, self.t0)
        return slot

    def _absorb_twice(self, manager):
        for seconds, lot in ((1, 4_000.0), (2, 20_000.0), (3, 4_000.0), (4, 20_000.0)):
            manager.process_book({"symbol": "TEST", "side": "BID", "levels": [{"price": 204.0, "lot": lot}, {"price": 202.0, "lot": 5_000.0}]}, self.t0 + timedelta(seconds=seconds))

    def _entry(self, manager):
        slot = self._seed_watch(manager)
        self._absorb_twice(manager)
        manager.process_trade({"symbol": "TEST", "price": 206.0, "lot": 10.0, "sideCode": 1, "exchange_time": self.t0 + timedelta(seconds=4.5)})
        manager.process_trade({"symbol": "TEST", "price": 206.0, "lot": 10.0, "sideCode": 1, "exchange_time": self.t0 + timedelta(seconds=5)})
        return slot

    def test_radar_creates_watchlist_and_reinforcement_keeps_one_subscription(self):
        assigned = []
        manager = SniperManager(self.config, on_slot_assigned=assigned.append)
        slot = manager.handle_radar_alert(self._alert())
        manager.handle_radar_alert(self._alert(seconds=1))
        self.assertEqual(slot.state, SniperState.WATCHING)
        self.assertEqual(assigned, ["TEST"])
        self.assertIsNone(slot.last_trade_time)
        manager.tick(self.t0 + timedelta(seconds=299))
        self.assertEqual(slot.ttl_seconds, 1.0)

    def test_quietest_watchlist_is_replaced_when_full(self):
        assigned, released = [], []
        cfg = SniperConfig(orderbook_exit_mode="full", max_slots=5, min_stock_price=0.0)
        manager = SniperManager(cfg, on_slot_assigned=assigned.append, on_slot_released=released.append)
        for index, symbol in enumerate(("AAAA", "BBBB", "CCCC", "DDDD", "EEEE")):
            manager.handle_radar_alert(self._alert(symbol, seconds=index))
        replacement = manager.handle_radar_alert(self._alert("FFFF", seconds=10))
        self.assertEqual(released, ["AAAA"])
        self.assertEqual(assigned, ["AAAA", "BBBB", "CCCC", "DDDD", "EEEE", "FFFF"])
        self.assertEqual(replacement.state, SniperState.WATCHING)
        self.assertEqual(replacement.symbol, "FFFF")

    def test_watchlist_expires_after_five_quiet_minutes(self):
        released = []
        manager = SniperManager(self.config, on_slot_released=released.append)
        slot = self._seed_watch(manager)
        manager.tick(self.t0 + timedelta(seconds=301))
        self.assertEqual(slot.state, SniperState.IDLE)
        self.assertEqual(released, ["TEST"])
        self.assertEqual(manager.history[-1]["outcome"], "WATCHLIST_IDLE")

    def test_stale_l2_is_visible_and_blocks_watchlist_entry(self):
        manager = SniperManager(self.config)
        slot = self._seed_watch(manager)
        manager.tick(self.t0 + timedelta(seconds=16))
        self.assertEqual(slot.state, SniperState.WATCHING)
        self.assertIn("STALE", slot.reason)

    def test_two_absorption_refills_then_two_haka_enters_at_support(self):
        manager = SniperManager(self.config)
        slot = self._entry(manager)
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertEqual(slot.entry_price, 206.0)
        self.assertEqual(slot.active_support_price, 204.0)
        self.assertEqual(slot.stop_loss_price, 202.0)
        self.assertEqual(slot.target_price, 0.0)

    def test_one_refill_or_invalid_haka_does_not_enter(self):
        manager = SniperManager(self.config)
        slot = self._seed_watch(manager)
        for seconds, lot in ((1, 4_000.0), (2, 20_000.0)):
            manager.process_book({"symbol": "TEST", "side": "BID", "levels": [{"price": 204.0, "lot": lot}, {"price": 202.0, "lot": 5_000.0}]}, self.t0 + timedelta(seconds=seconds))
        manager.process_trade({"symbol": "TEST", "price": 206.0, "lot": 10.0, "sideCode": 1, "exchange_time": self.t0 + timedelta(seconds=3)})
        self.assertEqual(slot.state, SniperState.WATCHING)

        self._absorb_twice(manager)
        manager.process_trade({"symbol": "TEST", "price": 208.0, "lot": 10.0, "sideCode": 1, "exchange_time": self.t0 + timedelta(seconds=5)})
        manager.process_trade({"symbol": "TEST", "price": 206.0, "lot": 10.0, "sideCode": 1, "exchange_time": self.t0 + timedelta(seconds=6)})
        manager.process_trade({"symbol": "TEST", "price": 206.0, "lot": 10.0, "sideCode": 2, "exchange_time": self.t0 + timedelta(seconds=6.5)})
        manager.process_trade({"symbol": "TEST", "price": 206.0, "lot": 10.0, "sideCode": 1, "exchange_time": self.t0 + timedelta(seconds=7)})
        self.assertEqual(slot.state, SniperState.WATCHING)

    def test_haka_more_than_five_seconds_apart_does_not_enter(self):
        manager = SniperManager(self.config)
        slot = self._seed_watch(manager)
        self._absorb_twice(manager)
        manager.process_trade({"symbol": "TEST", "price": 206.0, "lot": 10.0, "sideCode": 1, "exchange_time": self.t0 + timedelta(seconds=5)})
        manager.process_trade({"symbol": "TEST", "price": 206.0, "lot": 10.0, "sideCode": 1, "exchange_time": self.t0 + timedelta(seconds=11)})
        self.assertEqual(slot.state, SniperState.WATCHING)
        self.assertEqual(slot.haka_streak, 1)

    def test_haki_through_support_releases_watchlist(self):
        released = []
        manager = SniperManager(self.config, on_slot_released=released.append)
        slot = self._seed_watch(manager)
        manager.process_trade({"symbol": "TEST", "price": 202.0, "lot": 10.0, "sideCode": 2, "exchange_time": self.t0 + timedelta(seconds=1)})
        self.assertEqual(slot.state, SniperState.IDLE)
        self.assertEqual(released, ["TEST"])
        self.assertEqual(manager.history[-1]["outcome"], "WATCHLIST_SUPPORT_BROKEN")

    def test_depleted_support_that_disappears_releases_watchlist(self):
        released = []
        manager = SniperManager(self.config, on_slot_released=released.append)
        slot = self._seed_watch(manager)
        manager.process_book({"symbol": "TEST", "side": "BID", "levels": [{"price": 202.0, "lot": 5_000.0}]}, self.t0 + timedelta(seconds=1))
        self.assertEqual(slot.state, SniperState.IDLE)
        self.assertEqual(released, ["TEST"])
        self.assertEqual(manager.history[-1]["outcome"], "WATCHLIST_SUPPORT_BROKEN")

    def test_support_two_failed_refills_triggers_cut_loss(self):
        manager = SniperManager(self.config)
        slot = self._entry(manager)
        for seconds, lot in ((6, 2_000.0), (7, 3_500.0), (8, 2_000.0), (9, 3_500.0)):
            manager.process_book({"symbol": "TEST", "side": "BID", "levels": [{"price": 204.0, "lot": lot}, {"price": 202.0, "lot": 5_000.0}]}, self.t0 + timedelta(seconds=seconds))
        manager.process_trade({"symbol": "TEST", "price": 204.0, "lot": 10.0, "sideCode": 2, "exchange_time": self.t0 + timedelta(seconds=10)})
        self.assertEqual(slot.state, SniperState.EXIT_CL)
        self.assertEqual(slot.exit_signal_price, 202.0)
        self.assertEqual(manager.history[-1]["exit_reason_code"], "SUPPORT_BREAK")

    def test_resistance_refill_twice_triggers_take_profit(self):
        manager = SniperManager(self.config)
        slot = self._entry(manager)
        manager.process_book({"symbol": "TEST", "side": "OFFER", "levels": [{"price": 220.0, "lot": 50_000.0}]}, self.t0 + timedelta(seconds=6))
        manager.process_trade({"symbol": "TEST", "price": 220.0, "lot": 10.0, "sideCode": 1, "exchange_time": self.t0 + timedelta(seconds=7)})
        for seconds, lot in ((8, 5_000.0), (9, 8_000.0), (10, 5_000.0), (11, 8_000.0)):
            manager.process_book({"symbol": "TEST", "side": "OFFER", "levels": [{"price": 220.0, "lot": lot}]}, self.t0 + timedelta(seconds=seconds))
        manager.process_trade({"symbol": "TEST", "price": 218.0, "lot": 10.0, "sideCode": 2, "exchange_time": self.t0 + timedelta(seconds=12)})
        self.assertEqual(slot.state, SniperState.EXIT_TP)
        self.assertEqual(slot.exit_signal_price, 218.0)
        self.assertEqual(manager.history[-1]["exit_reason_code"], "RESISTANCE_REFILL")

    def test_stale_book_triggers_emergency_exit_on_tick(self):
        manager = SniperManager(self.config)
        slot = self._entry(manager)
        manager.tick(self.t0 + timedelta(seconds=30))
        self.assertEqual(slot.state, SniperState.EXIT_CL)
        self.assertEqual(manager.history[-1]["exit_reason_code"], "EMERGENCY_L2_STALE")

    def test_cli_builder_carries_full_orderbook_parameters(self):
        args = cli.build_parser().parse_args([
            "--sniper", "--orderbook-exit-mode", "full",
            "--orderbook-wall-min-lots", "12000",
            "--orderbook-psych-wall-min-lots", "80000",
            "--orderbook-wall-ratio", "2.5",
            "--orderbook-depletion-ratio", "0.25",
            "--orderbook-refill-min-lots", "1500",
            "--orderbook-support-levels", "2",
        ])
        config = cli.build_sniper_config(args)
        self.assertEqual(config.orderbook_exit_mode, "full")
        self.assertEqual(config.orderbook_wall_min_lots, 12_000.0)
        self.assertEqual(config.orderbook_psychological_wall_min_lots, 80_000.0)
        self.assertEqual(config.orderbook_wall_ratio, 2.5)
        self.assertEqual(config.orderbook_depletion_ratio, 0.25)
        self.assertEqual(config.orderbook_refill_min_lots, 1_500.0)

    def test_full_report_includes_released_watchlist_candidate(self):
        report = format_sniper_report({
            "session_id": "test", "session_symbol": "*", "started_at": self.t0, "ended_at": self.t0,
            "sniper_config": self.config,
            "history": [{
                "symbol": "TEST", "pattern": "BREAKOUT_MOMENTUM", "outcome": "WATCHLIST_IDLE",
                "alert_time": self.t0, "entry_time": None, "entry_price": 0.0, "lots": 0,
                "ref_price": 206.0, "holding_seconds": 300.0, "reason": "Sepi 5 menit tanpa DONE",
            }],
        })
        self.assertIn("Dilepas dari Watchlist Pra-Entry", report)
        self.assertIn("Sepi 5 menit tanpa DONE", report)

    def test_same_event_sequence_has_identical_watchlist_entry_decision(self):
        def run_sequence():
            manager = SniperManager(self.config)
            slot = self._entry(manager)
            return slot.state, slot.entry_price, slot.active_support_price, slot.stop_loss_price

        self.assertEqual(run_sequence(), run_sequence())


if __name__ == "__main__":
    unittest.main()
