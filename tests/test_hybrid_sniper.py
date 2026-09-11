import unittest
from datetime import datetime, timedelta, timezone
from stockbit_ws.radar import RadarAlert
from stockbit_ws.sniper import (
    SniperConfig,
    SniperManager,
    SniperState,
    apply_paper_friction,
    get_idx_tick_size,
    round_to_idx_tick,
)

_WIB = timezone(timedelta(hours=7))


class TestHybridSniper(unittest.TestCase):
    def test_paper_friction_applies_adverse_ticks_and_fees(self):
        config = SniperConfig(paper_slippage_ticks=1, fee_buy_pct=0.15, fee_sell_pct=0.25)
        result = apply_paper_friction({
            "entry_price": 100.0,
            "exit_price": 110.0,
            "lots": 10,
            "pnl_pct": 10.0,
        }, config)
        self.assertEqual(result["entry_price"], 101.0)
        self.assertEqual(result["exit_price"], 109.0)
        self.assertLess(result["net_idr"], 8_000.0)
        self.assertAlmostEqual(result["pnl_pct"], result["net_idr"] / result["val_in"] * 100, places=2)
        self.assertEqual(result["paper_fill_model"], "adverse_idx_ticks_plus_fees")

    def test_paper_slippage_changes_strategy_target_and_break_even_trail(self):
        config = SniperConfig(
            paper_slippage_ticks=1,
            min_follow_through_haka_lots=0,
            min_haka_streak=1,
            min_stock_price=0,
            target_tp_pct=3,
        )
        manager = SniperManager(config=config)
        t0 = datetime(2026, 9, 8, 9, 0, 0, tzinfo=_WIB)
        manager.handle_radar_alert(RadarAlert(
            timestamp=t0, symbol="EKAD", pattern="BREAKOUT_MOMENTUM", velocity=60,
            haka_pct=90, net_flow_idr=800_000_000, price_open=428, price_close=430,
            delta_points=2, delta_pct=0.5, details="test",
        ))
        slot = manager.slots[0]
        manager.process_trade({"symbol": "EKAD", "price": 432, "sideCode": 1, "exchange_time": t0 + timedelta(seconds=1)})
        self.assertEqual(slot.target_price, 450)
        manager.process_trade({"symbol": "EKAD", "price": 436, "sideCode": 1, "exchange_time": t0 + timedelta(seconds=2)})
        self.assertLess(slot.stop_loss_price, 438)
        manager.process_trade({"symbol": "EKAD", "price": 438, "sideCode": 1, "exchange_time": t0 + timedelta(seconds=3)})
        self.assertGreaterEqual(slot.stop_loss_price, 438)

    def test_idx_tick_size(self):
        self.assertEqual(get_idx_tick_size(150), 1.0)
        self.assertEqual(get_idx_tick_size(216), 2.0)
        self.assertEqual(get_idx_tick_size(500), 5.0)
        self.assertEqual(get_idx_tick_size(2500), 10.0)
        self.assertEqual(get_idx_tick_size(6000), 25.0)

    def test_round_to_idx_tick(self):
        self.assertEqual(round_to_idx_tick(219.8), 220.0)
        self.assertEqual(round_to_idx_tick(216.0), 216.0)
        self.assertEqual(round_to_idx_tick(150.4), 150.0)

    def test_hybrid_bep_plus_buffer_ticks_covers_fees(self):
        """Verify that BEP + buffer ticks (e.g. 1 tick) covers broker fees so net PnL is strictly positive."""
        events = []
        config = SniperConfig(
            max_slots=1,
            enable_hybrid_mode=True,
            hybrid_scalp_ratio=0.5,
            hybrid_runner_trailing_ticks=3,
            hybrid_runner_be_buffer_ticks=1,  # 1 tick buffer
            trade_capital_idr=550_000.0,
            fee_buy_pct=0.15,
            fee_sell_pct=0.25,
            min_stock_price=50.0,
        )
        manager = SniperManager(config=config, on_event=lambda msg, s: events.append(msg))
        t0 = datetime(2026, 9, 8, 9, 0, 0, tzinfo=_WIB)

        alert = RadarAlert(
            timestamp=t0,
            symbol="PIPA",
            pattern="BREAKOUT_MOMENTUM",
            velocity=60,
            haka_pct=90.0,
            net_flow_idr=800_000_000.0,
            price_open=210.0,
            price_close=214.0,
            delta_points=4.0,
            delta_pct=1.9,
            details="Breakout",
        )
        manager.handle_radar_alert(alert)
        slot = manager.slots[0]

        # Entry @ 216
        manager.process_trade({
            "symbol": "PIPA",
            "price": 216.0,
            "lot": 100.0,
            "sideCode": 1,
            "exchange_time": t0 + timedelta(seconds=1),
        })

        # Hit TP1 @ 224 (first valid IDX tick at or above 3%).
        manager.process_trade({
            "symbol": "PIPA",
            "price": 224.0,
            "lot": 50.0,
            "sideCode": 1,
            "exchange_time": t0 + timedelta(seconds=10),
        })
        self.assertEqual(slot.tranche1_status, "FILLED")
        # For price 216 (fraction 200-500, tick = 2.0):
        # BEP + 1 tick buffer = 216 + 2 = 218!
        self.assertEqual(slot.runner_trailing_stop_price, 218.0)

        # Immediate pullback to 218
        manager.process_trade({
            "symbol": "PIPA",
            "price": 218.0,
            "lot": 50.0,
            "sideCode": 2,
            "exchange_time": t0 + timedelta(seconds=15),
        })
        # Runner exited at 218
        self.assertEqual(slot.state, SniperState.EXIT_TP)
        self.assertEqual(slot.tranche2_status, "STOPPED")
        self.assertEqual(slot.tranche2_exit_price, 218.0)
        # Verify that Tranche 2 is strictly profitable after fees:
        # Buy @ 216, Sell @ 218 (+0.925% gross - 0.40% fee = +0.525% net)
        self.assertGreater(slot.tranche2_net_idr, 0.0)
        self.assertGreater(slot.tranche1_net_idr, 0.0)

    def test_hybrid_breakeven_and_peak_trailing_lifecycle(self):
        events = []
        config = SniperConfig(
            max_slots=1,
            enable_hybrid_mode=True,
            hybrid_scalp_ratio=0.5,
            hybrid_runner_trailing_ticks=3,
            hybrid_runner_be_buffer_ticks=1,
            min_follow_through_haka_lots=50.0,
            trade_capital_idr=550_000.0,
            target_tp_pct=3.0,
            stop_loss_pct=1.5,
            stop_loss_ticks=2,
            min_stock_price=50.0,
        )
        manager = SniperManager(config=config, on_event=lambda msg, s: events.append(msg))
        t0 = datetime(2026, 9, 8, 9, 0, 0, tzinfo=_WIB)

        # 1. Alert for PIPA @ 214
        alert = RadarAlert(
            timestamp=t0,
            symbol="PIPA",
            pattern="BREAKOUT_MOMENTUM",
            velocity=60,
            haka_pct=90.0,
            net_flow_idr=800_000_000.0,
            price_open=210.0,
            price_close=214.0,
            delta_points=4.0,
            delta_pct=1.9,
            details="Breakout",
        )
        manager.handle_radar_alert(alert)
        slot = manager.slots[0]
        self.assertEqual(slot.state, SniperState.OBSERVING)

        # 2. HAKA trades confirming entry @ 216
        # PIPA lot price = 216 * 100 = 21,600. Capital 550,000 -> 25 lots
        # T1 = 50% = 12 lots, T2 = 13 lots
        t1 = t0 + timedelta(seconds=1)
        manager.process_trade({
            "symbol": "PIPA",
            "price": 216.0,
            "lot": 100.0,
            "sideCode": 1,
            "exchange_time": t1,
        })
        self.assertEqual(slot.state, SniperState.ENTERED)
        self.assertTrue(slot.is_hybrid)
        self.assertEqual(slot.tranche1_lots, 12)
        self.assertEqual(slot.tranche2_lots, 13)
        self.assertEqual(slot.entry_price, 216.0)
        # Initial stop loss: 216 - 2 ticks = 212 or 213
        self.assertTrue(slot.runner_trailing_stop_price <= 214.0)

        # 3. Price reaches TP1 target (216 * 1.03 = 222.48 -> valid tick 224)
        t2 = t0 + timedelta(seconds=10)
        manager.process_trade({
            "symbol": "PIPA",
            "price": 224.0,
            "lot": 50.0,
            "sideCode": 1,
            "exchange_time": t2,
        })
        self.assertEqual(slot.tranche1_status, "FILLED")
        self.assertEqual(slot.tranche1_exit_price, 224.0)
        self.assertGreater(slot.tranche1_net_idr, 0)
        # Breakeven + 1 tick buffer floor: 216 + 2 = 218.0!
        self.assertEqual(slot.runner_trailing_stop_price, 218.0)

        # 4. Price surges to 226 (+4.6%)
        # Peak trail: 226 - (3 * 2.0) = 220.0
        t3 = t0 + timedelta(seconds=20)
        manager.process_trade({
            "symbol": "PIPA",
            "price": 226.0,
            "lot": 80.0,
            "sideCode": 1,
            "exchange_time": t3,
        })
        self.assertEqual(slot.peak_price, 226.0)
        self.assertEqual(slot.runner_trailing_stop_price, 220.0)

        # 5. Price surges further to peak 228 (+5.55%)
        # Peak trail: 228 - (3 * 2.0) = 222.0
        t4 = t0 + timedelta(seconds=30)
        manager.process_trade({
            "symbol": "PIPA",
            "price": 228.0,
            "lot": 120.0,
            "sideCode": 1,
            "exchange_time": t4,
        })
        self.assertEqual(slot.peak_price, 228.0)
        self.assertEqual(slot.runner_trailing_stop_price, 222.0)

        # 6. Price retreats and hits trailing stop @ 222
        t5 = t0 + timedelta(seconds=40)
        manager.process_trade({
            "symbol": "PIPA",
            "price": 222.0,
            "lot": 50.0,
            "sideCode": 2,  # HAKI
            "exchange_time": t5,
        })
        # Slot should complete with TAKE_PROFIT on both tranches!
        self.assertEqual(slot.state, SniperState.EXIT_TP)
        self.assertEqual(slot.tranche2_status, "STOPPED")
        self.assertEqual(slot.tranche2_exit_price, 222.0)
        self.assertGreater(slot.tranche2_net_idr, 0)
        total_net = slot.tranche1_net_idr + slot.tranche2_net_idr
        self.assertGreater(total_net, 10_000.0)  # Substantial net profit locked in

    def test_slow_mover_and_capital_affordability_exclusion(self):
        config = SniperConfig(
            max_slots=1,
            enable_hybrid_mode=True,
            trade_capital_idr=550_000.0,
            exclude_big_caps=True,
            custom_excluded_symbols=["BRMS"],
        )
        manager = SniperManager(config=config)
        t0 = datetime(2026, 9, 8, 9, 0, 0, tzinfo=_WIB)

        def make_alert(sym: str, price: float):
            return RadarAlert(
                timestamp=t0,
                symbol=sym,
                pattern="BREAKOUT_MOMENTUM",
                velocity=60,
                haka_pct=90.0,
                net_flow_idr=800_000_000.0,
                price_open=price - 2,
                price_close=price,
                delta_points=2.0,
                delta_pct=1.0,
                details="Test",
            )

        # 1. ITMG must be rejected (in DEFAULT_BIG_CAPS & unaffordable for 550k)
        slot_itmg = manager.handle_radar_alert(make_alert("ITMG", 26_700.0))
        self.assertIsNone(slot_itmg)

        # 2. TAPG must be rejected (in DEFAULT_BIG_CAPS)
        slot_tapg = manager.handle_radar_alert(make_alert("TAPG", 2_320.0))
        self.assertIsNone(slot_tapg)

        # 3. Custom excluded symbol BRMS must be rejected
        slot_brms = manager.handle_radar_alert(make_alert("BRMS", 350.0))
        self.assertIsNone(slot_brms)

        # 4. max_stock_price filter rejects stocks above price limit
        config_max = SniperConfig(max_stock_price=1500.0, exclude_big_caps=False)
        mgr_max = SniperManager(config=config_max)
        self.assertIsNone(mgr_max.handle_radar_alert(make_alert("KARK", 2_000.0)))
        self.assertIsNotNone(mgr_max.handle_radar_alert(make_alert("KARK", 1_200.0)))

        # 5. An affordable, non-excluded stock (PIPA @ 216) MUST be accepted
        slot_pipa = manager.handle_radar_alert(make_alert("PIPA", 216.0))
        self.assertIsNotNone(slot_pipa)


if __name__ == "__main__":
    unittest.main()
