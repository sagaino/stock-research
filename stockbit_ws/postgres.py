"""Append-only PostgreSQL journal and read-only replay access."""

import uuid

import psycopg
from psycopg.rows import dict_row

from .config import ConfigurationError, load_environment
from .events import EVENT_VERSION, number, timestamp_text
from .recording import APPLICATION_ID, RecordingError, deserialize_event, serialize_event, validate_session
from .subscription import SYMBOL_PATTERN


def connect_database(*, readonly=False):
    try:
        # Separate from Stockbit .env. Passwords never enter a CLI argument/URL.
        values = load_environment(".env.postgres")
        port = int(values.get("PG_PORT", "5433"))
        if not 1 <= port <= 65535:
            raise ValueError("Invalid port")
        options = "-c statement_timeout=10000 -c lock_timeout=2000"
        if readonly:
            options += " -c default_transaction_read_only=on"
        return psycopg.connect(
            host=values.get("PG_HOST", "127.0.0.1"), port=port,
            user=values.get("PG_USER", "stockbit"), password=values.get("PG_PASSWORD", "stockbit_local"),
            dbname=values.get("PG_DATABASE", "stockbit_ws"), connect_timeout=5,
            autocommit=True, row_factory=dict_row, options=options,
        )
    except (psycopg.Error, ConfigurationError, ValueError, TypeError):
        raise RecordingError("PostgreSQL tidak dapat dihubungi. Periksa Docker dan konfigurasi .env.postgres/PG_*.") from None


def verify_schema(connection):
    row = connection.execute("SELECT version FROM stockbit_ws.meta WHERE singleton=true").fetchone()
    if row is None or row["version"] != EVENT_VERSION:
        raise RecordingError("Versi schema rekaman PostgreSQL tidak didukung.")


def initialize_schema(connection):
    with connection.transaction():
        # Serialize first-time DDL when two clients start at the same time.
        connection.execute("SELECT pg_advisory_xact_lock(%s)", (APPLICATION_ID,))
        connection.execute("CREATE SCHEMA IF NOT EXISTS stockbit_ws")
        connection.execute("CREATE TABLE IF NOT EXISTS stockbit_ws.meta (singleton boolean PRIMARY KEY CHECK(singleton), version integer NOT NULL)")
        connection.execute("INSERT INTO stockbit_ws.meta VALUES (true, %s) ON CONFLICT DO NOTHING", (EVENT_VERSION,))
        verify_schema(connection)
        connection.execute("""CREATE TABLE IF NOT EXISTS stockbit_ws.sessions (
            id text PRIMARY KEY CHECK(id ~ '^[0-9a-f]{32}$'),
            run_no bigint GENERATED ALWAYS AS IDENTITY UNIQUE,
            symbol text NOT NULL, started_at timestamptz NOT NULL,
            ended_at timestamptz, duration_ms bigint CHECK(duration_ms >= 0),
            stale_after double precision NOT NULL CHECK(stale_after > 0),
            status text NOT NULL CHECK(status IN ('OPEN','COMPLETED','STOPPED','ERROR')),
            source text NOT NULL CHECK(source IN ('LIVE','SYNTHETIC'))
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS stockbit_ws.events (
            session_id text NOT NULL REFERENCES stockbit_ws.sessions(id),
            seq bigint NOT NULL CHECK(seq > 0), received_at timestamptz NOT NULL,
            elapsed_ms bigint NOT NULL CHECK(elapsed_ms >= 0),
            kind text NOT NULL CHECK(kind IN ('connection','message','book','done')),
            payload jsonb NOT NULL, PRIMARY KEY(session_id,seq)
        )""")
        connection.execute("""CREATE TABLE IF NOT EXISTS stockbit_ws.trades (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            session_id text NOT NULL REFERENCES stockbit_ws.sessions(id) ON DELETE CASCADE,
            trade_id numeric,
            symbol text NOT NULL,
            price numeric NOT NULL,
            shares numeric NOT NULL,
            lot numeric NOT NULL,
            side text NOT NULL CHECK(side IN ('BUY', 'SELL')),
            aggressor text NOT NULL CHECK(aggressor IN ('HAKA', 'HAKI')),
            trade_timestamp timestamptz NOT NULL,
            received_at timestamptz NOT NULL,
            transaction_value numeric NOT NULL,
            flag integer
        )""")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_trades_sym_ts ON stockbit_ws.trades(symbol, trade_timestamp DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_trades_sess_ts ON stockbit_ws.trades(session_id, trade_timestamp DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS idx_trades_ts ON stockbit_ws.trades(trade_timestamp DESC)")


class PostgresRecorder:
    def __init__(self, symbol, started_at, stale_after=15.0, *, source="LIVE", allowed_kinds=None, only_done=None):
        self.connection = None
        self.session_id = uuid.uuid4().hex
        self.symbol = symbol
        self.source = source
        self.sequence = self.last_elapsed = 0
        self.closed = False
        # Default: LIVE recordings save 'book' and 'done' (dropping 'message' and 'connection' noise);
        # SYNTHETIC test fixtures retain all kinds unless overridden.
        if allowed_kinds is not None:
            self.allowed_kinds = set(allowed_kinds)
        elif only_done is True:
            self.allowed_kinds = {"done"}
        elif source == "LIVE":
            self.allowed_kinds = {"book", "done"}
        else:
            self.allowed_kinds = None
        try:
            if (symbol != "*" and not SYMBOL_PATTERN.fullmatch(symbol)) or source not in ("LIVE", "SYNTHETIC") or number(stale_after, minimum=0) == 0:
                raise ValueError("Invalid session")
            self.connection = connect_database()
            initialize_schema(self.connection)
            self.connection.execute(
                "INSERT INTO stockbit_ws.sessions (id, symbol, started_at, stale_after, status, source) VALUES (%s,%s,%s,%s,'OPEN',%s)",
                (self.session_id, symbol, timestamp_text(started_at), stale_after, source)
            )
        except (psycopg.Error, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            if self.connection is not None:
                try:
                    self.connection.close()
                except Exception:
                    pass
            raise RecordingError("Sesi perekaman PostgreSQL gagal diinisialisasi.") from None

    def _dispose(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def append(self, kind, payload, received_at, elapsed):
        if self.closed:
            raise RecordingError("Sesi rekaman sudah ditutup.")
        # Filter out noise events ('message', 'connection') in live sessions
        if self.allowed_kinds is not None and kind in ("message", "connection") and kind not in self.allowed_kinds:
            return
        if self.allowed_kinds is not None and self.allowed_kinds == {"done"} and kind in ("book", "message", "connection"):
            return
        try:
            encoded, received, elapsed_ms, safe = serialize_event(kind, payload, self.symbol, received_at, elapsed, self.last_elapsed)
            # ponytail: one committed INSERT per event; batch only after measuring I/O.
            self.connection.execute("INSERT INTO stockbit_ws.events VALUES (%s,%s,%s,%s,%s,%s::jsonb)",
                                    (self.session_id, self.sequence + 1, received, elapsed_ms, kind, encoded))
            
            # Normalize trades into stockbit_ws.trades table for instant relational querying
            if kind == "done":
                trades = safe.get("trades", [])
                if trades:
                    trade_rows = [
                        (
                            self.session_id,
                            t.get("tradeId"),
                            t.get("symbol") or self.symbol,
                            t.get("price"),
                            t.get("shares"),
                            t.get("lot"),
                            t.get("side"),
                            t.get("aggressor"),
                            t.get("timestamp"),
                            received,
                            t.get("transactionValue"),
                            t.get("flag"),
                        )
                        for t in trades if t.get("price") is not None
                    ]
                    if trade_rows:
                        self.connection.cursor().executemany(
                            """INSERT INTO stockbit_ws.trades (
                                session_id, trade_id, symbol, price, shares, lot,
                                side, aggressor, trade_timestamp, received_at, transaction_value, flag
                            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                            trade_rows,
                        )
            self.sequence += 1
            self.last_elapsed = elapsed_ms
        except (psycopg.Error, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            raise RecordingError("Perekaman PostgreSQL gagal; sesi dihentikan agar tidak mengklaim rekaman lengkap.") from None

    def close(self, ended_at, elapsed, status="COMPLETED"):
        if self.closed:
            return
        try:
            if status not in ("COMPLETED", "STOPPED", "ERROR"):
                raise ValueError("Invalid status")
            duration = max(self.last_elapsed, round(number(elapsed, minimum=0) * 1000))
            self.connection.execute("UPDATE stockbit_ws.sessions SET ended_at=%s,duration_ms=%s,status=%s WHERE id=%s",
                                    (timestamp_text(ended_at), duration, status, self.session_id))
        except (psycopg.Error, ValueError, TypeError):
            raise RecordingError("Penutupan rekaman PostgreSQL gagal; periksa sesi berstatus OPEN.") from None
        finally:
            self.closed = True
            self._dispose()


class PostgresReader:
    def __init__(self):
        self.connection = None
        try:
            self.connection = connect_database(readonly=True)
            verify_schema(self.connection)
        except (psycopg.Error, RecordingError):
            self.close()
            raise RecordingError("Rekaman PostgreSQL belum tersedia atau tidak dapat dibaca. Periksa Docker, konfigurasi PG_*, dan schema.") from None

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def sessions(self):
        try:
            return list(self.connection.execute("SELECT * FROM stockbit_ws.sessions ORDER BY run_no DESC"))
        except psycopg.Error:
            raise RecordingError("Daftar sesi PostgreSQL tidak dapat dibaca.") from None

    def select_session(self, session_id=None):
        try:
            row = self.connection.execute("SELECT * FROM stockbit_ws.sessions WHERE id=%s", (session_id,)).fetchone() if session_id else self.connection.execute("SELECT * FROM stockbit_ws.sessions ORDER BY run_no DESC LIMIT 1").fetchone()
            return validate_session(row)
        except (psycopg.Error, ValueError, TypeError, KeyError, AttributeError, OverflowError):
            raise RecordingError("Sesi PostgreSQL tidak ditemukan atau metadata tidak valid.") from None

    def events(self, session):
        sequence, elapsed_ms = 0, 0
        try:
            upper = self.connection.execute("SELECT coalesce(max(seq),0) AS seq FROM stockbit_ws.events WHERE session_id=%s", (session["id"],)).fetchone()["seq"]
            # Bounded pages and a fixed upper bound: no long-lived transaction,
            # no loading an entire day's data or chasing an OPEN session forever.
            while sequence < upper:
                rows = self.connection.execute("""SELECT * FROM stockbit_ws.events
                    WHERE session_id=%s AND seq>%s AND seq<=%s ORDER BY seq LIMIT 100""", (session["id"], sequence, upper)).fetchall()
                if not rows:
                    raise ValueError("Missing events")
                for row in rows:
                    event = deserialize_event(row, session["symbol"], sequence, elapsed_ms)
                    sequence, elapsed_ms = row["seq"], row["elapsed_ms"]
                    yield event
        except (psycopg.Error, ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
            raise RecordingError("Event PostgreSQL rusak atau tidak dapat dibaca; replay dihentikan.") from None
