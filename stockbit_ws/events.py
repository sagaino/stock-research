"""Versioned, allowlisted market events. Never persist raw wire or credentials."""

from datetime import datetime, timezone
import math

from .subscription import SYMBOL_PATTERN

EVENT_VERSION = 1
MAX_ITEMS = 10_000
CONNECTION_STATES = {"CONNECTING", "CONNECTED", "DISCONNECTED"}


def utc_time(value):
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("Timestamp event harus memiliki timezone.")
    return value.astimezone(timezone.utc)


def timestamp_text(value):
    return utc_time(value).isoformat(timespec="milliseconds")


def number(value, *, minimum=None, integer=False, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid event number")
    if integer and (not isinstance(value, int) or value > (1 << 64) - 1):
        raise ValueError("Invalid event integer")
    if not math.isfinite(value) or (minimum is not None and value < minimum):
        raise ValueError("Invalid event number")
    return value


def normalize_event(kind, payload, symbol):
    """Drop all unknown keys, validate values, derive labels from numeric side.

    This runs both before writing and when reading an untrusted recording.
    A replay never executes pickle, SQL from a file, or raw protobuf captures.
    """
    if not isinstance(symbol, str) or (symbol != "*" and not SYMBOL_PATTERN.fullmatch(symbol)) or not isinstance(payload, dict):
        raise ValueError("Invalid event")
    if kind == "connection":
        state = payload.get("state")
        if state not in CONNECTION_STATES:
            raise ValueError("Invalid connection state")
        return {"state": state}
    if kind == "message":
        form = payload.get("format")
        if form not in ("binary", "text"):
            raise ValueError("Invalid message type")
        return {"format": form, "size": number(payload.get("size"), integer=True, minimum=0)}
    if kind == "book":
        book_sym = payload.get("symbol")
        if (
            not isinstance(book_sym, str)
            or not SYMBOL_PATTERN.fullmatch(book_sym)
            or (symbol != "*" and book_sym != symbol)
            or payload.get("side") not in ("BID", "OFFER")
        ):
            raise ValueError("Invalid book event")
        levels = payload.get("levels")
        if not isinstance(levels, list) or len(levels) > MAX_ITEMS:
            raise ValueError("Invalid book levels")
        result = []
        for level in levels:
            price = number(level.get("price"), minimum=0)
            shares = number(level.get("shares"), integer=True, minimum=0)
            frequency = number(level.get("frequency"), integer=True, minimum=0)
            result.append({"price": price, "shares": shares, "frequency": frequency, "lot": shares / 100})
        return {"type": "#O", "symbol": book_sym, "side": payload["side"], "levels": result}
    if kind != "done":
        raise ValueError("Unknown event type")
    trades = payload.get("trades")
    if not isinstance(trades, list) or not trades or len(trades) > MAX_ITEMS:
        raise ValueError("Invalid Done batch")
    result = []
    for trade in trades:
        code = trade.get("symbol")
        if not isinstance(code, str) or not SYMBOL_PATTERN.fullmatch(code) or (symbol != "*" and code != symbol) or type(trade.get("sideCode")) is not int or trade["sideCode"] not in (1, 2):
            raise ValueError("Invalid Done symbol/side")
        price = number(trade.get("price"), minimum=0)
        shares = number(trade.get("shares"), minimum=0)
        if price == 0 or shares == 0:
            raise ValueError("Invalid Done quantity")
        buy = trade["sideCode"] == 1
        result.append({
            "symbol": code, "timestamp": timestamp_text(trade["timestamp"]),
            "secondaryTimestamp": timestamp_text(trade["secondaryTimestamp"]) if trade.get("secondaryTimestamp") is not None else None,
            "price": price, "shares": shares, "lot": shares / 100,
            "sideCode": trade["sideCode"], "side": "BUY" if buy else "SELL", "aggressor": "HAKA" if buy else "HAKI",
            "tradeId": number(trade.get("tradeId"), integer=True, minimum=0, optional=True),
            "flag": number(trade.get("flag"), integer=True, minimum=0, optional=True),
            "changePoints": number(trade.get("changePoints"), optional=True),
            "changePercent": number(trade.get("changePercent"), optional=True),
            "transactionValue": number(trade.get("transactionValue", price * shares), minimum=0),
        })
    # Snapshot versus incremental batch cannot be established from this schema.
    return {"trades": result, "batchKind": "unknown"}


def decoded_trades(payload):
    result = []
    for item in payload["trades"]:
        trade = dict(item)
        trade["timestamp"] = utc_time(trade["timestamp"])
        trade["secondaryTimestamp"] = utc_time(trade["secondaryTimestamp"]) if trade["secondaryTimestamp"] else None
        result.append(trade)
    return result
