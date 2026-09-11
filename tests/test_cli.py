import base64
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import unittest
from unittest.mock import AsyncMock, patch

from stockbit_ws import cli
from stockbit_ws.config import FRAME_NAMES
from stockbit_ws.logger import SafeLogger
from test_subscription import make_frames
from test_trades import batch, bytes_field, record


def synthetic_environment():
    return {name: base64.b64encode(frame).decode("ascii") for name, frame in zip(FRAME_NAMES, make_frames())}


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.output = StringIO()
        self.logs = StringIO()
        self.dashboard = cli.Dashboard("COCO", SafeLogger(debug=True, output=self.logs), output=self.output)

    def test_one_binary_message_updates_both_sections_and_renders_once(self):
        mixed = bytes_field(10, b"#O|COCO|BID|135;3;12000|") + batch([record(trade_id=7)])
        with patch.object(self.dashboard, "render", wraps=self.dashboard.render) as render:
            self.dashboard.on_binary(mixed)
        self.assertEqual(self.dashboard.binary_messages, 1)
        self.assertEqual(self.dashboard.book_updates, 1)
        self.assertEqual(self.dashboard.done_batches, 1)
        self.assertEqual(self.dashboard.books["COCO"]["bid"][0]["lot"], 120)
        self.assertEqual(self.dashboard.recent["trades"][0]["tradeId"], 7)
        render.assert_called_once()
        self.assertIn("COCO ORDER BOOK", self.output.getvalue())
        self.assertIn("COCO RECENT DONE", self.output.getvalue())

    def test_only_requested_symbol_updates_book_and_recent_done(self):
        mixed = bytes_field(10, b"#O|BMRI|BID|5000;3;12000|") + batch([
            record(symbol=b"BMRI", trade_id=99), record(symbol=b"COCO", trade_id=7),
        ])
        self.dashboard.on_binary(mixed)
        self.assertEqual(self.dashboard.books, {})
        self.assertEqual(self.dashboard.book_updates, 0)
        self.assertEqual([trade["tradeId"] for trade in self.dashboard.recent["trades"]], [7])
        with patch.object(self.dashboard, "render") as render:
            self.dashboard.on_binary(batch([record(symbol=b"BMRI", trade_id=100)]))
        render.assert_not_called()
        self.assertEqual(self.dashboard.done_batches, 1)

    def test_malformed_and_unrelated_binary_messages_are_ignored(self):
        with patch.object(self.dashboard, "render") as render:
            for message in (b"", b"\xff", b"\x00", bytes_field(8, b"\xff"), bytes_field(30, b"unknown secret body")):
                self.dashboard.on_binary(message)
        render.assert_not_called()
        self.assertEqual(self.dashboard.binary_messages, 5)
        self.assertEqual(self.dashboard.books, {})
        self.assertEqual(self.dashboard.recent["trades"], [])
        self.assertNotIn("unknown secret body", self.logs.getvalue())

    def test_server_text_is_not_printed_even_with_debug_enabled(self):
        secret = "session-secret-password eyJcredential.jwt.signature\x1b[2J"
        self.dashboard.on_text(secret)
        self.dashboard.summary()
        self.assertIn("text", self.logs.getvalue())
        self.assertNotIn(secret, self.logs.getvalue() + self.output.getvalue())
        self.assertNotIn("session-secret-password", self.logs.getvalue())
        self.assertNotIn("\x1b", self.logs.getvalue())


class CliValidationTests(unittest.TestCase):
    def test_live_and_replay_share_the_same_sniper_config_builder(self):
        args = cli.build_parser().parse_args([
            "--replay", "postgres", "--sniper", "--hybrid",
            "--min-obs-seconds", "7", "--min-obs-trades", "21",
            "--min-obs-val", "42000000", "--paper-slippage-ticks", "2",
            "--no-l2-pre-entry", "--no-trading-hours-guard",
        ])
        config = cli.build_sniper_config(args)
        self.assertTrue(config.enable_hybrid_mode)
        self.assertEqual(config.min_observation_seconds, 7)
        self.assertEqual(config.min_observing_done_trades, 21)
        self.assertEqual(config.min_observing_haka_value_idr, 42_000_000)
        self.assertEqual(config.paper_slippage_ticks, 2)
        self.assertFalse(config.enable_l2_pre_entry_guard)
        self.assertFalse(config.enable_trading_hours_guard)

    def test_radar_delta_option_is_available_to_live_and_replay(self):
        args = cli.build_parser().parse_args(["--radar", "--min-delta-pct", "1.0"])
        self.assertEqual(args.min_delta_pct, 1.0)

    def test_storage_accepts_only_postgres_and_rejects_file_targets_before_io(self):
        for option in ("--record", "--replay"):
            self.assertEqual(getattr(cli.build_parser().parse_args([option]), option[2:]), "postgres")
            self.assertEqual(getattr(cli.build_parser().parse_args([option, "postgres"]), option[2:]), "postgres")
            with patch.object(cli, "load_environment") as load, patch.object(cli, "PostgresRecorder") as writer, redirect_stderr(StringIO()):
                with self.assertRaises(SystemExit) as caught:
                    cli.main([option, "old-recording.sqlite"])
                self.assertEqual(caught.exception.code, 2)
                load.assert_not_called()
                writer.assert_not_called()

    def test_check_validates_and_rewrites_synthetic_capture_without_network(self):
        output, errors = StringIO(), StringIO()
        with (
            patch.object(cli, "load_environment", return_value=synthetic_environment()) as load,
            patch.object(cli, "connect_stockbit_websocket", new_callable=AsyncMock) as connect,
            patch.object(cli.asyncio, "run", side_effect=AssertionError("Offline check started an event loop")) as run,
            redirect_stdout(output), redirect_stderr(errors),
        ):
            result = cli.main(["bmri", "--check", "--debug", "--env-file", "synthetic-only.env"])
        self.assertEqual(result, 0)
        load.assert_called_once_with("synthetic-only.env")
        connect.assert_not_awaited()
        run.assert_not_called()
        logs = output.getvalue() + errors.getvalue()
        self.assertIn("Subscription symbol: BMRI", logs)
        self.assertIn("Validasi offline OK", logs)
        self.assertIn("9 field", logs)
        self.assertNotIn("session-key", logs)
        self.assertNotIn("jwt-value", logs)

    def test_invalid_symbol_fails_before_config_or_network(self):
        with (
            patch.object(cli, "load_environment") as load,
            patch.object(cli, "connect_stockbit_websocket", new_callable=AsyncMock) as connect,
            patch.object(cli.asyncio, "run") as run,
            redirect_stderr(StringIO()),
        ):
            self.assertEqual(cli.main(["*"]), 1)
        load.assert_not_called()
        connect.assert_not_awaited()
        run.assert_not_called()

    def test_missing_configuration_fails_before_network(self):
        errors = StringIO()
        with (
            patch.object(cli, "load_environment", return_value={}),
            patch.object(cli, "connect_stockbit_websocket", new_callable=AsyncMock) as connect,
            patch.object(cli.asyncio, "run") as run,
            redirect_stderr(errors),
        ):
            self.assertEqual(cli.main(["COCO"]), 1)
        connect.assert_not_awaited()
        run.assert_not_called()
        self.assertIn("STOCKBIT_FRAME_1 belum diisi", errors.getvalue())

    def test_malformed_subscription_fails_even_when_requested_symbol_is_unchanged(self):
        values = {name: base64.b64encode(b"\xff").decode("ascii") for name in FRAME_NAMES}
        with (
            patch.object(cli, "load_environment", return_value=values),
            patch.object(cli, "connect_stockbit_websocket", new_callable=AsyncMock) as connect,
            patch.object(cli.asyncio, "run") as run,
            redirect_stderr(StringIO()),
        ):
            self.assertEqual(cli.main(["COCO", "--check"]), 1)
        connect.assert_not_awaited()
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
