from datetime import datetime, timedelta, timezone
import unittest

from stockbit_ws.events import normalize_event
from stockbit_ws.quality import FeedQuality

START = datetime(2026, 9, 4, 2, tzinfo=timezone.utc)


def book(side="BID", price=135):
    return {"symbol": "COCO", "side": side, "levels": [{"price": price, "shares": 10000, "frequency": 3}]}


def done(identifier=1, seconds=1):
    return {"symbol": "COCO", "timestamp": START + timedelta(seconds=seconds), "price": 136, "shares": 100,
            "sideCode": 1, "tradeId": identifier, "transactionValue": 13600}


class QualityTests(unittest.TestCase):
    def setUp(self):
        self.health = FeedQuality(START, stale_after=15, seen_limit=3)

    def apply(self, kind, payload, at=1):
        self.health.apply(kind, normalize_event(kind, payload, "COCO"), at)

    def full_market(self):
        self.apply("connection", {"state": "CONNECTED"})
        self.apply("book", book())
        self.apply("book", book("OFFER", 136))
        self.apply("done", {"trades": [done()]})

    def test_connecting_and_connected_are_not_proof_of_fresh_market_data(self):
        self.assertEqual(self.health.snapshot(START, 0)["status"], "CONNECTING")
        self.apply("connection", {"state": "CONNECTED"}, 0)
        self.apply("message", {"format": "binary", "size": 29})
        state = self.health.snapshot(START + timedelta(seconds=1), 1)
        self.assertEqual(state["status"], "WAITING")
        self.assertEqual(state["completeness"], "UNKNOWN")
        self.assertEqual(state["binaryMessages"], 1)

    def test_silence_becomes_stale_and_heartbeat_does_not_refresh_market(self):
        self.full_market()
        self.assertEqual(self.health.snapshot(START + timedelta(seconds=2), 2)["status"], "RECENT_OBSERVED")
        self.apply("message", {"format": "text", "size": 10}, 20)
        state = self.health.snapshot(START + timedelta(seconds=20), 20)
        self.assertEqual(state["status"], "STALE")
        self.assertEqual(state["messageAgeSeconds"], 0)
        self.assertEqual(state["bidAgeSeconds"], 19)
        self.assertEqual(state["offerAgeSeconds"], 19)
        self.assertIn("STALE_DONE_EVENT", state["issues"])

    def test_bid_does_not_refresh_offer_and_old_done_batch_is_still_old(self):
        self.full_market()
        self.apply("book", book(), 20)
        self.apply("done", {"trades": [done()]}, 20)
        state = self.health.snapshot(START + timedelta(seconds=20), 20)
        self.assertEqual(state["bidAgeSeconds"], 0)
        self.assertEqual(state["offerAgeSeconds"], 19)
        self.assertEqual(state["doneReceiveAgeSeconds"], 0)
        self.assertEqual(state["doneEventAgeSeconds"], 19)
        self.assertEqual(state["duplicatesWindow"], 1)

    def test_duplicates_late_records_and_initial_descending_snapshot(self):
        self.apply("done", {"trades": [done(2, 2), done(1, 1)]}, 3)
        self.assertEqual(self.health.late_done, 0)
        self.apply("done", {"trades": [done(2, 2), done(3, 0)]}, 4)
        self.assertEqual(self.health.duplicates, 1)
        self.assertEqual(self.health.late_done, 1)
        self.assertEqual(self.health.unique_done, 3)
        self.assertEqual(self.health.after_start, 2)

    def test_bounded_dedup_window_and_uint64_ids(self):
        self.apply("done", {"trades": [done((1 << 64) - i, i) for i in range(1, 6)]})
        self.assertEqual(len(self.health.seen), 3)
        self.assertEqual(self.health.evictions, 2)
        self.assertEqual(self.health.unique_done, 5)

    def test_clock_ahead_empty_crossed_and_disconnected_are_visible(self):
        self.full_market()
        self.apply("done", {"trades": [done(99, 60)]})
        self.apply("book", book("BID", 140))
        state = self.health.snapshot(START + timedelta(seconds=1), 1)
        self.assertEqual(state["status"], "PARTIAL")
        self.assertIn("DONE_CLOCK_AHEAD", state["issues"])
        self.assertIn("LOCKED_OR_CROSSED_BOOK", state["issues"])
        self.apply("book", {"symbol": "COCO", "side": "BID", "levels": []})
        self.assertIn("EMPTY_BID", self.health.snapshot(START, 1)["issues"])
        self.apply("connection", {"state": "DISCONNECTED"})
        self.assertEqual(self.health.snapshot(START, 1)["status"], "DISCONNECTED")
