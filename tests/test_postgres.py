"""Opt-in integration against this project's Docker PostgreSQL, never Stockbit.

Run: STOCKBIT_TEST_POSTGRES=1 uv run python -m unittest discover -s tests -p test_postgres.py -v
Only this test's freshly generated SYNTHETIC session IDs are removed afterwards.
"""

import asyncio
from io import StringIO
import os
import unittest
from unittest.mock import patch

import psycopg

from stockbit_ws.cli import Dashboard
from stockbit_ws.logger import SafeLogger
from stockbit_ws.postgres import connect_database, PostgresReader, PostgresRecorder
from stockbit_ws.recording import RecordingError
from stockbit_ws.replay import ReplayClock, replay_session
from test_quality import START
from test_trades import batch, bytes_field, record


class PostgresTestMixin:
    """Only clean up sessions created by the current test, never user data."""

    def setUp(self):
        super().setUp()
        if os.environ.get("STOCKBIT_TEST_POSTGRES") != "1":
            self.skipTest("Set STOCKBIT_TEST_POSTGRES=1 with project Docker PostgreSQL running")
        self.session_ids = []
        self.addCleanup(self.cleanup_sessions)

    def cleanup_sessions(self):
        if not self.session_ids:
            return
        with connect_database() as connection:
            for session_id in self.session_ids:
                connection.execute("DELETE FROM stockbit_ws.events WHERE session_id IN (SELECT id FROM stockbit_ws.sessions WHERE id=%s AND source='SYNTHETIC')", (session_id,))
                connection.execute("DELETE FROM stockbit_ws.sessions WHERE id=%s AND source='SYNTHETIC'", (session_id,))

    def writer(self, symbol="COCO", started_at=START, stale_after=15.0, *, source="SYNTHETIC"):
        writer = PostgresRecorder(symbol, started_at, stale_after, source="SYNTHETIC")
        self.session_ids.append(writer.session_id)
        self.addCleanup(lambda: writer.close(START, writer.last_elapsed / 1000, "ERROR") if not writer.closed else None)
        return writer

    def reader(self):
        reader = PostgresReader()
        self.addCleanup(reader.close)
        return reader


class PostgresConfigurationTests(unittest.TestCase):
    def test_connection_errors_do_not_echo_password_or_server_details(self):
        secret = "synthetic-password-must-not-be-logged"
        with patch("stockbit_ws.postgres.load_environment", return_value={"PG_PASSWORD": secret}), patch("stockbit_ws.postgres.psycopg.connect", side_effect=psycopg.OperationalError(secret)):
            with self.assertRaises(RecordingError) as caught:
                connect_database()
        self.assertNotIn(secret, str(caught.exception))


@unittest.skipUnless(os.environ.get("STOCKBIT_TEST_POSTGRES") == "1", "Set STOCKBIT_TEST_POSTGRES=1 with project Docker PostgreSQL running")
class PostgresIntegrationTests(unittest.TestCase):
    def test_record_restart_connection_paged_replay_and_read_only_boundary(self):
        ids = []

        def cleanup():
            with connect_database() as connection:
                for session_id in ids:
                    # Exact test-created IDs only; never reset tables or volumes.
                    connection.execute("DELETE FROM stockbit_ws.events WHERE session_id IN (SELECT id FROM stockbit_ws.sessions WHERE id=%s AND source='SYNTHETIC')", (session_id,))
                    connection.execute("DELETE FROM stockbit_ws.sessions WHERE id=%s AND source='SYNTHETIC'", (session_id,))

        writer = PostgresRecorder("COCO", START, source="SYNTHETIC")
        ids.append(writer.session_id)
        self.addCleanup(cleanup)
        self.addCleanup(lambda: writer.close(START, writer.last_elapsed / 1000, "ERROR") if not writer.closed else None)
        clock = ReplayClock(START)
        logger = SafeLogger(output=StringIO())
        original = Dashboard("COCO", logger, output=StringIO(), clock=clock, recorder=writer)
        original.on_connection("CONNECTED")
        large_id = (1 << 64) - 1
        wire = record(trade_id=large_id, seconds=int(START.timestamp()))
        original.on_binary(bytes_field(10, b"#O|COCO|BID|135;3;12000|") + batch([wire, wire]))
        original.on_binary(bytes_field(10, b"#O|COCO|OFFER|136;4;22000|"))
        for _ in range(205):
            original.on_text(b"synthetic-private-body-never-record")
        clock.advance(20)
        original.on_connection("DISCONNECTED")
        writer.close(clock.now(), clock.monotonic())

        # New writer/read connections prove committed data isn't connection-local.
        second = PostgresRecorder("BMRI", START, source="SYNTHETIC")
        ids.append(second.session_id)
        second.close(START, 0)
        reader = PostgresReader()
        self.addCleanup(reader.close)
        self.assertEqual(reader.select_session()["id"], second.session_id)
        session = reader.select_session(writer.session_id)
        events = list(reader.events(session))
        self.assertEqual(len(events), writer.sequence)
        self.assertGreater(len(events), 200)
        self.assertEqual([event["seq"] for event in events], list(range(1, len(events) + 1)))
        self.assertNotIn("synthetic-private-body", str(events))
        payload = next(event["payload"] for event in events if event["kind"] == "done")
        self.assertEqual(payload["trades"][0]["tradeId"], large_id)
        self.assertEqual(len(payload["trades"]), 2)
        with self.assertRaises(psycopg.errors.ReadOnlySqlTransaction):
            reader.connection.execute("DELETE FROM stockbit_ws.events WHERE session_id=%s", (writer.session_id,))
        replayed = Dashboard("COCO", logger, output=StringIO(), clock=ReplayClock(session["started_at"]))
        asyncio.run(replay_session(reader, session, replayed))
        self.assertEqual(replayed.books, original.books)
        self.assertEqual(replayed.recent, original.recent)
        self.assertEqual(replayed.health(), original.health())
        self.assertEqual(replayed.health()["duplicatesWindow"], 1)
