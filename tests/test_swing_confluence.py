import unittest

from stockbit_ws.swing_confluence import build_swing_plan, generate_macro_report


class TestSwingPlan(unittest.TestCase):
    def test_stop_is_below_entry_and_reward_is_positive(self):
        plan = build_swing_plan(close_price=545, broker_avg=584)
        entry_low = int(plan["entry"].split(" - ")[0])
        stop = int(plan["sl"].split()[0])

        self.assertLess(stop, entry_low)
        self.assertNotEqual(plan["rr_ratio"], "1 : 0.0")

    def test_macro_report_is_explicitly_not_an_l2_signal(self):
        report = generate_macro_report([{
            "symbol": "TINS", "top_buyer": "AK", "active_days": 4, "num_days": 5,
            "smart_net": 1_000_000_000, "retail_net": -500_000_000, "total_turnover": 10_000_000_000,
        }], "2026-09-04", ["2026-08-31", "2026-09-04"])
        self.assertIn("bukan sinyal trading", report)
        self.assertIn("TINS", report)
