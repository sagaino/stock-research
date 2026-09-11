"""Observable feed health, never a trading signal or completeness guarantee."""

from collections import OrderedDict
from datetime import datetime, timezone
import time

from .events import utc_time


class Clock:
    def now(self):
        value = datetime.now(timezone.utc)
        return value.replace(microsecond=value.microsecond // 1000 * 1000)

    def monotonic(self):
        return time.monotonic()


class FeedQuality:
    def __init__(self, started_at, stale_after=15.0, seen_limit=10_000, *, require_book=True):
        if stale_after <= 0 or seen_limit < 1:
            raise ValueError("Invalid quality limits")
        self.started_at = utc_time(started_at)
        self.stale_after = stale_after
        self.seen_limit = seen_limit
        self.require_book = require_book
        self.connection = "CONNECTING"
        self.side_at = {}
        self.levels = {}
        self.done_received_at = None
        self.latest_done = None
        self.last_message_at = None
        self.binary_messages = self.text_messages = 0
        self.book_updates = self.done_batches = 0
        self.duplicates = self.unique_done = self.late_done = self.after_start = self.evictions = 0
        # ponytail: 10k-key window, not lifetime uniqueness; query the journal
        # for full-session dedup if analysis later needs exact total counts.
        self.seen = OrderedDict()

    def apply(self, kind, payload, elapsed):
        if kind == "connection":
            self.connection = payload["state"]
        elif kind == "message":
            self.last_message_at = elapsed
            if payload["format"] == "binary":
                self.binary_messages += 1
            else:
                self.text_messages += 1
        elif kind == "book":
            self.book_updates += 1
            self.side_at[payload["side"]] = elapsed
            self.levels[payload["side"]] = payload["levels"]
        elif kind == "done":
            self.done_batches += 1
            self.done_received_at = elapsed
            previous_latest = self.latest_done
            for trade in payload["trades"]:
                stamp = utc_time(trade["timestamp"])
                key = (trade["symbol"], trade["tradeId"]) if trade["tradeId"] is not None else (
                    trade["symbol"], trade["timestamp"], trade["price"], trade["shares"], trade["sideCode"],
                )
                if key in self.seen:
                    self.duplicates += 1
                    self.seen.move_to_end(key)
                    continue
                self.seen[key] = None
                if len(self.seen) > self.seen_limit:
                    self.seen.popitem(last=False)
                    self.evictions += 1
                self.unique_done += 1
                if previous_latest is not None and stamp < previous_latest:
                    self.late_done += 1
                if stamp > self.started_at:
                    self.after_start += 1
                if self.latest_done is None or stamp > self.latest_done:
                    self.latest_done = stamp

    def snapshot(self, now, elapsed):
        def age(at):
            return None if at is None else round(max(0, elapsed - at), 3)

        ages = {side: age(self.side_at.get(side)) for side in ("BID", "OFFER")}
        event_age = round((utc_time(now) - self.latest_done).total_seconds(), 3) if self.latest_done else None
        issues = []
        for side, seconds in ages.items():
            if not self.require_book:
                continue
            if seconds is None:
                issues.append("WAITING_" + side)
            else:
                if not self.levels[side]:
                    issues.append("EMPTY_" + side)
                if seconds > self.stale_after:
                    issues.append("STALE_" + side)
        if self.latest_done is None:
            issues.append("WAITING_DONE")
        elif event_age < -5:
            issues.append("DONE_CLOCK_AHEAD")
        elif event_age > self.stale_after:
            issues.append("STALE_DONE_EVENT")
        bids, offers = self.levels.get("BID", []), self.levels.get("OFFER", [])
        if bids and offers and max(level["price"] for level in bids) >= min(level["price"] for level in offers):
            issues.append("LOCKED_OR_CROSSED_BOOK")
        if self.connection != "CONNECTED":
            status = self.connection
        elif any(issue.startswith("STALE") for issue in issues):
            status = "STALE"
        elif issues:
            status = "WAITING" if not self.side_at and self.latest_done is None else "PARTIAL"
        else:
            status = "RECENT_OBSERVED"
        return {
            "status": status, "connection": self.connection, "issues": issues,
            "bidAgeSeconds": ages["BID"], "offerAgeSeconds": ages["OFFER"],
            "doneReceiveAgeSeconds": age(self.done_received_at), "doneEventAgeSeconds": event_age,
            "messageAgeSeconds": age(self.last_message_at),
            "binaryMessages": self.binary_messages, "textMessages": self.text_messages,
            "bookUpdates": self.book_updates, "doneBatches": self.done_batches,
            "uniqueDoneWindow": self.unique_done, "duplicatesWindow": self.duplicates,
            "lateDoneWindow": self.late_done, "timestampAfterStartWindow": self.after_start,
            "dedupEvictions": self.evictions, "dedupWindowLimit": self.seen_limit,
            "completeness": "UNKNOWN",
        }
