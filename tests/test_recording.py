from datetime import timedelta
import json
import psycopg
import unittest

from stockbit_ws.events import normalize_event
from stockbit_ws.recording import RecordingError
from test_postgres import PostgresTestMixin
from test_quality import START, book, done

SECRET = "synthetic-authentication-never-persist-this"


class RecordingTests(PostgresTestMixin, unittest.TestCase):
    def test_allowlist_drops_secrets_and_retains_exact_market_values(self):
        writer = self.writer()
        payload = book()
        payload["jwt"] = SECRET
        payload["levels"][0]["unknown"] = SECRET
        trade = done((1 << 64) - 1)
        trade.update(session=SECRET, aggressor=SECRET)
        writer.append("book", payload, START, 0)
        writer.append("done", {"trades": [trade, trade], "raw": SECRET}, START, 0)
        writer.append("message", {"format": "text", "size": 500, "body": SECRET}, START, 0)
        writer.close(START + timedelta(seconds=20), 20)
        reader = self.reader()
        session = reader.select_session()
        events = list(reader.events(session))
        self.assertEqual(session["source"], "SYNTHETIC")
        self.assertEqual(len(events[1]["payload"]["trades"]), 2)
        self.assertEqual(events[1]["payload"]["trades"][0]["tradeId"], (1 << 64) - 1)
        self.assertEqual(events[1]["payload"]["trades"][0]["aggressor"], "HAKA")
        self.assertEqual(events[1]["payload"]["batchKind"], "unknown")
        stored = reader.connection.execute("SELECT payload FROM stockbit_ws.events WHERE session_id=%s", (writer.session_id,)).fetchall()
        self.assertNotIn(SECRET, json.dumps(stored))
        self.assertEqual(events[2]["payload"], {"format": "text", "size": 500})

    def test_append_sessions_preserves_previous_runs_and_reader_is_read_only(self):
        first = self.writer()
        first.append("book", book(), START, 0)
        first.close(START, 0)
        second = self.writer()
        second.append("book", book("OFFER", 136), START, 0)
        second.close(START, 0)
        reader = self.reader()
        self.assertEqual(len([row for row in reader.sessions() if row["id"] in self.session_ids]), 2)
        self.assertEqual(reader.select_session()["id"], second.session_id)
        events = list(reader.events(reader.select_session(first.session_id)))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["payload"]["side"], "BID")
        with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
            reader.connection.execute("DELETE FROM stockbit_ws.events WHERE session_id=%s", (first.session_id,))

    def test_invalid_market_values_fail_without_persisting_partial_event(self):
        writer = self.writer()
        for payload in ({"trades": [done()]}, {"trades": [done()]}):
            payload["trades"][0]["price"] = float("nan")
            with self.assertRaises(RecordingError):
                writer.append("done", payload, START, 0)
        with self.assertRaises(RecordingError):
            writer.append("unknown", {"token": SECRET}, START, 0)
        self.assertEqual(writer.sequence, 0)

    def test_event_order_uses_monotonic_time_even_if_wall_clock_changes(self):
        writer = self.writer()
        writer.append("book", book(), START, 2)
        writer.append("book", book("OFFER", 136), START - timedelta(seconds=60), 3)
        with self.assertRaises(RecordingError):
            writer.append("book", book(), START, 1)
        writer.close(START, 4)
        events = list(self.reader().events(self.reader().select_session()))
        self.assertEqual([event["elapsed"] for event in events], [2, 3])

    def test_corrupt_event_and_missing_sequence_fail_closed_without_echo(self):
        writer = self.writer()
        writer.append("book", book(), START, 0)
        writer.connection.execute("UPDATE stockbit_ws.events SET payload=%s::jsonb WHERE session_id=%s", (json.dumps({"invalid": SECRET}), writer.session_id))
        writer.close(START, 0)
        reader = self.reader()
        with self.assertRaises(RecordingError) as caught:
            list(reader.events(reader.select_session()))
        self.assertNotIn(SECRET, str(caught.exception))

    def test_open_session_is_readable_and_incomplete_status_preserved(self):
        writer = self.writer()
        writer.append("book", book(), START, 0)
        reader = self.reader()
        self.assertEqual(reader.select_session()["status"], "OPEN")
        self.assertEqual(len(list(reader.events(reader.select_session()))), 1)

    def test_closed_writer_rejects_new_events_and_close_is_idempotent(self):
        writer = self.writer()
        writer.close(START, 0, "STOPPED")
        writer.close(START, 0)
        with self.assertRaises(RecordingError):
            writer.append("book", book(), START, 0)
        self.assertEqual(self.reader().select_session()["status"], "STOPPED")

    def test_normalization_rejects_unknown_state_mixed_symbol_and_nonfinite_values(self):
        for kind, payload in (("connection", {"state": SECRET}), ("done", {"trades": [{**done(), "symbol": "BMRI"}]}), ("done", {"trades": [{**done(), "tradeId": 1.5}]})):
            with self.assertRaises(ValueError):
                normalize_event(kind, payload, "COCO")
