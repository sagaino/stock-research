"""Order-book snapshots, preserving the captured JavaScript feed semantics."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import math
import re


_SYMBOL = re.compile(r"[A-Z0-9._-]{1,20}", re.ASCII)
_PRICE = re.compile(r"[0-9]+(?:\.[0-9]+)?", re.ASCII)
_INTEGER = re.compile(r"[0-9]+", re.ASCII)
_MAX_SAFE_INTEGER = (1 << 53) - 1


def format_number(value, maximum_fraction_digits=2, *, grouping=True):
    """Format feed numbers like Intl.NumberFormat('en-US')."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return ""
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    try:
        number = Decimal(str(value))
        with localcontext() as context:
            context.prec = max(28, number.adjusted() + maximum_fraction_digits + 4)
            rounded = number.quantize(
                Decimal(1).scaleb(-maximum_fraction_digits), rounding=ROUND_HALF_UP
            )
        formatted = format(rounded, f",.{maximum_fraction_digits}f" if grouping else f".{maximum_fraction_digits}f")
    except (InvalidOperation, ValueError, OverflowError):
        return ""
    return formatted.rstrip("0").rstrip(".") if maximum_fraction_digits else formatted


def parse_order_book_payload(payload):
    if not isinstance(payload, str) or len(payload) > 5 * 1024 * 1024 or not payload.startswith("#O|"):
        return None
    parts = payload.split("|")
    if len(parts) < 3:
        return None
    message_type, symbol, side = parts[:3]
    if message_type != "#O" or not _SYMBOL.fullmatch(symbol) or side not in ("BID", "OFFER"):
        return None

    levels = []
    for raw_level in parts[3:]:
        values = raw_level.split(";")
        if len(values) != 3 or not _PRICE.fullmatch(values[0]) or not all(_INTEGER.fullmatch(value) for value in values[1:]):
            continue
        try:
            price = float(values[0])
            frequency, shares = int(values[1]), int(values[2])
        except (ValueError, OverflowError):
            continue
        if not math.isfinite(price) or frequency > _MAX_SAFE_INTEGER or shares > _MAX_SAFE_INTEGER:
            continue
        levels.append({"price": price, "frequency": frequency, "shares": shares, "lot": shares / 100})
    return {"type": message_type, "symbol": symbol, "side": side, "levels": levels}


def update_order_book(books, message, now=None):
    if not isinstance(books, dict):
        raise TypeError("books must be a dict")
    if not isinstance(message, dict) or message.get("side") not in ("BID", "OFFER") or not isinstance(message.get("symbol"), str) or not isinstance(message.get("levels"), list):
        raise TypeError("Invalid order-book message")
    if now is None:
        now = datetime.now(timezone.utc)
    if not isinstance(now, datetime):
        raise TypeError("now must be a datetime")
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
    current = books.get(message["symbol"], {"bid": [], "offer": [], "updatedAt": None})
    updated = {
        "bid": message["levels"] if message["side"] == "BID" else current["bid"],
        "offer": message["levels"] if message["side"] == "OFFER" else current["offer"],
        "updatedAt": now,
    }
    books[message["symbol"]] = updated
    return updated


def build_order_book_rows(book):
    if not isinstance(book, dict):
        return []
    bids = book.get("bid") if isinstance(book.get("bid"), list) else []
    offers = book.get("offer") if isinstance(book.get("offer"), list) else []
    rows = []
    for index in range(max(len(bids), len(offers))):
        bid = bids[index] if index < len(bids) and isinstance(bids[index], dict) else {}
        offer = offers[index] if index < len(offers) and isinstance(offers[index], dict) else {}
        rows.append({
            "Bid Freq": bid.get("frequency", ""),
            "Bid Lot": format_number(bid.get("lot")),
            "Bid": bid.get("price", ""),
            "Offer": offer.get("price", ""),
            "Offer Lot": format_number(offer.get("lot")),
            "Offer Freq": offer.get("frequency", ""),
        })
    return rows
