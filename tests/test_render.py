from datetime import datetime, timezone
from io import StringIO
import unittest

from stockbit_ws.render import render_dashboard


class RenderTests(unittest.TestCase):
    def test_dashboard_has_two_sections_before_data_arrives(self):
        output = StringIO()
        render_dashboard("COCO", None, [], output=output, clear=True)
        content = output.getvalue()
        self.assertIn("COCO ORDER BOOK", content)
        self.assertIn("COCO RECENT DONE", content)
        self.assertIn("Bid Freq", content)
        self.assertIn("Trade ID", content)
        self.assertEqual(content.count("(waiting for data)"), 2)
        self.assertNotIn("\x1b", content)

    def test_formats_sections_in_wib_and_respects_done_limit(self):
        updated = datetime(2026, 9, 4, 23, 0, 0, 123000, tzinfo=timezone.utc)
        book = {"bid": [{"frequency": 3, "price": 135, "lot": 1000}], "offer": [], "updatedAt": updated}
        trade = {
            "symbol": "COCO", "timestamp": updated, "price": 136, "shares": 100,
            "sideCode": 1, "side": "BUY", "aggressor": "HAKA", "tradeId": 123456789,
            "lot": 1, "transactionValue": 13600, "changePoints": None, "changePercent": None,
        }
        output = StringIO()
        render_dashboard("COCO", book, [trade, trade], output=output, done_limit=1)
        content = output.getvalue()
        self.assertIn("2026-09-05 06:00:00.123 WIB", content)
        self.assertIn("06:00:00.123", content)
        self.assertIn("1,000", content)
        self.assertIn("Rp13.600", content)
        self.assertEqual(content.count("123456789"), 1)

    def test_untrusted_text_cannot_inject_terminal_commands(self):
        output = StringIO()
        render_dashboard("COCO\x1b[2J\n\u202e", None, [], output=output)
        content = output.getvalue()
        self.assertNotIn("\x1b", content)
        self.assertNotIn("\u202e", content)
        self.assertIn("COCO?[2J?? ORDER BOOK", content)


if __name__ == "__main__":
    unittest.main()
