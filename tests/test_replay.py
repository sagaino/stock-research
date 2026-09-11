import asyncio
from contextlib import asynccontextmanager, redirect_stderr, redirect_stdout
from datetime import timedelta
from io import StringIO
import unittest
from unittest.mock import AsyncMock, patch

from stockbit_ws import cli
from stockbit_ws.cli import Dashboard
from stockbit_ws.logger import SafeLogger
from stockbit_ws.recording import RecordingError
from test_postgres import PostgresTestMixin
from stockbit_ws.replay import ReplayClock, replay_session
from stockbit_ws.websocket import connect_stockbit_websocket
from stockbit_ws.logger import private_transport_logger
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from test_cli import synthetic_environment
from test_quality import START, book, done
from test_trades import batch, bytes_field, record


class ReplayTests(PostgresTestMixin, unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        super().setUp()
        self.logs = StringIO()
        self.logger = SafeLogger(output=self.logs)

    def dashboard(self, clock, recorder=None):
        return Dashboard("COCO", self.logger, output=StringIO(), clock=clock, recorder=recorder)

    async def test_binary_decode_record_replay_preserves_state_order_and_quality(self):
        clock = ReplayClock(START)
        writer = self.writer()
        dashboard = self.dashboard(clock, writer)
        dashboard.on_connection("CONNECTING")
        clock.advance(0.1)
        dashboard.on_connection("CONNECTED")
        clock.advance(0.1)
        dashboard.on_binary(bytes_field(30, b"secret-raw-server-message-do-not-record"))
        seconds = int(START.timestamp())
        clock.advance(0.8)
        first = record(seconds=seconds, trade_id=(1 << 64) - 2)
        dashboard.on_binary(bytes_field(10, b"#O|COCO|BID|135;3;12000|") + batch([first]))
        clock.advance(0.1)
        dashboard.on_binary(bytes_field(10, b"#O|COCO|OFFER|136;4;22000|"))
        clock.advance(0.9)
        dashboard.on_binary(batch([first, record(seconds=seconds + 1, trade_id=(1 << 64) - 1)]))
        clock.advance(20)
        dashboard.tick()
        self.assertEqual(dashboard.health()["status"], "STALE")
        dashboard.on_connection("DISCONNECTED")
        writer.close(clock.now(), clock.monotonic())
        reader = self.reader()
        session = reader.select_session()
        replayed = self.dashboard(ReplayClock(session["started_at"]))
        count = await replay_session(reader, session, replayed)
        self.assertEqual(count, writer.sequence)
        self.assertEqual(replayed.books, dashboard.books)
        self.assertEqual(replayed.recent, dashboard.recent)
        self.assertEqual(replayed.health(), dashboard.health())
        self.assertEqual(replayed.binary_messages, 4)
        self.assertEqual(replayed.health()["duplicatesWindow"], 1)
        self.assertEqual(replayed.health()["uniqueDoneWindow"], 2)
        self.assertNotIn("secret-raw-server", str(list(reader.events(session))))

    async def test_replay_speed_waits_in_bounded_steps_and_preserves_virtual_end(self):
        writer = self.writer()
        writer.append("connection", {"state": "CONNECTED"}, START, 0)
        writer.append("book", book(), START + timedelta(seconds=3), 3)
        writer.close(START + timedelta(seconds=5), 5)
        reader = self.reader()
        session = reader.select_session()
        dashboard = self.dashboard(ReplayClock(START))
        with patch("stockbit_ws.replay.asyncio.sleep", new_callable=AsyncMock) as sleep:
            await replay_session(reader, session, dashboard, speed=2)
        delays = [call.args[0] for call in sleep.await_args_list]
        self.assertAlmostEqual(sum(delays), 2.5)
        self.assertTrue(all(0 <= delay <= 1 for delay in delays))
        self.assertEqual(dashboard.clock.now(), START + timedelta(seconds=5))
        self.assertEqual(dashboard.health()["bidAgeSeconds"], 2)

    async def test_last_session_does_not_merge_previous_symbol_or_book(self):
        for side in ("BID", "OFFER"):
            writer = self.writer()
            writer.append("book", book(side, 136), START, 0)
            writer.close(START, 0)
        reader = self.reader()
        dashboard = self.dashboard(ReplayClock(START))
        await replay_session(reader, reader.select_session(), dashboard)
        self.assertEqual(dashboard.books["COCO"]["bid"], [])
        self.assertEqual(len(dashboard.books["COCO"]["offer"]), 1)

    async def test_recording_failure_is_not_swallowed_by_binary_parser(self):
        writer = self.writer()
        dashboard = self.dashboard(ReplayClock(START), writer)
        with patch.object(writer, "append", side_effect=RecordingError("fixed safe failure")):
            with self.assertRaises(RecordingError):
                dashboard.on_binary(bytes_field(10, b"#O|COCO|BID|135;3;12000|"))
        self.assertTrue(dashboard.recording_failed)
        self.assertEqual(dashboard.books, {})
        writer.close(START, 0, "ERROR")

    async def test_loopback_websocket_through_recorder_then_offline_replay(self):
        frames = [b"synthetic-auth-frame-one", b"synthetic-auth-frame-two", b"synthetic-auth-frame-three"]
        writer = self.writer()
        dashboard = self.dashboard(ReplayClock(START), writer)
        received = []

        async def handler(server):
            for _ in frames:
                received.append(await server.recv())
            await server.send(bytes_field(10, b"#O|COCO|BID|135;3;12000|") + batch([record(), record()]))
            await server.send(bytes_field(10, b"#O|COCO|OFFER|136;4;22000|"))
            await server.close()

        async with serve(handler, "127.0.0.1", 0, subprotocols=["web"], logger=private_transport_logger()) as server:
            port = server.sockets[0].getsockname()[1]

            @asynccontextmanager
            async def connector(uri, **options):
                options.pop("ssl")  # Only this loopback fixture is plaintext.
                async with connect(f"ws://127.0.0.1:{port}", **options) as socket:
                    yield socket

            await asyncio.wait_for(connect_stockbit_websocket(frames=frames, logger=self.logger, on_binary=dashboard.on_binary, on_text=dashboard.on_text, on_connection=dashboard.on_connection, connector=connector), 3)
        dashboard.on_connection("DISCONNECTED")
        writer.close(START, 0)
        self.assertEqual(received, frames)
        reader = self.reader()
        replayed = self.dashboard(ReplayClock(START))
        await replay_session(reader, reader.select_session(), replayed)
        self.assertEqual(replayed.books, dashboard.books)
        self.assertEqual(replayed.recent, dashboard.recent)
        self.assertEqual(replayed.health()["duplicatesWindow"], 1)
        self.assertNotIn("synthetic-auth-frame", str(list(reader.events(reader.select_session()))))

    async def test_ui_throttling_does_not_drop_recorded_events(self):
        writer = self.writer()
        dashboard = self.dashboard(ReplayClock(START), writer)
        with patch.object(dashboard, "render", wraps=dashboard.render) as render:
            for identifier in range(50):
                dashboard.on_binary(batch([record(trade_id=identifier)]))
            self.assertEqual(render.call_count, 1)
        self.assertEqual(dashboard.done_batches, 50)
        self.assertEqual(writer.sequence, 100)  # message metadata + Done each time
        writer.close(START, 0)

    async def test_tick_detects_staleness_without_any_new_messages(self):
        clock = ReplayClock(START)
        dashboard = self.dashboard(clock)
        dashboard.on_connection("CONNECTED")
        dashboard.accept("book", book())
        dashboard.accept("book", book("OFFER", 136))
        dashboard.accept("done", {"trades": [done(seconds=0)]})
        dashboard.render()
        clock.advance(16)
        with patch.object(dashboard, "render", wraps=dashboard.render) as render:
            dashboard.tick()
        render.assert_called_once()
        self.assertIn("STALE", dashboard.output.getvalue())


class RecordingCliTests(PostgresTestMixin, unittest.TestCase):

    def test_cli_live_mock_records_then_replays_without_environment_or_network(self):
        async def transport(**kwargs):
            kwargs["on_connection"]("CONNECTED")
            kwargs["on_binary"](bytes_field(10, b"#O|COCO|BID|135;3;12000|") + batch([record()]))
            kwargs["on_text"](b"never-persist-secret-text")

        with patch.object(cli, "PostgresRecorder", side_effect=self.writer), patch.object(cli, "load_environment", return_value=synthetic_environment()), patch.object(cli, "connect_stockbit_websocket", side_effect=transport), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(cli.main(["COCO", "--record", "postgres"]), 0)
        output, errors = StringIO(), StringIO()
        with patch.object(cli, "load_environment", side_effect=AssertionError("Replay read credentials")), patch.object(cli, "connect_stockbit_websocket", side_effect=AssertionError("Replay opened network")), redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(cli.main(["--replay", "postgres"]), 0)
        self.assertIn("REPLAY POSTGRES", errors.getvalue())
        self.assertIn("COCO ORDER BOOK", output.getvalue())
        self.assertIn("Replay selesai", errors.getvalue())
        reader = self.reader()
        self.assertNotIn("never-persist-secret", str(list(reader.events(reader.select_session()))))

    def test_cli_lists_sessions_and_rejects_conflicting_modes_without_writes(self):
        writer = self.writer()
        writer.close(START, 0)
        errors = StringIO()
        with redirect_stderr(errors):
            self.assertEqual(cli.main(["--replay", "postgres", "--sessions"]), 0)
            for arguments in (["--replay", "postgres", "--record", "postgres"], ["--session", writer.session_id], ["--replay", "postgres", "--speed", "nan"], ["--replay", "postgres", "--stale-after", "10"], ["--check", "--record", "postgres"]):
                self.assertEqual(cli.main(arguments), 1)
        self.assertIn(writer.session_id, errors.getvalue())
        self.assertIn("SYNTHETIC", errors.getvalue())

    def test_cli_storage_failure_returns_error_and_marks_session(self):
        async def transport(**kwargs):
            raise RecordingError("Storage unavailable")

        with patch.object(cli, "PostgresRecorder", side_effect=self.writer), patch.object(cli, "load_environment", return_value=synthetic_environment()), patch.object(cli, "connect_stockbit_websocket", side_effect=transport), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(cli.main(["COCO", "--record", "postgres"]), 1)
        reader = self.reader()
        self.assertEqual(reader.select_session()["status"], "ERROR")

    def test_cli_replay_missing_or_wrong_symbol_fails_safely(self):
        with patch("stockbit_ws.replay.PostgresReader", side_effect=RecordingError("Unavailable")), redirect_stderr(StringIO()):
            self.assertEqual(cli.main(["--replay", "postgres"]), 1)
        writer = self.writer()
        writer.close(START, 0)
        with redirect_stderr(StringIO()):
            self.assertEqual(cli.main(["BMRI", "--replay", "postgres"]), 1)

    def test_cli_replay_with_radar_activates_scanner(self):
        writer = self.writer()
        writer.close(START, 0)
        output, errors = StringIO(), StringIO()
        with redirect_stdout(output), redirect_stderr(errors):
            self.assertEqual(cli.main(["--replay", "postgres", "--radar"]), 0)
        self.assertIn("Market Radar AKTIF", errors.getvalue())
        self.assertIn("Radar Anomali:", errors.getvalue())

