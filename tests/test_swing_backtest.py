import datetime
import unittest

from stockbit_ws.idx_calendar import first_idx_session_on_or_after, is_idx_session, last_idx_session_on_or_before, next_idx_sessions
from stockbit_ws.swing_backtest import rank_candidates, select_candidates, simulate_trade, validation_health, week_ends


class TestSwingBacktest(unittest.TestCase):
    def test_conservative_stop_wins_when_one_daily_bar_hits_both_levels(self):
        signal = datetime.date(2026, 7, 3)
        bars = {
            signal + datetime.timedelta(days=3): {"open": 100, "high": 108, "low": 95, "close": 102},
            signal + datetime.timedelta(days=4): {"open": 102, "high": 103, "low": 101, "close": 102},
            signal + datetime.timedelta(days=5): {"open": 102, "high": 103, "low": 101, "close": 102},
            signal + datetime.timedelta(days=6): {"open": 102, "high": 103, "low": 101, "close": 102},
            signal + datetime.timedelta(days=7): {"open": 102, "high": 103, "low": 101, "close": 102},
        }
        trade = simulate_trade(signal, bars, 100, fee_buy_pct=0.15, fee_sell_pct=0.25, slippage_ticks=1)
        self.assertEqual(trade["entry_date"], datetime.date(2026, 7, 6))
        self.assertEqual(trade["outcome"], "STOP_AMBIGUOUS")
        self.assertLess(trade["net_return_pct"], 0)

    def test_price_filter_rejects_extended_names_before_position_cap(self):
        signal = datetime.date(2026, 7, 3)
        picks = [
            {"symbol": "A", "top_buyer_avg": 100, "smart_net": 2},
            {"symbol": "B", "top_buyer_avg": 100, "smart_net": 3},
            {"symbol": "C", "top_buyer_avg": 100, "smart_net": 1},
        ]
        prices = {symbol: {signal: {"close": close}} for symbol, close in (("A", 106), ("B", 107), ("C", 104))}
        selected = select_candidates(picks, signal, prices, max_margin_pct=6, max_positions=2)
        self.assertEqual([pick["symbol"] for pick in selected], ["A", "C"])

    def test_only_keeps_weeks_with_a_following_week(self):
        self.assertEqual(week_ends(datetime.date(2026, 6, 29), datetime.date(2026, 7, 12)), [datetime.date(2026, 7, 3)])

    def test_idx_holiday_is_not_an_expected_session(self):
        self.assertFalse(is_idx_session(datetime.date(2026, 8, 17)))
        self.assertEqual(next_idx_sessions(datetime.date(2026, 8, 14), 5), [
            datetime.date(2026, 8, 18), datetime.date(2026, 8, 19),
            datetime.date(2026, 8, 20), datetime.date(2026, 8, 21),
            datetime.date(2026, 8, 24),
        ])
        self.assertEqual(last_idx_session_on_or_before(datetime.date(2026, 9, 13)), datetime.date(2026, 9, 11))
        self.assertEqual(first_idx_session_on_or_after(datetime.date(2026, 1, 1)), datetime.date(2026, 1, 2))

    def test_idx_2025_idul_fitri_and_august_joint_leave_are_not_sessions(self):
        self.assertFalse(is_idx_session(datetime.date(2025, 4, 4)))
        self.assertFalse(is_idx_session(datetime.date(2025, 8, 18)))
        self.assertEqual(next_idx_sessions(datetime.date(2025, 3, 27), 5), [
            datetime.date(2025, 4, 8), datetime.date(2025, 4, 9),
            datetime.date(2025, 4, 10), datetime.date(2025, 4, 11),
            datetime.date(2025, 4, 14),
        ])

    def test_candidate_audit_keeps_filter_reason(self):
        signal = datetime.date(2026, 7, 3)
        picks = [{"symbol": "A", "top_buyer_avg": 100, "smart_net": 1}]
        selected, audit = rank_candidates(picks, signal, {"A": {signal: {"close": 107}}}, max_margin_pct=6, max_positions=5)
        self.assertEqual(selected, [])
        self.assertEqual(audit[0]["reason"], "HARGA_DI_ATAS_BATAS_AVERAGE")

    def test_profit_factor_gate_uses_net_validation_returns_and_sample_size(self):
        passed, _, stats = validation_health([3.0, -1.0] * 15, min_profit_factor=1.2, min_trades=30)
        self.assertTrue(passed)
        self.assertEqual(stats["profit_factor"], 3.0)
        passed, reason, _ = validation_health([3.0, -1.0], min_profit_factor=1.2, min_trades=30)
        self.assertFalse(passed)
        self.assertIn("trade validasi", reason)

    def test_static_stop_and_long_holding_window(self):
        signal = datetime.date(2026, 7, 3)
        dates = next_idx_sessions(signal, 10)
        bars = {date: {"open": 100, "high": 102, "low": 98, "close": 100} for date in dates}
        trade = simulate_trade(signal, bars, 100, fee_buy_pct=0.15, fee_sell_pct=0.25, slippage_ticks=1, hold_sessions=10, take_profit_pct=20, static_stop_loss_pct=10)
        self.assertEqual(trade["exit_date"], dates[-1])
        self.assertEqual(trade["outcome"], "TIME_EXIT")
        self.assertEqual(trade["target"], 121)
        self.assertEqual(trade["stop"], 91)
