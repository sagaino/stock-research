"""Validation and serialization for recorded market events."""

import json
import uuid

from .events import normalize_event, number, timestamp_text, utc_time
from .subscription import SYMBOL_PATTERN

APPLICATION_ID = 0x53425753
MAX_JSON_BYTES = 10 * 1024 * 1024


class RecordingError(RuntimeError):
    """Only fixed messages; database errors may contain private contents."""



def serialize_event(kind, payload, symbol, received_at, elapsed, last_elapsed):
    safe = normalize_event(kind, payload, symbol)
    encoded = json.dumps(safe, allow_nan=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("Oversized event")
    elapsed_ms = round(number(elapsed, minimum=0) * 1000)
    if elapsed_ms < last_elapsed:
        raise ValueError("Clock moved backwards")
    return encoded, timestamp_text(received_at), elapsed_ms, safe


def validate_session(row):
    if row is None:
        raise ValueError("Missing session")
    result = dict(row)
    if uuid.UUID(hex=result["id"]).hex != result["id"]:
        raise ValueError("Invalid session id")
    if (result["symbol"] != "*" and not SYMBOL_PATTERN.fullmatch(result["symbol"])) or result["status"] not in ("OPEN", "COMPLETED", "STOPPED", "ERROR"):
        raise ValueError("Invalid session")
    if result["source"] not in ("LIVE", "SYNTHETIC"):
        raise ValueError("Invalid source")
    result["started_at"] = timestamp_text(result["started_at"])
    if result["ended_at"] is not None:
        result["ended_at"] = timestamp_text(result["ended_at"])
        number(result["duration_ms"], integer=True, minimum=0)
    if number(result["stale_after"], minimum=0) == 0:
        raise ValueError("Invalid threshold")
    return result


def deserialize_event(row, symbol, sequence, elapsed):
    payload = row["payload"]
    encoded = payload if isinstance(payload, str) else json.dumps(payload, allow_nan=False)
    if row["seq"] != sequence + 1 or row["elapsed_ms"] < elapsed or len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("Invalid event sequence")
    elapsed_ms = number(row["elapsed_ms"], integer=True, minimum=0)
    return {"seq": row["seq"], "received_at": utc_time(row["received_at"]), "elapsed": elapsed_ms / 1000,
            "kind": row["kind"], "payload": normalize_event(row["kind"], json.loads(encoded), symbol)}
