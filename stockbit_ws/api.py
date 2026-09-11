"""Read-only REST API for Stockbit recorded sessions and market events."""

from __future__ import annotations

import argparse
from collections.abc import Generator
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
import os
import sys
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
import psycopg
import uvicorn

from .events import timestamp_text
from .postgres import connect_database, verify_schema
from .recording import RecordingError


@contextmanager
def get_db_connection() -> Generator[psycopg.Connection, None, None]:
    """Provide a read-only database connection, ensuring it is closed after use."""
    conn = None
    try:
        conn = connect_database(readonly=True)
        verify_schema(conn)
        yield conn
    except RecordingError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Database tidak dapat dihubungi atau schema belum siap: {exc}",
        ) from None
    finally:
        if conn is not None and not conn.closed:
            conn.close()


def db_dependency() -> Generator[psycopg.Connection, None, None]:
    with get_db_connection() as conn:
        yield conn


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Verify database connection on startup (read-only verification)
    try:
        with get_db_connection():
            pass
    except HTTPException:
        # Allow starting even if DB is currently down, requests will report 503
        pass
    yield


app = FastAPI(
    title="Stockbit WebSocket Session API",
    description="Read-only REST API untuk membaca riwayat sesi dan event pasar Stockbit WebSocket.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["GET"],
    allow_headers=["*"],
)


def _format_datetime(val: Any) -> str | None:
    if val is None:
        return None
    if isinstance(val, datetime):
        return timestamp_text(val)
    return str(val)


@app.get("/", tags=["Info"])
def root():
    return {
        "name": "Stockbit WebSocket Market Data API",
        "version": "0.1.0",
        "status": "online",
        "endpoints": {
            "health": "/health",
            "sessions": "/api/sessions",
            "session_detail": "/api/sessions/{session_id}",
            "session_events": "/api/sessions/{session_id}/events",
            "docs": "/docs",
        },
    }


@app.get("/health", tags=["Health"])
def health_check(conn: psycopg.Connection = Depends(db_dependency)):
    try:
        row = conn.execute("SELECT 1 AS ok").fetchone()
        if row and row.get("ok") == 1:
            return {"status": "ok", "database": "connected", "mode": "read-only"}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Database check failed: {exc}") from None
    return {"status": "ok", "database": "connected"}


@app.get("/api/sessions", tags=["Sessions"])
def list_sessions(
    symbol: str | None = Query(None, description="Filter berdasarkan kode saham (contoh: BMRI, PTRO, atau '*')"),
    status: str | None = Query(None, description="Filter status: OPEN, COMPLETED, STOPPED, ERROR"),
    source: str | None = Query(None, description="Filter sumber data: LIVE, SYNTHETIC"),
    limit: int = Query(50, ge=1, le=500, description="Jumlah maksimal sesi yang dikembalikan"),
    offset: int = Query(0, ge=0, description="Offset paginasi"),
    conn: psycopg.Connection = Depends(db_dependency),
):
    """Mendapatkan daftar sesi rekaman, diurutkan dari yang terbaru, disertai jumlah total event."""
    clauses: list[str] = []
    params: list[Any] = []

    if symbol:
        clauses.append("s.symbol = %s")
        params.append(symbol.strip().upper())
    if status:
        clauses.append("s.status = %s")
        params.append(status.strip().upper())
    if source:
        clauses.append("s.source = %s")
        params.append(source.strip().upper())

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    # Count total matching
    count_query = f"SELECT count(*) AS total FROM stockbit_ws.sessions s {where_sql}"
    total_row = conn.execute(count_query, params).fetchone()
    total_count = total_row["total"] if total_row else 0

    # Query sessions with O(1) total_events using lateral max(seq) on B-tree index
    query = f"""
        SELECT s.id,
               s.run_no,
               s.symbol,
               s.started_at,
               s.ended_at,
               s.duration_ms,
               s.stale_after,
               s.status,
               s.source,
               COALESCE(e.total_events, 0) AS total_events,
               e.latest_event_at
        FROM stockbit_ws.sessions s
        LEFT JOIN LATERAL (
            SELECT coalesce(max(seq), 0) AS total_events,
                   max(received_at) AS latest_event_at
            FROM stockbit_ws.events ev
            WHERE ev.session_id = s.id
        ) e ON true
        {where_sql}
        ORDER BY s.run_no DESC
        LIMIT %s OFFSET %s
    """
    rows = conn.execute(query, params + [limit, offset]).fetchall()

    sessions = []
    for r in rows:
        sessions.append({
            "id": r["id"],
            "run_no": r["run_no"],
            "symbol": r["symbol"],
            "started_at": _format_datetime(r["started_at"]),
            "ended_at": _format_datetime(r["ended_at"]),
            "duration_ms": r["duration_ms"],
            "stale_after": r["stale_after"],
            "status": r["status"],
            "source": r["source"],
            "total_events": r["total_events"],
            "latest_event_at": _format_datetime(r["latest_event_at"]),
        })

    return {
        "total": total_count,
        "limit": limit,
        "offset": offset,
        "sessions": sessions,
    }


@app.get("/api/sessions/{session_id}", tags=["Sessions"])
def get_session(
    session_id: str,
    conn: psycopg.Connection = Depends(db_dependency),
):
    """Mendapatkan detail satu sesi, termasuk breakdown jenis event dan rentang waktu penerimaan data."""
    row = conn.execute(
        "SELECT * FROM stockbit_ws.sessions WHERE id = %s",
        (session_id.strip(),),
    ).fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Sesi tidak ditemukan")

    # Aggregate metrics for this session
    agg_query = """
        SELECT count(*) AS total_events,
               min(received_at) AS first_event_at,
               max(received_at) AS latest_event_at
        FROM stockbit_ws.events
        WHERE session_id = %s
    """
    agg = conn.execute(agg_query, (session_id,)).fetchone() or {}

    # Event count by kind
    kinds_query = """
        SELECT kind, count(*) AS count
        FROM stockbit_ws.events
        WHERE session_id = %s
        GROUP BY kind
    """
    kinds_rows = conn.execute(kinds_query, (session_id,)).fetchall()
    kinds_dict = {k["kind"]: k["count"] for k in kinds_rows}

    return {
        "id": row["id"],
        "run_no": row["run_no"],
        "symbol": row["symbol"],
        "started_at": _format_datetime(row["started_at"]),
        "ended_at": _format_datetime(row["ended_at"]),
        "duration_ms": row["duration_ms"],
        "stale_after": row["stale_after"],
        "status": row["status"],
        "source": row["source"],
        "events_summary": {
            "total_events": agg.get("total_events", 0),
            "first_event_at": _format_datetime(agg.get("first_event_at")),
            "latest_event_at": _format_datetime(agg.get("latest_event_at")),
            "by_kind": kinds_dict,
        },
    }


@app.get("/api/sessions/{session_id}/events", tags=["Events"])
def get_session_events(
    session_id: str,
    seq_gt: int = Query(0, ge=0, description="Hanya ambil event dengan seq lebih besar dari nilai ini"),
    limit: int = Query(100, ge=1, le=500, description="Maksimal event per batch"),
    kind: str | None = Query(None, description="Filter jenis event: connection, message, book, done"),
    conn: psycopg.Connection = Depends(db_dependency),
):
    """Membaca stream event yang tersimpan dalam satu sesi secara terpaginasi."""
    # Ensure session exists
    session = conn.execute("SELECT id, symbol FROM stockbit_ws.sessions WHERE id = %s", (session_id,)).fetchone()
    if not session:
        raise HTTPException(status_code=404, detail="Sesi tidak ditemukan")

    clauses = ["session_id = %s", "seq > %s"]
    params: list[Any] = [session_id, seq_gt]

    if kind:
        clauses.append("kind = %s")
        params.append(kind.strip().lower())

    params.append(limit)

    query = f"""
        SELECT seq, received_at, elapsed_ms, kind, payload
        FROM stockbit_ws.events
        WHERE {' AND '.join(clauses)}
        ORDER BY seq ASC
        LIMIT %s
    """
    rows = conn.execute(query, params).fetchall()

    events = []
    max_seq = seq_gt
    for r in rows:
        events.append({
            "seq": r["seq"],
            "received_at": _format_datetime(r["received_at"]),
            "elapsed_ms": r["elapsed_ms"],
            "kind": r["kind"],
            "payload": r["payload"],
        })
        if r["seq"] > max_seq:
            max_seq = r["seq"]

    return {
        "session_id": session_id,
        "symbol": session["symbol"],
        "count": len(events),
        "next_seq": max_seq,
        "events": events,
    }


@app.get("/api/sessions/{session_id}/report", tags=["Reports"])
def get_session_report(
    session_id: str,
    conn: psycopg.Connection = Depends(db_dependency),
):
    """Mendapatkan laporan audit kualitas rekaman dan analisis deskriptif pasar (JSON & Markdown)."""
    from .report import (
        analyze_session_uniqueness,
        compute_market_descriptive,
        generate_full_report,
        measure_recorder_performance,
    )

    row = conn.execute("SELECT * FROM stockbit_ws.sessions WHERE id = %s", (session_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Sesi tidak ditemukan")

    try:
        uniqueness = analyze_session_uniqueness(conn, session_id)
        perf = measure_recorder_performance(conn, session_id)
        market = compute_market_descriptive(conn, session_id, row["symbol"])
        markdown = generate_full_report(session_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal membuat laporan: {exc}") from None

    return {
        "session_id": session_id,
        "symbol": row["symbol"],
        "status": row["status"],
        "source": row["source"],
        "uniqueness": uniqueness,
        "recorder_performance": perf,
        "market_descriptive": market,
        "markdown_report": markdown,
    }


@app.get("/api/sessions/{session_id}/intervals", tags=["Analysis"])
def get_session_intervals(
    session_id: str,
    interval: int = Query(5, ge=1, le=300, description="Ukuran interval detik (contoh: 1, 5, 30)"),
    symbol: str | None = Query(None, description="Filter kode saham (wajib jika sesi wildcard *)"),
    conn: psycopg.Connection = Depends(db_dependency),
):
    """Mendapatkan data time-series bar per interval (OHLC, volume/value, HAKA/HAKI net flow, spread, imbalance)."""
    from .intervals import build_interval_bars, extract_activity_patterns, load_session_trades_and_books

    row = conn.execute("SELECT * FROM stockbit_ws.sessions WHERE id = %s", (session_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Sesi tidak ditemukan")

    try:
        data = load_session_trades_and_books(conn, session_id, symbol)
        bars = build_interval_bars(
            data["live_trades"], data["book_updates"], interval,
            start_time=data["started_at"], end_time=data["ended_at"],
            stale_after=data["session"]["stale_after"],
        )
        patterns = extract_activity_patterns(bars)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal memproses interval: {exc}") from None

    return {
        "session_id": session_id,
        "symbol": data["target_symbol"],
        "interval_seconds": interval,
        "total_bars": len(bars),
        "snapshot_trades_count": len(data["snapshot_trades"]),
        "live_trades_count": len(data["live_trades"]),
        "patterns": patterns,
        "bars": bars,
    }


@app.get("/api/sessions/{session_id}/radar", tags=["Analysis"])
def get_session_radar_anomalies(
    session_id: str,
    conn: psycopg.Connection = Depends(db_dependency),
):
    """Memindai anomali pasar (Breakout Momentum, Squeeze Blitz, Heavy Absorption) untuk sesi rekaman."""
    from .radar import scan_session_radar, format_radar_report

    row = conn.execute("SELECT * FROM stockbit_ws.sessions WHERE id = %s", (session_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Sesi tidak ditemukan")

    try:
        scan_res = scan_session_radar(session_id, conn=conn)
        markdown_report = format_radar_report(scan_res)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Gagal memindai radar anomali: {exc}") from None

    return {
        "session_id": session_id,
        "symbol": row["symbol"],
        "total_alerts": scan_res["total_alerts"],
        "alerts": scan_res["alerts"],
        "markdown_report": markdown_report,
    }




def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Stockbit WebSocket Session & Event REST API Server")
    parser.add_argument(
        "--host",
        default=os.environ.get("API_HOST", "127.0.0.1"),
        help="Host binding (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("API_PORT", os.environ.get("PORT", "8000"))),
        help="Port binding (default: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="Enable auto-reload for development",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    print(f"Memulai Stockbit WS REST API di http://{args.host}:{args.port} (Docs: http://{args.host}:{args.port}/docs)")
    uvicorn.run(
        "stockbit_ws.api:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
