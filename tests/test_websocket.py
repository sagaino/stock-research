"""Transport integration against ephemeral loopback servers only.

No .env, captured credential, or Stockbit connection is used by this module.
"""

import asyncio
from contextlib import asynccontextmanager, contextmanager
import io
import logging
import socket
import ssl
import traceback
import unittest

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.exceptions import InvalidStatus
from websockets.http11 import Response
from websockets.protocol import State

from stockbit_ws import websocket as transport
from stockbit_ws.config import MAX_FRAME_BYTES
from stockbit_ws.logger import SafeLogger, private_transport_logger


SECRET = "synthetic-private-session-do-not-log"
FRAMES = tuple(f"{SECRET}-frame-{index}".encode() for index in range(1, 4))


@contextmanager
def capture_root_debug():
    root = logging.getLogger()
    previous_level = root.level
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        yield output
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)


class LocalTransportTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.log_output = io.StringIO()
        self.logger = SafeLogger(debug=True, output=self.log_output)
        self.binary = []
        self.text = []

    @asynccontextmanager
    async def local_server(self, handler):
        async with serve(
            handler,
            "127.0.0.1",
            0,
            subprotocols=["web"],
            origins=[transport.WS_ORIGIN],
            ping_interval=None,
            logger=private_transport_logger(),
        ) as server:
            port = server.sockets[0].getsockname()[1]
            observed = {"options": None, "client": None, "requested_uri": None}

            @asynccontextmanager
            async def connector(uri, **options):
                observed["requested_uri"] = uri
                observed["options"] = dict(options)
                # Production keeps TLS verification; this test alone redirects
                # its connector to an explicitly local plaintext server.
                options.pop("ssl", None)
                async with connect(f"ws://127.0.0.1:{port}/ws", **options) as client:
                    observed["client"] = client
                    yield client

            yield connector, observed

    async def run_client(self, connector, **overrides):
        arguments = {
            "frames": FRAMES,
            "logger": self.logger,
            "on_binary": self.binary.append,
            "on_text": self.text.append,
            "connector": connector,
        }
        arguments.update(overrides)
        await transport.connect_stockbit_websocket(**arguments)

    def assert_no_session_tasks(self):
        names = [task.get_coro().__qualname__ for task in asyncio.all_tasks()]
        self.assertNotIn("send_initialization_frames", names)
        self.assertNotIn("run_session.<locals>.receive", names)

    async def test_origin_protocol_ordered_binary_timing_receive_and_ping_pong(self):
        received = []
        observed = {}
        loop = asyncio.get_running_loop()

        async def handler(server):
            observed["origin"] = server.request.headers.get("Origin")
            observed["protocol"] = server.subprotocol
            for index in range(3):
                message = await server.recv()
                received.append((loop.time(), message))
                if index == 0:
                    await server.send(b"market-snapshot")
                    await server.send("text-message")
                    pong = await server.ping(SECRET.encode())
                    await asyncio.wait_for(pong, timeout=1)
                    observed["pong"] = True
                if index == 1:
                    observed["received_concurrently"] = bool(self.binary and self.text)
            await server.close()

        with capture_root_debug() as root_logs:
            async with self.local_server(handler) as (connector, client_info):
                await asyncio.wait_for(self.run_client(connector), timeout=3)
            self.assertEqual(logging.getLogger().level, logging.DEBUG)
        self.assertEqual(observed["origin"], transport.WS_ORIGIN)
        self.assertEqual(observed["protocol"], "web")
        self.assertTrue(observed["pong"])
        self.assertTrue(observed["received_concurrently"])
        self.assertEqual([message for _, message in received], list(FRAMES))
        self.assertTrue(all(isinstance(message, bytes) for _, message in received))
        # Permit scheduling jitter while proving these weren't sent together.
        self.assertGreaterEqual(received[1][0] - received[0][0], 0.15)
        self.assertGreaterEqual(received[2][0] - received[0][0], 0.36)
        self.assertEqual(self.binary, [b"market-snapshot"])
        self.assertEqual(self.text, [b"text-message"])
        self.assertEqual(client_info["requested_uri"], transport.WS_URL)
        options = client_info["options"]
        self.assertEqual(options["subprotocols"], ["web"])
        self.assertEqual(options["max_size"], MAX_FRAME_BYTES)
        self.assertIsNone(options["proxy"])
        self.assertIsNone(options["ping_interval"])
        self.assertIsNone(options["user_agent_header"])
        self.assertTrue(options["logger"].disabled)
        self.assertFalse(options["logger"].propagate)
        self.assertEqual(client_info["client"].state, State.CLOSED)
        self.assertNotIn(SECRET, self.log_output.getvalue())
        self.assertNotIn(SECRET, root_logs.getvalue())
        self.assert_no_session_tasks()

    async def test_normal_server_early_close_cancels_remaining_initialization(self):
        received = []

        async def handler(server):
            received.append(await server.recv())
            await server.close(code=1000, reason=SECRET)

        with capture_root_debug() as root_logs:
            async with self.local_server(handler) as (connector, observed):
                with self.assertRaises(transport.TransportError) as caught:
                    await asyncio.wait_for(self.run_client(connector), timeout=2)
        self.assertEqual(received, [FRAMES[0]])
        self.assertIn("initialization", str(caught.exception))
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertNotIn(SECRET, self.log_output.getvalue() + root_logs.getvalue())
        self.assertEqual(observed["client"].state, State.CLOSED)
        self.assert_no_session_tasks()

    async def test_abnormal_close_reason_never_enters_logs_or_public_error(self):
        async def handler(server):
            await server.recv()
            await server.close(code=1008, reason=SECRET)

        with capture_root_debug() as root_logs:
            async with self.local_server(handler) as (connector, _):
                with self.assertRaises(transport.TransportError) as caught:
                    await asyncio.wait_for(self.run_client(connector), timeout=2)
        self.assertIn("1008", str(caught.exception))
        self.assertNotIn(SECRET, str(caught.exception))
        self.assertNotIn(SECRET, self.log_output.getvalue() + root_logs.getvalue())
        self.assert_no_session_tasks()

    async def test_duration_cancels_sender_receiver_and_closes_connection(self):
        received = []
        closed = asyncio.Event()

        async def handler(server):
            try:
                async for message in server:
                    received.append(message)
            finally:
                closed.set()

        async with self.local_server(handler) as (connector, observed):
            await asyncio.wait_for(self.run_client(connector, duration=0.08), timeout=2)
            await asyncio.wait_for(closed.wait(), timeout=1)
        self.assertEqual(received, [FRAMES[0]])
        self.assertEqual(observed["client"].state, State.CLOSED)
        self.assertIn("Batas durasi tercapai", self.log_output.getvalue())
        self.assert_no_session_tasks()

    async def test_explicit_cancellation_propagates_and_cleans_up(self):
        first_frame = asyncio.Event()
        closed = asyncio.Event()
        received = []

        async def handler(server):
            try:
                async for message in server:
                    received.append(message)
                    first_frame.set()
            finally:
                closed.set()

        async with self.local_server(handler) as (connector, observed):
            task = asyncio.create_task(self.run_client(connector))
            await asyncio.wait_for(first_frame.wait(), timeout=1)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            await asyncio.wait_for(closed.wait(), timeout=1)
        self.assertEqual(received, [FRAMES[0]])
        self.assertEqual(observed["client"].state, State.CLOSED)
        self.assert_no_session_tasks()

    async def test_raw_connector_exceptions_are_sanitized_even_with_debug_logging(self):
        rejected = InvalidStatus(Response(401, SECRET, Headers({"Set-Cookie": SECRET}), SECRET.encode()))
        errors = [
            RuntimeError(SECRET), OSError(SECRET), socket.gaierror(SECRET),
            ssl.SSLError(SECRET), TimeoutError(SECRET), rejected,
            transport.TransportError(SECRET),
        ]
        with capture_root_debug() as root_logs:
            for error in errors:
                @asynccontextmanager
                async def connector(*args, **kwargs):
                    raise error
                    yield  # pragma: no cover - establish async context manager

                with self.subTest(error=type(error).__name__):
                    with self.assertRaises(transport.TransportError) as caught:
                        await self.run_client(connector)
                    public_traceback = "".join(traceback.format_exception(caught.exception))
                    self.assertNotIn(SECRET, str(caught.exception))
                    self.assertNotIn(SECRET, public_traceback)
        self.assertNotIn(SECRET, self.log_output.getvalue() + root_logs.getvalue())

    async def test_callback_errors_are_sanitized_and_sender_is_cancelled(self):
        for exception_type in (RuntimeError, transport.TransportError):
            received = []

            async def handler(server):
                received.append(await server.recv())
                await server.send(b"synthetic-market-data")
                await server.wait_closed()

            def failing_callback(message):
                raise exception_type(SECRET)

            with self.subTest(exception_type=exception_type.__name__):
                async with self.local_server(handler) as (connector, observed):
                    with self.assertRaises(transport.TransportError) as caught:
                        await asyncio.wait_for(self.run_client(connector, on_binary=failing_callback), timeout=2)
                self.assertNotIn(SECRET, str(caught.exception))
                self.assertNotIn(SECRET, self.log_output.getvalue())
                self.assertEqual(received, [FRAMES[0]])
                self.assertEqual(observed["client"].state, State.CLOSED)
                self.assert_no_session_tasks()


class TLSConfigurationTests(unittest.TestCase):
    def test_production_context_checks_hostname_certificate_and_has_trust_roots(self):
        context = transport.create_tls_context()
        self.assertTrue(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
        self.assertGreater(context.cert_store_stats()["x509_ca"], 0)


if __name__ == "__main__":
    unittest.main()
