"""Observed Done record decoder and bounded recent-trade state.

The side-code mapping is inherited from the existing client (1=HAKA/BUY,
2=HAKI/SELL); it remains an inferred feed interpretation, not an official
protocol definition. Unknown sides are ignored. A snapshot alone does not
establish that the feed is complete or that records are newly executed.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, localcontext
import math
import re
import struct

from .orderbook import format_number
from .protobuf import decode_printable_utf8, normalize_incoming_buffer, parse_protobuf


_SYMBOL = re.compile(r"[A-Z][A-Z0-9._-]{1,19}", re.ASCII)
_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)
_WIB = timezone(timedelta(hours=7), "WIB")


def _field(fields, number, wire_type):
    return next((field for field in fields if field["fieldNumber"] == number and field["wireType"] == wire_type), None)


def _varint(fields, number):
    field = _field(fields, number, 0)
    return field["value"] if field else None


def _double(fields, number):
    field = _field(fields, number, 1)
    if field is None:
        return None
    try:
        return struct.unpack("<d", field["value"])[0]
    except (TypeError, ValueError, struct.error):
        return None


def _finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def parse_timestamp(buffer):
    try:
        fields = parse_protobuf(buffer, strict=True)
        seconds = _varint(fields, 1)
        nanos = _varint(fields, 2)
        nanos = 0 if nanos is None else nanos
        if not isinstance(seconds, int) or not isinstance(nanos, int) or nanos < 0 or nanos >= 1_000_000_000:
            return None
        # Preserve the original JS Date's millisecond precision without a
        # floating-point epoch conversion, which can round into the next ms.
        return _EPOCH + timedelta(seconds=seconds, milliseconds=nanos // 1_000_000)
    except (TypeError, ValueError, OverflowError):
        return None


def _parse_change(buffer):
    try:
        fields = parse_protobuf(buffer, strict=True)
        points, percent = _double(fields, 1), _double(fields, 2)
        return {"points": points if _finite(points) else None, "percent": percent if _finite(percent) else None}
    except (TypeError, ValueError, OverflowError):
        return {"points": None, "percent": None}


def parse_done_trade_record(buffer):
    try:
        fields = parse_protobuf(buffer, strict=True)
        primary = _field(fields, 1, 2)
        secondary = _field(fields, 7, 2)
        change_field = _field(fields, 8, 2)
        symbol_field = _field(fields, 2, 2)
        symbol = decode_printable_utf8(symbol_field["value"]) if symbol_field else None
        price, shares = _double(fields, 3), _double(fields, 4)
        side_code = _varint(fields, 5)
        if primary is None or not isinstance(symbol, str) or not _SYMBOL.fullmatch(symbol) or not _finite(price) or price <= 0 or not _finite(shares) or shares <= 0 or side_code not in (1, 2):
            return None
        timestamp = parse_timestamp(primary["value"])
        if timestamp is None:
            return None
        change = _parse_change(change_field["value"]) if change_field else {"points": None, "percent": None}
        transaction_value = _double(fields, 11)
        return {
            "symbol": symbol,
            "timestamp": timestamp,
            "secondaryTimestamp": parse_timestamp(secondary["value"]) if secondary else None,
            "price": price,
            "shares": shares,
            "lot": shares / 100,
            "sideCode": side_code,
            "side": "BUY" if side_code == 1 else "SELL",
            "aggressor": "HAKA" if side_code == 1 else "HAKI",
            "changePoints": change["points"],
            "changePercent": change["percent"],
            "tradeId": _varint(fields, 9),
            "flag": _varint(fields, 10),
            "transactionValue": transaction_value if _finite(transaction_value) else price * shares,
        }
    except (TypeError, ValueError, OverflowError):
        return None


def find_done_trade_batch(input):
    """Collect valid records from all outer field-8 batches in one message.

    This extends the JS decoder, which returned only the first valid batch;
    single-batch captures produce the same records in the same order.
    """
    try:
        fields = parse_protobuf(normalize_incoming_buffer(input), strict=True)
    except (TypeError, ValueError, OverflowError):
        return None
    trades = []
    for outer in fields:
        if outer["fieldNumber"] != 8 or outer["wireType"] != 2:
            continue
        try:
            batch = parse_protobuf(outer["value"], strict=True)
        except (TypeError, ValueError, OverflowError):
            continue
        for record in batch:
            if record["fieldNumber"] == 1 and record["wireType"] == 2:
                trade = parse_done_trade_record(record["value"])
                if trade is not None:
                    trades.append(trade)
    return trades or None


def create_recent_trade_state():
    return {"trades": [], "seenKeys": set()}


def _trade_key(trade):
    if trade.get("tradeId") is not None:
        return (trade["symbol"], trade["tradeId"])
    return (trade["symbol"], trade["timestamp"], trade["price"], trade["shares"], trade["sideCode"])


def _valid_trade(trade):
    return (
        isinstance(trade, dict)
        and isinstance(trade.get("symbol"), str)
        and isinstance(trade.get("timestamp"), datetime)
        and trade["timestamp"].tzinfo is not None
        and _finite(trade.get("price"))
        and _finite(trade.get("shares"))
        and trade.get("sideCode") in (1, 2)
        and (trade.get("tradeId") is None or isinstance(trade["tradeId"], int))
    )


def update_recent_trades(state, incoming, max_trades=100):
    if not isinstance(state, dict) or not isinstance(state.get("trades"), list) or not isinstance(state.get("seenKeys"), set):
        raise TypeError("Invalid recent-trade state")
    if isinstance(max_trades, bool) or not isinstance(max_trades, int) or max_trades < 0:
        raise ValueError("max_trades must be a non-negative integer")
    for trade in incoming or ():
        if not _valid_trade(trade):
            continue
        key = _trade_key(trade)
        if key not in state["seenKeys"]:
            state["seenKeys"].add(key)
            state["trades"].append(trade)
    # Python integers preserve the ordering of IDs above JavaScript's safe
    # integer range, including records sharing the same millisecond.
    state["trades"].sort(key=lambda trade: (trade["timestamp"], trade.get("tradeId") or 0), reverse=True)
    state["trades"] = state["trades"][:max_trades]
    state["seenKeys"] = {_trade_key(trade) for trade in state["trades"]}
    return state["trades"]


def _format_signed(value, fraction_digits=2):
    if not _finite(value):
        return ""
    # Number.prototype.toFixed renders an actual -0 as 0, while a negative
    # nonzero value that rounds to zero still retains its minus sign.
    number = Decimal(0) if value == 0 else (Decimal.from_float(value) if isinstance(value, float) else Decimal(value))
    with localcontext() as context:
        context.prec = max(28, number.adjusted() + fraction_digits + 4)
        rounded = number.quantize(Decimal(1).scaleb(-fraction_digits), rounding=ROUND_HALF_UP)
    return ("+" if value > 0 else "") + format(rounded, f".{fraction_digits}f")


def build_recent_trade_rows(trades, limit=20, *, include_code=False):
    if not isinstance(limit, int) or isinstance(limit, bool) or limit < 0:
        raise ValueError("limit must be a non-negative integer")
    rows = []
    for trade in (trades or [])[:limit]:
        if not _valid_trade(trade):
            continue
        local = trade["timestamp"].astimezone(_WIB)
        percent = trade.get("changePercent")
        rows.append({
            "Time": local.strftime("%H:%M:%S.") + f"{local.microsecond // 1000:03d}",
            "Price": trade["price"],
            "Lot": format_number(trade.get("lot", trade["shares"] / 100)),
            "Side": f"{trade.get('aggressor', '')}/{trade.get('side', '')}",
            "Change": "" if percent is None else f"{_format_signed(trade.get('changePoints'), 0)} ({_format_signed(percent)}%)",
            "Value": "Rp" + format_number(trade.get("transactionValue"), 0).replace(",", "."),
            "Trade ID": "" if trade.get("tradeId") is None else str(trade["tradeId"]),
        })
        if include_code:
            rows[-1]["Code"] = trade["symbol"]
    return rows
