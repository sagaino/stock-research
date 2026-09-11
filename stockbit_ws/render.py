"""Plain terminal output for the order book and recent Done sections."""

from datetime import datetime, timedelta, timezone
import sys
import unicodedata

from .orderbook import build_order_book_rows
from .trades import build_recent_trade_rows


_WIB = timezone(timedelta(hours=7), "WIB")
_BOOK_HEADERS = ("Bid Freq", "Bid Lot", "Bid", "Offer", "Offer Lot", "Offer Freq")
_DONE_HEADERS = ("Time", "Price", "Lot", "Side", "Change", "Value", "Trade ID")


def _safe_text(value):
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    # Feed/user-controlled text must never inject terminal escape sequences,
    # newlines, or bidi formatting into the terminal dashboard.
    return "".join(character if not unicodedata.category(character).startswith("C") else "?" for character in str(value))


def _table(headers, rows):
    cells = [[_safe_text(row.get(header, "")) for header in headers] for row in rows]
    widths = [max(len(header), *(len(row[index]) for row in cells)) if cells else len(header) for index, header in enumerate(headers)]
    separator = "-+-".join("-" * width for width in widths)
    lines = [" | ".join(header.ljust(width) for header, width in zip(headers, widths)), separator]
    lines.extend(" | ".join(value.rjust(width) for value, width in zip(row, widths)) for row in cells)
    if not cells:
        lines.append("(waiting for data)")
    return "\n".join(lines)


def render_dashboard(symbol, book_or_none, trades, *, output=sys.stdout, done_limit=20, clear=False, quality=None, radar_alerts=None, sniper_table=None):
    """Render both sections; an explicit clear only affects a real TTY."""
    all_market = symbol == "*"
    lines = [] if all_market else [f"========== {_safe_text(symbol)} ORDER BOOK =========="]
    if quality is not None:
        def age(key):
            value = quality.get(key)
            return "-" if value is None else f"{value:.1f}s"
        book_age = "" if all_market else f" | BID age {age('bidAgeSeconds')} | OFFER age {age('offerAgeSeconds')}"
        lines.insert(0, f"FEED: {_safe_text(quality['status'])}{book_age} | Done event age {age('doneEventAgeSeconds')}")
        lines.insert(1, "Checks: " + (_safe_text(', '.join(quality['issues'])) or "recent data observed; completeness UNKNOWN"))
        lines.insert(2, f"Done window: new={quality['uniqueDoneWindow']} duplicates={quality['duplicatesWindow']} late={quality['lateDoneWindow']} | Not a trading signal")
    updated = book_or_none.get("updatedAt") if isinstance(book_or_none, dict) else None
    if isinstance(updated, datetime):
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        local = updated.astimezone(_WIB)
        update_text = local.strftime("%Y-%m-%d %H:%M:%S.") + f"{local.microsecond // 1000:03d} WIB"
    else:
        update_text = "-"
    if not all_market:
        lines.append(f"Updated: {update_text}")
        lines.append(_table(_BOOK_HEADERS, build_order_book_rows(book_or_none)))
    title = "ALL MARKET RUNNING TRADE" if all_market else f"{_safe_text(symbol)} RECENT DONE"
    lines.extend(("", f"========== {title} ==========", "Time: WIB (UTC+07:00)"))
    if all_market:
        lines.append("Subscription * experimental | feed-wide health, not per-stock freshness | completeness UNKNOWN")
    headers = ("Time", "Code", *_DONE_HEADERS[1:]) if all_market else _DONE_HEADERS
    lines.append(_table(headers, build_recent_trade_rows(trades, done_limit, include_code=all_market)))
    if radar_alerts:
        lines.extend(("", "========== LIVE RADAR ALERTS (BREAKOUT & SQUEEZE) =========="))
        for alert in reversed(radar_alerts[-5:]):
            lines.append(alert.format_banner())
    if sniper_table:
        lines.extend(("", *sniper_table))
    prefix = "\x1b[2J\x1b[H" if clear and callable(getattr(output, "isatty", None)) and output.isatty() else ""
    output.write(prefix + "\n".join(lines) + "\n")
    if callable(getattr(output, "flush", None)):
        output.flush()

