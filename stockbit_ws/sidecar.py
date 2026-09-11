"""Dynamic Level 2 Order Book Sidecar WebSocket Manager.

Enables on-demand, symbol-specific Level 2 Order Book streaming for active Sniper
slots while the master connection continues running in wildcard ('*') mode.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from .config import MAX_FRAME_BYTES
from .logger import private_transport_logger
from .orderbook import parse_order_book_payload
from .protobuf import find_order_book_payload
from .recording import RecordingError
from .subscription import prepare_frames_for_symbol
from .websocket import (
    WS_ORIGIN,
    WS_PROTOCOL,
    WS_URL,
    create_tls_context,
)
async def send_sidecar_initialization_frames(ws: Any, frames: list[bytes], logger: Any = None) -> None:
    """Send 3 initialization handshake frames without polluting user dashboard."""
    if len(frames) != 3:
        raise ValueError("Initialization memerlukan tepat tiga frame.")
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    for target, frame in zip((0, 0.180, 0.400), frames):
        await asyncio.sleep(max(0, started_at + target - loop.time()))
        await ws.send(frame)
    if logger and hasattr(logger, "debug"):
        logger.debug("→ [L2 SIDECAR] 3 handshake frames terkirim.")


class L2SidecarManager:
    """Manages concurrent dedicated WebSocket connections for active Sniper symbols."""

    def __init__(
        self,
        base_frames: list[bytes],
        on_book: Callable[[dict[str, Any]], None],
        logger: Any | None = None,
        connector: Any = connect,
        reconnect: bool = False,
    ):
        self.base_frames = base_frames
        self.on_book = on_book
        self.logger = logger
        self.connector = connector
        self.reconnect = reconnect
        self.active_tasks: dict[str, asyncio.Task[None]] = {}
        self.failure: RecordingError | None = None

    def is_subscribed(self, symbol: str) -> bool:
        task = self.active_tasks.get(symbol)
        return task is not None and not task.done()

    def subscribe_symbol(self, symbol: str) -> None:
        """Open an on-demand L2 dedicated WebSocket stream for the given symbol."""
        if not symbol or symbol == "*":
            return
        if self.is_subscribed(symbol):
            return

        try:
            prepared = prepare_frames_for_symbol(self.base_frames, symbol)
            dedicated_frames = prepared["frames"]
        except (ValueError, TypeError) as err:
            if self.logger:
                self.logger.debug(f"[L2 SIDECAR] Gagal membuat frame untuk {symbol}: {err}")
            return

        if self.logger:
            self.logger.lifecycle(f"📡 [L2 SIDECAR] Membuka koneksi Level 2 Order Book khusus {symbol}...")

        task = asyncio.create_task(self._run_sidecar(symbol, dedicated_frames))
        self.active_tasks[symbol] = task

    def unsubscribe_symbol(self, symbol: str) -> None:
        """Cleanly close and cancel the dedicated L2 stream for the given symbol."""
        task = self.active_tasks.pop(symbol, None)
        if task is not None and not task.done():
            task.cancel()
            if self.logger:
                self.logger.lifecycle(f"🔌 [L2 SIDECAR] Menutup koneksi Level 2 Order Book {symbol} (slot selesai).")

    async def _run_sidecar(self, symbol: str, frames: list[bytes]) -> None:
        """Run dedicated WebSocket session for a single symbol to stream order book events."""
        try:
            delay = 1.0
            while True:
                retry = False
                try:
                    async with self.connector(
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
                        if self.logger:
                            self.logger.debug(f"[L2 SIDECAR] Terhubung ke server Stockbit untuk {symbol}.")
                        await send_sidecar_initialization_frames(ws, frames, self.logger)
                        delay = 1.0
                        async for message in ws:
                            if not isinstance(message, bytes):
                                continue
                            try:
                                payload = find_order_book_payload(message)
                                parsed = parse_order_book_payload(payload) if payload is not None else None
                                if parsed and parsed.get("symbol") == symbol:
                                    try:
                                        self.on_book(parsed)
                                    except Exception:
                                        self.failure = RecordingError("Pemrosesan L2 sidecar gagal; sesi utama dihentikan agar tidak ditandai lengkap.")
                                        raise self.failure
                            except RecordingError:
                                self.failure = RecordingError("Perekaman L2 sidecar gagal; sesi utama dihentikan agar tidak ditandai lengkap.")
                                raise
                            except (ValueError, TypeError, OverflowError):
                                pass
                    retry = self.reconnect
                except ConnectionClosed:
                    if self.logger:
                        self.logger.debug(f"[L2 SIDECAR] Koneksi {symbol} terputus oleh server.")
                    retry = self.reconnect
                except RecordingError:
                    retry = False
                except Exception:
                    if self.logger:
                        self.logger.debug(f"[L2 SIDECAR] Sesi {symbol} mengalami gangguan; detail disembunyikan.")
                    retry = self.reconnect
                if not retry:
                    break
                if self.logger:
                    self.logger.lifecycle(f"↻ [L2 SIDECAR] Menghubungkan ulang {symbol} dalam {delay:.0f}s...")
                await asyncio.sleep(delay)
                delay = min(10.0, delay * 2)
        except asyncio.CancelledError:
            raise
        finally:
            # A cancelled task may finish after a replacement subscription is registered.
            # Only the task that owns the mapping may remove it.
            if self.active_tasks.get(symbol) is asyncio.current_task():
                self.active_tasks.pop(symbol, None)

    def raise_if_failed(self) -> None:
        if self.failure is not None:
            raise self.failure

    async def aclose_all(self) -> None:
        tasks = list(self.active_tasks.values())
        self.close_all()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def close_all(self) -> None:
        """Cancel and clean up all active sidecars upon system shutdown."""
        symbols = list(self.active_tasks.keys())
        for sym in symbols:
            self.unsubscribe_symbol(sym)
