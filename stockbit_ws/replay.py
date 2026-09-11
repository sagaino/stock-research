"""Replay decoded events; PostgreSQL, never Stockbit networking."""

import asyncio
from datetime import timedelta

from .events import utc_time
from .recording import RecordingError
from .postgres import PostgresReader


class ReplayClock:
    def __init__(self, started_at):
        self.current = utc_time(started_at)
        self.elapsed = 0.0

    def now(self):
        return self.current

    def monotonic(self):
        return self.elapsed

    def set(self, stamp, elapsed):
        self.current = utc_time(stamp)
        self.elapsed = elapsed

    def advance(self, seconds):
        self.current += timedelta(seconds=seconds)
        self.elapsed += seconds


async def replay_session(reader, session, dashboard, *, speed=0):
    if dashboard.symbol != session["symbol"]:
        raise RecordingError("Symbol replay harus sama dengan symbol sesi rekaman.")

    async def wait_until(elapsed):
        while speed > 0 and elapsed - dashboard.clock.monotonic() > 0.000001:
            advance = min(elapsed - dashboard.clock.monotonic(), speed)
            await asyncio.sleep(advance / speed)
            dashboard.clock.advance(advance)
            dashboard.tick()

    count = 0
    for event in reader.events(session):
        await wait_until(event["elapsed"])
        dashboard.clock.set(event["received_at"], event["elapsed"])
        dashboard.accept(event["kind"], event["payload"], received_at=event["received_at"], elapsed=event["elapsed"], record=False)
        if speed > 0 and dashboard.dirty and dashboard.clock.monotonic() - dashboard.last_render >= 0.25:
            dashboard.render()
        count += 1
        if count % 100 == 0:
            await asyncio.sleep(0)  # Keep Ctrl+C responsive during fast replay.
    if session["ended_at"] is not None:
        elapsed = session["duration_ms"] / 1000
        if elapsed < dashboard.clock.monotonic():
            raise RecordingError("Durasi sesi lebih pendek daripada event terakhir.")
        await wait_until(elapsed)
        dashboard.clock.set(session["ended_at"], elapsed)
    dashboard.render()
    return count


def replay_main(args, logger):
    from .cli import Dashboard, build_sniper_config

    reader = None
    try:
        reader = PostgresReader()
        if args.sessions:
            for row in reader.sessions():
                session = reader.select_session(row["id"])
                logger.lifecycle(f"{session['id']}  {session['symbol']}  {session['started_at']}  {session['status']}  {session['source']}")
            return 0
        session = reader.select_session(args.session)
        if args.all and session["symbol"] != "*":
            raise RecordingError("Sesi ini bukan Running Trade semua saham.")
        if args.symbol is not None and args.symbol.strip().upper() != session["symbol"]:
            raise RecordingError("Symbol argumen berbeda dari sesi; pilih sesi yang sesuai.")
        logger.lifecycle(f"REPLAY POSTGRES (tanpa Stockbit): {session['id']} | {session['symbol']} | {session['status']} | {session['source']} | quality memakai waktu rekaman, bukan waktu sekarang")
        if session["status"] in ("OPEN", "ERROR"):
            logger.lifecycle("Peringatan: sesi tidak selesai normal; hanya event yang tersimpan dapat direplay.")
        sniper = None
        if getattr(args, "sniper", False):
            args.radar = True
            from .sniper import SniperManager

            def _print_sniper_event(message, slot):
                logger.lifecycle(message)

            sniper_config = build_sniper_config(args)
            sniper = SniperManager(config=sniper_config, on_event=_print_sniper_event)
            logger.lifecycle(f"Sniper Manager AKTIF saat replay: kapasitas {sniper_config.max_slots} slot, konfigurasi sama dengan live.")

        radar = None
        if getattr(args, "radar", False):
            from .radar import MarketRadar, RadarConfig

            def _print_radar_alert(alert):
                logger.lifecycle(alert.format_banner())

            radar = MarketRadar(
                config=RadarConfig(breakout_min_delta_pct=args.min_delta_pct),
                on_alert=_print_radar_alert,
                start_time=utc_time(session["started_at"]),
                end_time=utc_time(session["ended_at"]) if session["ended_at"] else None,
            )
            logger.lifecycle(
                f"Market Radar AKTIF saat replay: memindai anomali Breakout & Squeeze "
                f"(Breakout min delta {args.min_delta_pct:.2f}%)."
            )

        clock = ReplayClock(session["started_at"])
        dashboard = Dashboard(session["symbol"], logger, clock=clock, stale_after=session["stale_after"], radar=radar, sniper=sniper)
        count = asyncio.run(replay_session(reader, session, dashboard, speed=args.speed))
        if sniper is not None:
            sniper.close_all(clock.now())
        logger.lifecycle(f"Replay selesai: {count} event. Replay decoder-output, bukan pengujian ulang wire decoder.")
        dashboard.summary()
        return 0
    except RecordingError as error:
        logger.error(str(error))
        return 1
    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.lifecycle("Replay dihentikan.")
        return 130
    finally:
        if reader is not None:
            reader.close()
