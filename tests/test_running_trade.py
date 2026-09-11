"""Reported wildcard command, mixed-symbol state, and PostgreSQL replay.

Synthetic fixtures verify our implementation, not Stockbit server acceptance.
"""

import asyncio
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import unittest
from unittest.mock import patch

from stockbit_ws import cli
from stockbit_ws.events import normalize_event
from stockbit_ws.logger import SafeLogger
from stockbit_ws.protobuf import encode_bytes_field, parse_protobuf
from stockbit_ws.replay import ReplayClock, replay_session
from stockbit_ws.subscription import prepare_frames_for_running_trade
from test_cli import synthetic_environment
from test_postgres import PostgresTestMixin
from test_quality import START, book, done
from test_subscription import make_frames, make_root, core_fields, field_at
from test_trades import batch, record


def market_wire(identifier=1):
    return batch([record(symbol=symbol, trade_id=identifier, seconds=int(START.timestamp()))
                  for symbol in (b"BBCA", b"BMRI", b"COCO")])


class RunningTradeTests(unittest.TestCase):
    def test_subscription_is_trades_only_and_preserves_authentication_bytes(self):
        frames = make_frames()
        result = prepare_frames_for_running_trade(frames)
        self.assertEqual(result["frames"][0], frames[0])
        self.assertEqual(field_at(result["frames"][1], 2)["value"], b"")
        self.assertEqual(field_at(result["frames"][2], 2)["raw"], bytes.fromhex("12 03 2a 01 2a"))
        for original, rewritten in zip(frames, result["frames"]):
            before = [field["raw"] for field in parse_protobuf(original, strict=True, include_raw=True) if field["fieldNumber"] != 2]
            after = [field["raw"] for field in parse_protobuf(rewritten, strict=True, include_raw=True) if field["fieldNumber"] != 2]
            self.assertEqual(before, after)

    def test_subscription_rejects_ambiguous_or_unknown_commands(self):
        for frames in ([], make_frames()[:2],
                       [make_root(), make_root([]), make_root()],
                       [make_root(), make_root([]), make_root(core_fields()) + encode_bytes_field(2, b"")],
                       [make_root(), make_root([]), make_root(core_fields() + [{"fieldNumber": 99, "wireType": 2, "value": b"unknown"}])],
                       [make_root(), make_root([]), make_root(core_fields()) + encode_bytes_field(5, b"duplicate-auth")]):
            with self.subTest(frames=frames), self.assertRaises((ValueError, TypeError)):
                prepare_frames_for_running_trade(frames)

    def test_all_market_normalization_keeps_real_codes_and_rejects_invalid_codes(self):
        trades = [{**done(), "symbol": code} for code in ("BBCA", "BMRI", "COCO")]
        self.assertEqual([trade["symbol"] for trade in normalize_event("done", {"trades": trades}, "*")["trades"]], ["BBCA", "BMRI", "COCO"])
        for code in ("*", "", "BBCA\n", None):
            with self.assertRaises(ValueError):
                normalize_event("done", {"trades": [{**done(), "symbol": code}]}, "*")
        with self.assertRaises(ValueError):
            normalize_event("done", {"trades": trades}, "COCO")
        self.assertEqual(normalize_event("book", book(), "*")["symbol"], "COCO")
        for bad_code in ("*", "", "COCO\n", None):
            with self.assertRaises(ValueError):
                normalize_event("book", {**book(), "symbol": bad_code}, "*")

    def test_dashboard_displays_codes_deduplicates_per_symbol_and_ignores_books(self):
        output = StringIO()
        dashboard = cli.Dashboard("*", SafeLogger(output=StringIO()), output=output, clock=ReplayClock(START))
        dashboard.on_connection("CONNECTED")
        dashboard.on_binary(market_wire() + encode_bytes_field(10, b"#O|COCO|BID|135;3;12000|"))
        dashboard.on_binary(market_wire())
        dashboard.render()
        self.assertEqual(len(dashboard.recent["trades"]), 3)
        self.assertEqual(dashboard.health()["duplicatesWindow"], 3)
        self.assertEqual(dashboard.books, {})
        self.assertEqual(dashboard.health()["status"], "RECENT_OBSERVED")
        self.assertEqual(dashboard.health()["completeness"], "UNKNOWN")
        for text in ("Code", "BBCA", "BMRI", "COCO", "ALL MARKET RUNNING TRADE"):
            self.assertIn(text, output.getvalue())
        self.assertNotIn("ORDER BOOK", output.getvalue())
        dashboard.clock.advance(16)
        self.assertEqual(dashboard.health()["status"], "STALE")

    def test_check_builds_wildcard_without_network_and_rejects_conflicting_symbol(self):
        with patch.object(cli, "load_environment", return_value=synthetic_environment()), patch.object(cli, "connect_stockbit_websocket") as network, redirect_stderr(StringIO()), redirect_stdout(StringIO()):
            self.assertEqual(cli.main(["--all", "--check"]), 0)
            self.assertEqual(cli.main(["BMRI", "--all", "--check"]), 1)
            network.assert_not_called()


class RunningTradePostgresTests(PostgresTestMixin, unittest.TestCase):
    def test_cli_all_records_mixed_feed_with_wildcard_command(self):
        async def transport(**kwargs):
            self.assertEqual(field_at(kwargs["frames"][-1], 2)["value"], b"\x2a\x01*")
            kwargs["on_connection"]("CONNECTED")
            kwargs["on_binary"](market_wire())

        with patch.object(cli, "PostgresRecorder", side_effect=self.writer), patch.object(cli, "load_environment", return_value=synthetic_environment()), patch.object(cli, "connect_stockbit_websocket", side_effect=transport), redirect_stdout(StringIO()), redirect_stderr(StringIO()):
            self.assertEqual(cli.main(["--all", "--record"]), 0)
        reader = self.reader()
        session = reader.select_session(self.session_ids[-1])
        self.assertEqual(session["symbol"], "*")
        self.assertEqual(session["status"], "COMPLETED")
        trades = [trade for event in reader.events(session) if event["kind"] == "done" for trade in event["payload"]["trades"]]
        self.assertEqual({trade["symbol"] for trade in trades}, {"BBCA", "BMRI", "COCO"})

    def test_mixed_market_recording_replays_exactly_without_losing_bounded_display_overflow(self):
        writer = self.writer("*")
        clock = ReplayClock(START)
        logger = SafeLogger(output=StringIO())
        dashboard = cli.Dashboard("*", logger, output=StringIO(), clock=clock, recorder=writer)
        dashboard.on_connection("CONNECTED")
        for identifier in range(150):
            dashboard.on_binary(market_wire(identifier))
        dashboard.on_binary(market_wire(149))
        clock.advance(20)
        dashboard.on_connection("DISCONNECTED")
        writer.close(clock.now(), clock.monotonic())
        reader = self.reader()
        session = reader.select_session(writer.session_id)
        self.assertEqual(session["symbol"], "*")
        events = list(reader.events(session))
        self.assertEqual(len(events), writer.sequence)
        self.assertEqual(sum(len(event["payload"]["trades"]) for event in events if event["kind"] == "done"), 453)
        replayed = cli.Dashboard("*", logger, output=StringIO(), clock=ReplayClock(START))
        asyncio.run(replay_session(reader, session, replayed))
        self.assertEqual(replayed.recent, dashboard.recent)
        self.assertEqual(replayed.health(), dashboard.health())
        self.assertEqual(len(replayed.recent["trades"]), 100)
        self.assertEqual(replayed.health()["uniqueDoneWindow"], 450)
        self.assertEqual(replayed.health()["duplicatesWindow"], 3)
        with redirect_stdout(StringIO()), redirect_stderr(StringIO()), patch.object(cli, "load_environment", side_effect=AssertionError("Stockbit credentials read during replay")):
            self.assertEqual(cli.main(["--all", "--replay", "--session", writer.session_id]), 0)
