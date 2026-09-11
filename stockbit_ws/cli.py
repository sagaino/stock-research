"""Small read-only CLI; the dashboard is independent of its transport."""

import argparse
import asyncio
import json
import math
import signal
import sys

from .config import ConfigurationError, debug_enabled, load_captured_frames, load_environment
from .events import decoded_trades, normalize_event
from .logger import SafeLogger
from .orderbook import parse_order_book_payload, update_order_book
from .protobuf import find_order_book_payload
from .quality import Clock, FeedQuality
from .recording import RecordingError
from .postgres import PostgresRecorder
from .render import render_dashboard
from .subscription import SYMBOL_PATTERN, prepare_frames_for_symbol, prepare_frames_for_running_trade
from .trades import create_recent_trade_state, find_done_trade_batch, update_recent_trades
from .websocket import TransportError, connect_stockbit_websocket


class Dashboard:
    def __init__(self, symbol, logger, output=None, *, recorder=None, clock=None, stale_after=15.0, radar=None, sniper=None):
        self.symbol = symbol
        self.logger = logger
        self.output = output if output is not None else sys.stdout
        self.clock = clock or Clock()
        self.started_at = self.clock.now()
        self.started_mono = self.clock.monotonic()
        self.recorder = recorder
        self.recording_failed = False
        self.radar = radar
        self.sniper = sniper
        if self.radar is not None and self.radar.start_time is None:
            self.radar.start_time = self.started_at
        self.quality = FeedQuality(self.started_at, stale_after, require_book=symbol != "*")
        self.books = {}
        self.recent = create_recent_trade_state()
        self.binary_messages = self.book_updates = self.done_batches = 0
        self.last_render = float("-inf")
        self.last_quality_signature = None
        self.dirty = False
        self.finished = None

    def elapsed(self):
        return round(max(0, self.clock.monotonic() - self.started_mono), 3)

    def health(self):
        now, elapsed = self.finished or (self.clock.now(), self.elapsed())
        return self.quality.snapshot(now, elapsed)

    def render(self):
        radar_alerts = self.radar.alerts[-5:] if self.radar is not None else None
        sniper_table = self.sniper.format_table() if self.sniper is not None else None
        render_dashboard(
            self.symbol,
            self.books.get(self.symbol),
            self.recent["trades"],
            output=self.output,
            clear=True,
            quality=self.health(),
            radar_alerts=radar_alerts,
            sniper_table=sniper_table,
        )
        self.last_render = self.clock.monotonic()
        self.last_quality_signature = self._quality_signature()
        self.dirty = False

    def _quality_signature(self):
        health = self.health()
        return health["status"], tuple(health["issues"])

    def tick(self):
        # Wall-clock silence must become visible even when no messages arrive.
        if self.sniper is not None:
            self.sniper.tick(self.clock.now())
            self.dirty = True
        is_tty = callable(getattr(self.output, "isatty", None)) and self.output.isatty()
        if self.dirty or self._quality_signature() != self.last_quality_signature or is_tty:
            self.render()

    def accept(self, kind, payload, *, received_at=None, elapsed=None, record=True):
        safe = normalize_event(kind, payload, self.symbol)
        received_at = self.clock.now() if received_at is None else received_at
        elapsed = self.elapsed() if elapsed is None else elapsed
        if record and self.recorder is not None:
            try:
                self.recorder.append(kind, safe, received_at, elapsed)
            except RecordingError:
                self.recording_failed = True
                raise
        self.quality.apply(kind, safe, elapsed)
        if kind == "book":
            update_order_book(self.books, safe, now=received_at)
            self.book_updates += 1
            if self.sniper is not None:
                self.sniper.process_book(safe)
        elif kind == "done":
            incoming_trades = decoded_trades(safe)
            update_recent_trades(self.recent, incoming_trades)
            self.done_batches += 1
            if self.radar is not None and self.sniper is not None:
                # Interleave detection and observation per trade. Processing the
                # whole radar batch first would let Sniper observe earlier trades
                # after an alert raised by a later trade in the same message.
                for trade in self.radar.ordered_trades(incoming_trades):
                    for alert in self.radar.process_trade(trade):
                        self.sniper.handle_radar_alert(alert)
                        self.dirty = True
                    self.sniper.process_batch([trade], current_time=received_at)
            elif self.radar is not None:
                if self.radar.process_batch(incoming_trades):
                    self.dirty = True
            elif self.sniper is not None:
                self.sniper.process_batch(incoming_trades, current_time=received_at)
            if self.sniper is not None:
                self.dirty = True
        elif kind == "message" and safe["format"] == "binary":
            self.binary_messages += 1
        if kind != "message":
            self.dirty = True

    def on_connection(self, state):
        self.accept("connection", {"state": state})

    def on_binary(self, raw):
        received_at, elapsed = self.clock.now(), self.elapsed()
        self.accept("message", {"format": "binary", "size": len(raw)}, received_at=received_at, elapsed=elapsed)
        self.logger.binary(len(raw))
        parsed = None
        try:
            payload = find_order_book_payload(raw)
            parsed = parse_order_book_payload(payload) if payload is not None else None
        except (ValueError, TypeError, OverflowError):
            self.logger.debug("Order-book payload tidak dikenali; diabaikan.")
        if self.symbol != "*" and parsed and parsed["symbol"] == self.symbol:
            self.accept("book", parsed, received_at=received_at, elapsed=elapsed)
            self.logger.debug(f"orderbook {self.symbol} {parsed['side']}: {len(parsed['levels'])} levels")
        # Both decoders run: one message may contain both kinds of data.
        requested = []
        try:
            requested = [trade for trade in find_done_trade_batch(raw) or () if self.symbol == "*" or trade["symbol"] == self.symbol]
        except (ValueError, TypeError, OverflowError):
            self.logger.debug("Done payload tidak dikenali; diabaikan.")
        if requested:
            self.accept("done", {"trades": requested}, received_at=received_at, elapsed=elapsed)
            self.logger.debug(f"done {self.symbol}: {len(requested)} records dalam batch")
        # Coalesce terminal redraws; every event still reaches recording/state.
        if self.dirty and self.clock.monotonic() - self.last_render >= 0.25:
            self.render()

    def on_sidecar_book(self, parsed):
        received_at = self.clock.now()
        elapsed = self.elapsed()
        if self.recorder is not None:
            try:
                self.recorder.append("book", parsed, received_at, elapsed)
            except RecordingError:
                self.recording_failed = True
                raise
        update_order_book(self.books, parsed, now=received_at)
        self.book_updates += 1
        if self.sniper is not None:
            self.sniper.process_book(parsed, current_time=received_at)
        self.dirty = True
        if self.clock.monotonic() - self.last_render >= 0.25:
            self.render()

    def on_text(self, raw):
        self.accept("message", {"format": "text", "size": len(raw)})
        self.logger.debug(f"← {len(raw)} B text (body tidak dicetak)")

    def summary(self):
        self.logger.lifecycle(
            f"Ringkasan: {self.binary_messages} pesan binary, {self.book_updates} update order book, "
            f"{self.done_batches} batch Done, {len(self.recent['trades'])} Done tersimpan (maks. 100)."
        )
        self.logger.lifecycle("Kualitas: " + json.dumps(self.health(), sort_keys=True))
        if self.recent["trades"]:
            latest = self.recent["trades"][0]["timestamp"].isoformat(timespec="milliseconds")
            self.logger.lifecycle(f"Timestamp Done terbaru: {latest}; snapshot belum membuktikan transaksi live baru.")
        if self.radar is not None:
            self.logger.lifecycle(f"Radar Anomali: {len(self.radar.alerts)} alert terdeteksi.")
        if self.sniper is not None:
            self.logger.lifecycle(f"Sniper History: {len(self.sniper.history)} operasi pemantauan selesai.")


def _duration(value):
    try:
        number = float(value)
    except (ValueError, TypeError):
        raise argparse.ArgumentTypeError("Durasi harus berupa angka positif.") from None
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Durasi harus berupa angka positif.")
    return number


def build_parser():
    parser = argparse.ArgumentParser(description="Stockbit market data: Order Book + Recent Done (read-only).")
    parser.add_argument("symbol", nargs="?", help="Symbol saham, contoh BMRI (default COCO; replay mengikuti sesi)")
    parser.add_argument("--all", action="store_true", help="Running Trade semua saham (eksperimental) dengan Dynamic L2 Sidecar")
    parser.add_argument("--env-file", default=".env", help="File konfigurasi (default .env di folder aktif)")
    parser.add_argument("--debug", action="store_true", help="Metadata diagnostik tanpa isi frame/credential")
    parser.add_argument("--check", action="store_true", help="Validasi frame dan symbol secara offline; tidak membuka WebSocket")
    parser.add_argument("--duration", type=_duration, help="Tutup koneksi setelah N detik, termasuk waktu connecting")
    parser.add_argument("--record", nargs="?", const="postgres", choices=["postgres"], help="Rekam ke PostgreSQL")
    parser.add_argument("--stale-after", type=_duration, help="Ambang umur data live dalam detik (default 15; replay memakai nilai rekaman)")
    parser.add_argument("--replay", nargs="?", const="postgres", choices=["postgres"], help="Replay PostgreSQL; tidak membuka WebSocket Stockbit")
    parser.add_argument("--sessions", action="store_true", help="Daftar sesi PostgreSQL untuk --replay")
    parser.add_argument("--session", help="ID sesi replay; default sesi terakhir")
    parser.add_argument("--speed", type=float, default=0, help="Kecepatan replay: 0=langsung, 1=asli, 10=10x")
    parser.add_argument("--radar", action="store_true", help="Aktifkan Market Radar anomaly scanner (terutama pada --all)")
    parser.add_argument("--min-delta-pct", type=float, default=0.75, help="Minimal kenaikan harga untuk alert Breakout Radar (default 0.75%%)")
    parser.add_argument("--sniper", action="store_true", help="Aktifkan Sniper Manager taktis (maksimal 5 slot, otomatis aktifkan --radar)")
    parser.add_argument("--sniper-slots", type=int, default=5, help="Jumlah slot maksimal sniper (default 5)")
    parser.add_argument("--min-price", type=float, default=50.0, help="Minimal harga saham untuk masuk radar sniper (default 50: izinkan saham mulai Rp 50)")
    parser.add_argument("--max-price", type=float, default=0.0, help="Maksimal harga saham untuk masuk radar sniper (default 0 / tanpa batas)")
    parser.add_argument("--hybrid", action="store_true", help="Aktifkan Mode Hybrid (Partial Scalp TP + Trailing Runner)")
    parser.add_argument("--hybrid-scalp-ratio", type=float, default=0.5, help="Rasio alokasi lot untuk Tranche 1 Scalp TP (default 0.5 = 50%%)")
    parser.add_argument("--hybrid-runner-trailing-ticks", type=int, default=3, help="Jarak trailing ticks dari harga puncak untuk Tranche 2 Runner (default 3 tick fraksi IDX)")
    parser.add_argument("--hybrid-runner-be-ticks", type=int, default=1, help="Buffer tick di atas entry price (BEP + N tick) untuk menutup fee broker (default: 1)")
    parser.add_argument("--exclude", type=str, default="", help="Daftar kode saham yang di-blacklist (dipisahkan koma, misal: ITMG,TAPG,UNTR)")
    parser.add_argument("--spawn-terminal", action="store_true", help="Buka jendela terminal baru saat sniper terpancing")
    parser.add_argument("--min-obs-seconds", type=float, default=4.0, help="Minimum durasi observasi kontinu (detik) sebelum konfirmasi entry (default 4.0s)")
    parser.add_argument("--min-obs-trades", type=int, default=15, help="Minimum jumlah transaksi DONE kontinu saat observasi (default 15 trades)")
    parser.add_argument("--max-tape-silence", type=float, default=2.5, help="Maksimum jeda tanpa trade sebelum observasi dianggap sepi/batal (default 2.5s)")
    parser.add_argument("--min-obs-val", type=float, default=25_000_000.0, help="Minimum total rupiah HAKA saat observasi (default Rp 25.000.000)")
    parser.add_argument("--stagnant-hold", type=float, default=90.0, help="Batas waktu hold saham mandek di BEP sebelum scratch exit (default 90s)")
    parser.add_argument("--l2-pre-entry", action=argparse.BooleanOptionalAction, default=True, help="Verifikasi L2 Bid fortification >= 1.2x & minimal 1.500 lot bid sebelum entry (default: True)")
    parser.add_argument("--orderbook-exit-mode", choices=("legacy", "full"), default="legacy", help="Mode order book: legacy atau full Watchlist Pullback (default legacy)")
    parser.add_argument("--orderbook-wall-min-lots", type=float, default=10_000.0, help="Minimum lot wall biasa (default 10000)")
    parser.add_argument("--orderbook-psych-wall-min-lots", type=float, default=50_000.0, help="Minimum lot wall level psikologis (default 50000)")
    parser.add_argument("--orderbook-wall-ratio", type=float, default=3.0, help="Rasio wall terhadap median depth sekitar (default 3)")
    parser.add_argument("--orderbook-depletion-ratio", type=float, default=0.20, help="Sisa lot maksimal untuk menandai depleted (default 0.20)")
    parser.add_argument("--orderbook-refill-min-lots", type=float, default=1_000.0, help="Minimum lot refill per siklus (default 1000)")
    parser.add_argument("--orderbook-support-levels", type=int, default=2, help="Jumlah papan bid support yang diperiksa (default 2)")
    parser.add_argument("--trading-hours-guard", action=argparse.BooleanOptionalAction, default=True, help="Blokir entry baru setelah 15:35 WIB (default: True)")
    parser.add_argument("--dynamic-tp-refill-strikes", type=int, default=2, help="Minimal gelombang pengisian ulang offer sebelum trigger Dynamic TP (default: 2 strikes)")
    parser.add_argument("--paper-slippage-ticks", type=int, default=1, help="Slippage paper per sisi dalam tick IDX (default: 1)")
    return parser


def build_sniper_config(args):
    """One configuration path for live observation and replay."""
    from .sniper import SniperConfig

    excluded = [item.strip().upper() for item in args.exclude.split(",") if item.strip()]
    return SniperConfig(
        max_slots=args.sniper_slots,
        spawn_terminal=args.spawn_terminal,
        enable_hybrid_mode=args.hybrid,
        hybrid_scalp_ratio=args.hybrid_scalp_ratio,
        hybrid_runner_trailing_ticks=args.hybrid_runner_trailing_ticks,
        hybrid_runner_be_buffer_ticks=args.hybrid_runner_be_ticks,
        min_stock_price=args.min_price,
        max_stock_price=args.max_price,
        custom_excluded_symbols=excluded,
        min_observation_seconds=args.min_obs_seconds,
        min_observing_done_trades=args.min_obs_trades,
        max_tape_silence_seconds=args.max_tape_silence,
        min_observing_haka_value_idr=args.min_obs_val,
        stagnant_timeout_seconds=args.stagnant_hold,
        enable_l2_pre_entry_guard=args.l2_pre_entry,
        orderbook_exit_mode=args.orderbook_exit_mode,
        orderbook_wall_min_lots=args.orderbook_wall_min_lots,
        orderbook_psychological_wall_min_lots=args.orderbook_psych_wall_min_lots,
        orderbook_wall_ratio=args.orderbook_wall_ratio,
        orderbook_depletion_ratio=args.orderbook_depletion_ratio,
        orderbook_refill_min_lots=args.orderbook_refill_min_lots,
        orderbook_support_levels=args.orderbook_support_levels,
        enable_trading_hours_guard=args.trading_hours_guard,
        dynamic_tp_min_refill_strikes=args.dynamic_tp_refill_strikes,
        paper_slippage_ticks=args.paper_slippage_ticks,
    )


async def _run(dashboard=None, sidecar_manager=None, **kwargs):
    loop = asyncio.get_running_loop()
    task = asyncio.current_task()
    installed = False
    try:
        loop.add_signal_handler(signal.SIGTERM, task.cancel)
        installed = True
    except (NotImplementedError, RuntimeError):
        pass
    async def refresh():
        while True:
            await asyncio.sleep(1)
            if sidecar_manager is not None:
                sidecar_manager.raise_if_failed()
            dashboard.tick()

    ticker = asyncio.create_task(refresh()) if dashboard is not None else None
    transport = asyncio.create_task(connect_stockbit_websocket(**kwargs))
    try:
        watched = {transport} | ({ticker} if ticker is not None else set())
        done, _ = await asyncio.wait(watched, return_when=asyncio.FIRST_COMPLETED)
        for completed in done:
            completed.result()
    finally:
        transport.cancel()
        await asyncio.gather(transport, return_exceptions=True)
        if ticker is not None:
            ticker.cancel()
            await asyncio.gather(ticker, return_exceptions=True)
        if sidecar_manager is not None:
            await sidecar_manager.aclose_all()
        if installed:
            loop.remove_signal_handler(signal.SIGTERM)


def main(argv=None):
    args = build_parser().parse_args(argv)
    logger = SafeLogger()
    if not math.isfinite(args.speed) or args.speed < 0:
        logger.error("Kecepatan replay harus angka non-negatif.")
        return 1
    if args.sniper_slots < 1 or args.paper_slippage_ticks < 0 or args.min_delta_pct < 0:
        logger.error("Slot sniper minimal 1; paper slippage dan minimum delta tidak boleh negatif.")
        return 1
    if args.all and args.symbol is not None:
        logger.error("--all tidak dapat digabung dengan symbol tertentu.")
        return 1
    if args.replay:
        if args.record or args.check or args.duration or args.stale_after is not None:
            logger.error("Replay tidak dapat digabung dengan --record, --check, --duration, atau --stale-after.")
            return 1
        from .replay import replay_main
        return replay_main(args, logger)
    if args.sessions or args.session or args.speed != 0 or (args.check and args.record):
        logger.error("Opsi sesi/kecepatan memerlukan --replay; --check tidak membuat rekaman.")
        return 1
    symbol = "*" if args.all else (args.symbol or "COCO").strip().upper()
    args.stale_after = 15.0 if args.stale_after is None else args.stale_after
    if not args.all and SYMBOL_PATTERN.fullmatch(symbol) is None:
        logger.error("Symbol tidak valid. Gunakan contoh seperti COCO, BMRI, atau BBRI.")
        return 1
    try:
        environment = load_environment(args.env_file)
        logger.debug_enabled = args.debug or debug_enabled(environment.get("DEBUG_WS"))
        frames = load_captured_frames(environment)
    except ConfigurationError as error:
        logger.error(str(error))
        return 1
    try:
        subscription = prepare_frames_for_running_trade(frames) if symbol == "*" else prepare_frames_for_symbol(frames, symbol)
    except (ValueError, TypeError):
        logger.error("Struktur subscription capture tidak dikenali atau ambigu. Tidak ada frame yang dikirim.")
        return 1
    logger.lifecycle(f"Subscription symbol: {symbol}")
    if symbol == "*":
        logger.lifecycle("Running Trade semua saham EKSPERIMENTAL: subscription dan decoder perlu validasi live; kelengkapan UNKNOWN. Recording sinkron belum diuji untuk beban seluruh pasar.")
    logger.debug(f"Symbol capture: {subscription['capturedSymbol']}; {subscription['replacementCount']} field diganti.")
    if args.check:
        logger.lifecycle("Validasi offline OK: tiga frame valid dan symbol siap. Masa berlaku session belum diperiksa.")
        return 0
    clock = Clock()
    recorder = None
    radar = None
    sniper = None
    if args.sniper:
        args.radar = True
        from .sniper import SniperManager
        def _print_sniper_event(message, slot):
            logger.lifecycle(message)
        sniper_config = build_sniper_config(args)
        sniper = SniperManager(config=sniper_config, on_event=_print_sniper_event)
        hybrid_msg = " [MODE HYBRID: Scalp TP + Trailing Runner]" if args.hybrid else ""
        price_msg = f" (Min Price: Rp {args.min_price:.0f})" if args.min_price > 0 else ""
        strategy_msg = "Watchlist Pullback L2" if args.orderbook_exit_mode == "full" else "observasi 10s -> TP/CL"
        logger.lifecycle(f"Sniper Manager AKTIF: kapasitas {args.sniper_slots} slot taktis{hybrid_msg}{price_msg} ({strategy_msg}).")
    if args.radar:
        from .radar import MarketRadar, RadarConfig
        def _print_radar_alert(alert):
            logger.lifecycle(alert.format_banner())
        radar = MarketRadar(
            config=RadarConfig(breakout_min_delta_pct=args.min_delta_pct),
            on_alert=_print_radar_alert,
        )
        logger.lifecycle(
            f"Market Radar AKTIF: memindai anomali Breakout, Squeeze, & Absorption secara real-time "
            f"(Breakout min delta {args.min_delta_pct:.2f}%)."
        )
    try:
        dashboard = Dashboard(symbol, logger, clock=clock, stale_after=args.stale_after, radar=radar, sniper=sniper)
        sidecar_manager = None
        if symbol == "*" and sniper is not None:
            from .sidecar import L2SidecarManager
            sidecar_manager = L2SidecarManager(
                base_frames=frames,
                on_book=dashboard.on_sidecar_book,
                logger=logger,
                reconnect=True,
            )
            sniper.on_slot_assigned = sidecar_manager.subscribe_symbol
            sniper.on_slot_released = sidecar_manager.unsubscribe_symbol
            logger.lifecycle("Dynamic L2 Order Book Sidecar AKTIF: slot sniper otomatis streaming Level 2 depth.")
        if args.record:
            recorder = PostgresRecorder(symbol, dashboard.started_at, args.stale_after)
            dashboard.recorder = recorder
            logger.lifecycle(f"Recording session: {recorder.session_id} (hanya event 'book' & 'done' disimpan)")
    except RecordingError as error:
        logger.error(str(error))
        return 1
    result = 0
    status = "COMPLETED"
    try:
        dashboard.on_connection("CONNECTING")
        dashboard.render()
        logger.lifecycle("Connecting...")
        asyncio.run(
            _run(
                dashboard=dashboard,
                sidecar_manager=sidecar_manager,
                frames=subscription["frames"],
                logger=logger,
                on_binary=dashboard.on_binary,
                on_text=dashboard.on_text,
                on_connection=dashboard.on_connection,
                duration=args.duration,
            )
        )
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.lifecycle("Dihentikan; koneksi ditutup.")
        status = "STOPPED"
    except (TransportError, RecordingError) as error:
        logger.error(str(error))
        result = 1
        status = "ERROR"
    finally:
        if sidecar_manager is not None:
            sidecar_manager.close_all()
        try:
            dashboard.accept("connection", {"state": "DISCONNECTED"}, record=not dashboard.recording_failed)
        except RecordingError as error:
            logger.error(str(error))
            result = 1
            status = "ERROR"
            dashboard.accept("connection", {"state": "DISCONNECTED"}, record=False)
        dashboard.finished = clock.now(), dashboard.elapsed()
        if recorder is not None:
            try:
                recorder.close(*dashboard.finished, status)
            except RecordingError as error:
                logger.error(str(error))
                result = 1
        dashboard.render()
        dashboard.summary()
        if sniper is not None and sniper.history:
            from pathlib import Path
            from .sniper import format_sniper_report
            sid = recorder.session_id if recorder is not None else "live"
            scan_res = {
                "session_id": sid,
                "session_symbol": symbol,
                "started_at": dashboard.started_at,
                "ended_at": dashboard.finished[0],
                "total_radar_alerts": len(radar.alerts) if radar else 0,
                "history": sniper.history,
                "sniper_config": sniper.config,
            }
            report_text = format_sniper_report(scan_res)
            out_path = Path("reports") / f"sniper_{sid[:8]}.md"
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(report_text, encoding="utf-8")
            logger.lifecycle(f"📊 Laporan Performa Sniper tersimpan ke: {out_path.resolve()}")
    return result
