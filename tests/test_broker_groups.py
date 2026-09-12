import unittest
from datetime import time
from unittest.mock import MagicMock, patch

import httpx

from stockbit_ws.broker_groups import broker_group
from stockbit_ws.exodus_l2 import fetch_l2_ticks_forward
from stockbit_ws.phase3_scanner import scan_absorption, scan_sweeping


class BrokerGroupTests(unittest.TestCase):
    def test_known_groups_are_shared_by_scanners(self):
        self.assertEqual(broker_group("XL Nama"), "retail")
        self.assertEqual(broker_group("AK Nama"), "smart")
        self.assertIsNone(broker_group("UNKNOWN"))

    def test_absorption_only_counts_known_smart_buyer(self):
        ticks = [
            {"action": "sell", "seller_code": "XL", "buyer_code": "AK", "lot": 10, "price": 100},
            {"action": "sell", "seller_code": "XL", "buyer_code": "ZZ", "lot": 100, "price": 100},
        ]
        absorbers, total_lot, _ = scan_absorption(ticks)
        self.assertEqual(total_lot, 110)
        self.assertEqual([row["broker"] for row in absorbers], ["AK"])

    def test_sweeping_uses_same_broker_window_even_when_tape_is_interleaved(self):
        ticks = [
            {"action": "buy", "buyer_code": "AK", "lot": 1, "price": 100, "time": time(9, 0, 0)},
            {"action": "buy", "buyer_code": "YU", "lot": 1, "price": 200, "time": time(9, 0, 1)},
            {"action": "buy", "buyer_code": "AK", "lot": 1, "price": 102, "time": time(9, 0, 1)},
            {"action": "buy", "buyer_code": "AK", "lot": 1, "price": 104, "time": time(9, 0, 2)},
        ]
        sweeps = scan_sweeping(ticks)
        self.assertEqual([row["broker"] for row in sweeps], ["AK"])

    def test_l2_cursor_must_advance(self):
        client = MagicMock(spec=httpx.Client)
        response = MagicMock()
        response.json.return_value = {
            "data": {"running_trade": [{"trade_number": 7}]}
        }
        client.get.return_value = response
        with patch("stockbit_ws.exodus_l2.time.sleep"):
            with self.assertRaisesRegex(RuntimeError, "cursor trade_number"):
                list(fetch_l2_ticks_forward(client, "2026-09-11"))


if __name__ == "__main__":
    unittest.main()
