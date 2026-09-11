"""Unit tests for Dynamic Level 2 Order Book Sidecar WebSocket Manager."""

import asyncio
from contextlib import asynccontextmanager
import unittest
from unittest.mock import MagicMock

from websockets.exceptions import ConnectionClosed

from stockbit_ws.protobuf import encode_bytes_field, encode_message, encode_string_field
from stockbit_ws.recording import RecordingError
from stockbit_ws.sidecar import L2SidecarManager, send_sidecar_initialization_frames


def core_fields(symbol="COCO"):
    return [{"fieldNumber": number, "wireType": 2, "value": symbol.encode()} for number in (2, 6, 7, 9)]


def make_root(fields=None):
    wire = encode_string_field(1, "account")
    if fields is not None:
        wire += encode_bytes_field(2, encode_message(fields))
    return wire + encode_string_field(3, "session-key") + encode_string_field(5, "jwt-value")


def make_frames():
    return [
        make_root(),
        make_root(core_fields()),
        make_root(core_fields() + [{"fieldNumber": 5, "wireType": 2, "value": b"COCO"}]),
    ]


class MockWebSocket:
    def __init__(self, messages=None):
        self.messages = messages or []
        self.sent_frames = []

    async def send(self, frame):
        self.sent_frames.append(frame)

    def __aiter__(self):
        return self._generator()

    async def _generator(self):
        for msg in self.messages:
            yield msg


class TestSidecarManager(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.frames = make_frames()
        self.received_books = []
        self.logger = MagicMock()

    def _on_book(self, parsed):
        self.received_books.append(parsed)

    async def test_initial_state_and_ignores(self):
        manager = L2SidecarManager(self.frames, self._on_book, self.logger)
        self.assertFalse(manager.is_subscribed("PIPA"))
        manager.subscribe_symbol("")
        manager.subscribe_symbol("*")
        self.assertEqual(len(manager.active_tasks), 0)

    async def test_subscribe_and_stream_order_book(self):
        msg_bid = encode_bytes_field(10, b"#O|PIPA|BID|135;3;12000|134;2;8000|")
        msg_offer = encode_bytes_field(10, b"#O|PIPA|OFFER|136;5;20000|")
        mock_ws = MockWebSocket([msg_bid, msg_offer])

        @asynccontextmanager
        async def mock_connector(*args, **kwargs):
            yield mock_ws

        manager = L2SidecarManager(self.frames, self._on_book, self.logger, connector=mock_connector)
        manager.subscribe_symbol("PIPA")
        self.assertTrue(manager.is_subscribed("PIPA"))

        # Wait for sidecar task to finish consuming messages
        task = manager.active_tasks["PIPA"]
        await task

        self.assertEqual(len(self.received_books), 2)
        self.assertEqual(self.received_books[0]["symbol"], "PIPA")
        self.assertEqual(self.received_books[0]["side"], "BID")
        self.assertEqual(len(self.received_books[0]["levels"]), 2)
        self.assertEqual(self.received_books[1]["side"], "OFFER")
        self.assertEqual(self.received_books[1]["levels"][0]["price"], 136)
        self.assertEqual(len(mock_ws.sent_frames), 3)

    async def test_idempotent_subscription(self):
        mock_ws = MockWebSocket([])

        @asynccontextmanager
        async def mock_connector(*args, **kwargs):
            await asyncio.sleep(0.5)
            yield mock_ws

        manager = L2SidecarManager(self.frames, self._on_book, self.logger, connector=mock_connector)
        manager.subscribe_symbol("PIPA")
        task1 = manager.active_tasks["PIPA"]

        # Second subscribe must not replace the existing active task
        manager.subscribe_symbol("PIPA")
        task2 = manager.active_tasks["PIPA"]
        self.assertIs(task1, task2)

        manager.unsubscribe_symbol("PIPA")
        try:
            await task1
        except asyncio.CancelledError:
            pass
        self.assertTrue(task1.cancelled())

    async def test_unsubscribe_cancels_task_cleanly(self):
        mock_ws = MockWebSocket([])

        @asynccontextmanager
        async def mock_connector(*args, **kwargs):
            try:
                while True:
                    await asyncio.sleep(0.1)
            finally:
                pass
            yield mock_ws

        manager = L2SidecarManager(self.frames, self._on_book, self.logger, connector=mock_connector)
        manager.subscribe_symbol("PIPA")
        self.assertTrue(manager.is_subscribed("PIPA"))

        task = manager.active_tasks["PIPA"]
        manager.unsubscribe_symbol("PIPA")
        self.assertFalse(manager.is_subscribed("PIPA"))
        try:
            await task
        except asyncio.CancelledError:
            pass
        self.assertTrue(task.cancelled())

    async def test_old_task_cannot_remove_replacement_subscription(self):
        started = asyncio.Event()

        @asynccontextmanager
        async def mock_connector(*args, **kwargs):
            started.set()
            await asyncio.Event().wait()
            yield MockWebSocket([])

        manager = L2SidecarManager(self.frames, self._on_book, self.logger, connector=mock_connector)
        manager.subscribe_symbol("PIPA")
        old_task = manager.active_tasks["PIPA"]
        await started.wait()
        manager.unsubscribe_symbol("PIPA")
        manager.subscribe_symbol("PIPA")
        new_task = manager.active_tasks["PIPA"]
        self.assertIsNot(old_task, new_task)
        try:
            await old_task
        except asyncio.CancelledError:
            pass
        self.assertIs(manager.active_tasks.get("PIPA"), new_task)
        manager.unsubscribe_symbol("PIPA")
        try:
            await new_task
        except asyncio.CancelledError:
            pass

    async def test_close_all_cleans_up_multiple_tasks(self):
        @asynccontextmanager
        async def mock_connector(*args, **kwargs):
            while True:
                await asyncio.sleep(0.1)
            yield MockWebSocket([])

        manager = L2SidecarManager(self.frames, self._on_book, self.logger, connector=mock_connector)
        manager.subscribe_symbol("PIPA")
        manager.subscribe_symbol("MDIA")
        self.assertEqual(len(manager.active_tasks), 2)

        manager.close_all()
        self.assertEqual(len(manager.active_tasks), 0)

    async def test_server_connection_closed_handled_cleanly(self):
        @asynccontextmanager
        async def mock_connector(*args, **kwargs):
            raise ConnectionClosed(None, None)
            yield MockWebSocket([])

        manager = L2SidecarManager(self.frames, self._on_book, self.logger, connector=mock_connector)
        manager.subscribe_symbol("PIPA")
        task = manager.active_tasks["PIPA"]
        await task
        self.assertFalse(manager.is_subscribed("PIPA"))

    async def test_generic_error_handled_cleanly(self):
        @asynccontextmanager
        async def mock_connector(*args, **kwargs):
            raise RuntimeError("Network failure")
            yield MockWebSocket([])

        manager = L2SidecarManager(self.frames, self._on_book, self.logger, connector=mock_connector)
        manager.subscribe_symbol("PIPA")
        task = manager.active_tasks["PIPA"]
        await task
        self.assertFalse(manager.is_subscribed("PIPA"))

    async def test_invalid_base_frames_handled(self):
        manager = L2SidecarManager([b"invalid"], self._on_book, self.logger)
        manager.subscribe_symbol("PIPA")
        self.assertEqual(len(manager.active_tasks), 0)

    async def test_send_sidecar_initialization_frames_validation(self):
        mock_ws = MockWebSocket([])
        with self.assertRaises(ValueError):
            await send_sidecar_initialization_frames(mock_ws, [b"frame1"])

    async def test_callback_failure_is_exposed_to_main_session(self):
        message = encode_bytes_field(10, b"#O|PIPA|BID|135;3;12000|")
        mock_ws = MockWebSocket([message])

        @asynccontextmanager
        async def mock_connector(*args, **kwargs):
            yield mock_ws

        def fail(_book):
            raise RecordingError("synthetic failure")

        manager = L2SidecarManager(self.frames, fail, self.logger, connector=mock_connector)
        manager.subscribe_symbol("PIPA")
        await manager.active_tasks["PIPA"]
        with self.assertRaisesRegex(RecordingError, "sesi utama dihentikan"):
            manager.raise_if_failed()


if __name__ == "__main__":
    unittest.main()
