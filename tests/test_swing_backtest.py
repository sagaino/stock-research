import datetime
import unittest

from stockbit_ws.swing_backtest import evaluate_outcome, week_ends


class TestSwingBacktest(unittest.TestCase):
    def test_evaluates_exactly_five_following_sessions(self):
        signal = datetime.date(2026, 7, 3)
        bars = {signal: {"open": 100, "high": 101, "low": 99, "close": 100}}
        for offset, close in enumerate((102, 101, 104, 106, 105), 1):
            date = signal + datetime.timedelta(days=offset + 1)
            bars[date] = {"open": close, "high": close + 2, "low": close - 3, "close": close}
        outcome = evaluate_outcome(signal, bars)
        self.assertAlmostEqual(outcome["return_pct"], 5.0)
        self.assertAlmostEqual(outcome["max_up_pct"], 8.0)
        self.assertAlmostEqual(outcome["max_down_pct"], -2.0)

    def test_only_keeps_weeks_with_a_following_week(self):
        self.assertEqual(week_ends(datetime.date(2026, 6, 29), datetime.date(2026, 7, 12)), [datetime.date(2026, 7, 3)])
