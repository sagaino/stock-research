from datetime import datetime, timezone
import unittest

from stockbit_ws.orderbook import build_order_book_rows, format_number, parse_order_book_payload, update_order_book


class OrderBookTests(unittest.TestCase):
    def test_observed_payload_converts_shares_to_lots(self):
        self.assertEqual(parse_order_book_payload("#O|COCO|OFFER|140;1476;58320500|"), {
            "type": "#O", "symbol": "COCO", "side": "OFFER",
            "levels": [{"price": 140, "frequency": 1476, "shares": 58320500, "lot": 583205}],
        })

    def test_updates_are_separate_snapshots_per_side_and_symbol(self):
        books = {}
        when = datetime(2026, 1, 1, 0, 0, 0, 123456, tzinfo=timezone.utc)
        update_order_book(books, parse_order_book_payload("#O|COCO|BID|132;342;19624100|131;2;200|"), when)
        update_order_book(books, parse_order_book_payload("#O|COCO|OFFER|133;33;3114100|"), when)
        update_order_book(books, parse_order_book_payload("#O|BMRI|BID|5000;1;100|"), when)
        book = update_order_book(books, parse_order_book_payload("#O|COCO|BID|132;1;100|"), when)
        self.assertEqual(len(book["bid"]), 1)
        self.assertEqual(book["offer"][0]["price"], 133)
        self.assertEqual(books["BMRI"]["bid"][0]["price"], 5000)
        self.assertEqual(book["updatedAt"].microsecond, 123000)
        self.assertEqual(book["updatedAt"].tzinfo, timezone.utc)
        emptied = update_order_book(books, parse_order_book_payload("#O|COCO|BID|"), when)
        self.assertEqual(emptied["bid"], [])
        self.assertEqual(emptied["offer"], book["offer"])

    def test_malformed_payloads_and_levels_do_not_contaminate_book(self):
        for payload in (None, b"#O|COCO|BID", "#O|COCO", "#O|coco|BID|", "#O|COCO|BUY|", "#O|COCO\n|BID|", "#O|COCO|BID|" + "x" * (5 * 1024 * 1024)):
            with self.subTest(payload_type=type(payload).__name__):
                self.assertIsNone(parse_order_book_payload(payload))
        result = parse_order_book_payload("#O|COCO|BID|bad|1;2;3;4|-1;2;3|1;2.5;3|1;2;9007199254740992|１３２;2;3|132;2;301|")
        self.assertEqual(result["levels"], [{"price": 132, "frequency": 2, "shares": 301, "lot": 3.01}])

    def test_rows_handle_unequal_sides_and_group_numbers(self):
        books = {}
        update_order_book(books, parse_order_book_payload("#O|COCO|BID|132;342;19624100|"))
        book = update_order_book(books, parse_order_book_payload("#O|COCO|OFFER|133;33;3114100|134;1;150|"))
        self.assertEqual(build_order_book_rows(book), [
            {"Bid Freq": 342, "Bid Lot": "196,241", "Bid": 132, "Offer": 133, "Offer Lot": "31,141", "Offer Freq": 33},
            {"Bid Freq": "", "Bid Lot": "", "Bid": "", "Offer": 134, "Offer Lot": "1.5", "Offer Freq": 1},
        ])
        self.assertEqual(build_order_book_rows(None), [])
        self.assertEqual(format_number(0), "0")
        self.assertEqual(format_number(100), "100")
        self.assertEqual(format_number(1.005), "1.01")

    def test_invalid_state_fails_clearly(self):
        with self.assertRaises(TypeError):
            update_order_book([], {})
        with self.assertRaises(TypeError):
            update_order_book({}, None)


if __name__ == "__main__":
    unittest.main()
