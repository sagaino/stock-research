"""Single authenticated connection; no orders, reconnect, or session refresh."""

import asyncio
import socket
import ssl

import certifi
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from .config import MAX_FRAME_BYTES
from .logger import private_transport_logger
from .recording import RecordingError

WS_URL = "wss://wss-trading.stockbit.com/ws"
WS_ORIGIN = "https://stockbit.com"
WS_PROTOCOL = "web"


def create_tls_context():
    # Some macOS Python installs have no default CA file/directory. Add the
    # Mozilla root bundle without disabling hostname/certificate validation.
    context = ssl.create_default_context()
    context.load_verify_locations(cafile=certifi.where())
    return context


class TransportError(RuntimeError):
    """Safe public error, never a server body or a raw library exception."""


class _InitializationClosed(Exception):
    """Internal sentinel; never carries data from the feed or callbacks."""


async def send_initialization_frames(ws, frames, logger):
    if len(frames) != 3:
        raise ValueError("Initialization memerlukan tepat tiga frame.")
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    labels = ("init frame 1", "init frame 2", "subscription frame")
    for target, frame, label in zip((0, 0.180, 0.400), frames, labels):
        await asyncio.sleep(max(0, started_at + target - loop.time()))
        await ws.send(frame)
        logger.lifecycle(f"→ sent {label}")


async def run_session(ws, frames, logger, on_binary, on_text):
    async def receive():
        async for message in ws:
            if isinstance(message, bytes):
                on_binary(message)
            else:
                on_text(message.encode("utf-8"))

    sender = asyncio.create_task(send_initialization_frames(ws, frames, logger))
    receiver = asyncio.create_task(receive())
    try:
        done, _ = await asyncio.wait((sender, receiver), return_when=asyncio.FIRST_COMPLETED)
        # Check receiver first so a closed connection never keeps sending init.
        if receiver in done:
            receiver.result()
            if not sender.done():
                raise _InitializationClosed()
            sender.result()
            return
        sender.result()
        await receiver
    finally:
        for task in (sender, receiver):
            if not task.done():
                task.cancel()
        await asyncio.gather(sender, receiver, return_exceptions=True)


def _safe_failure(error):
    if isinstance(error, RecordingError):
        return "Perekaman gagal; koneksi dihentikan. Periksa ruang disk dan akses file rekaman."
    if isinstance(error, _InitializationClosed):
        return "WebSocket tertutup sebelum initialization selesai."
    if isinstance(error, InvalidStatus):
        status = error.response.status_code
        return f"Handshake WebSocket ditolak (HTTP {status}). Periksa masa berlaku session."
    if isinstance(error, ConnectionClosed):
        code = error.rcvd.code if error.rcvd is not None else 1006
        return f"WebSocket terputus (code {code}); alasan server tidak dicetak."
    if isinstance(error, ssl.SSLError):
        return "Validasi/koneksi TLS gagal. Verifikasi jaringan dan sertifikat lokal."
    if isinstance(error, socket.gaierror):
        return "Nama host WebSocket tidak dapat ditemukan."
    if isinstance(error, TimeoutError):
        return "Koneksi WebSocket melewati batas waktu."
    if isinstance(error, OSError):
        return "Koneksi jaringan WebSocket gagal."
    return "Sesi WebSocket gagal; detail mentah disembunyikan agar credential tidak tercetak."


async def connect_stockbit_websocket(*, frames, logger, on_binary, on_text, duration=None, connector=connect, on_connection=None):
    async def session():
        async with connector(
            WS_URL,
            origin=WS_ORIGIN,
            subprotocols=[WS_PROTOCOL],
            max_size=MAX_FRAME_BYTES,
            open_timeout=10,
            close_timeout=3,
            ping_interval=None,
            proxy=None,
            user_agent_header=None,
            logger=private_transport_logger(),
            ssl=create_tls_context(),
        ) as ws:
            logger.lifecycle("Connected")
            if on_connection is not None:
                on_connection("CONNECTED")
            await run_session(ws, frames, logger, on_binary, on_text)
            logger.lifecycle("WebSocket disconnected (normal close)")

    try:
        if duration is None:
            await session()
        else:
            timeout = asyncio.timeout(duration)
            try:
                async with timeout:
                    await session()
            except TimeoutError:
                if not timeout.expired():
                    raise
                logger.lifecycle("Batas durasi tercapai; koneksi ditutup.")
    except asyncio.CancelledError:
        raise
    except Exception as error:
        raise TransportError(_safe_failure(error)) from None
