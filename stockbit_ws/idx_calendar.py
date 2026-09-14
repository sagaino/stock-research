"""Minimal IDX session calendar for the 2025-2026 backtest dataset."""

from __future__ import annotations

import datetime


# National holidays and joint leave days that fall on weekdays in the current
# historical sample. A missing EOD marker on another weekday remains a data
# problem, never a silently substituted older session.
IDX_CLOSURES_2025 = {
    datetime.date(2025, 1, 1): "Tahun Baru",
    datetime.date(2025, 1, 27): "Isra Mikraj",
    datetime.date(2025, 1, 28): "Cuti bersama Imlek",
    datetime.date(2025, 1, 29): "Tahun Baru Imlek",
    datetime.date(2025, 3, 28): "Cuti bersama Nyepi",
    datetime.date(2025, 3, 31): "Idul Fitri",
    datetime.date(2025, 4, 1): "Idul Fitri",
    datetime.date(2025, 4, 2): "Cuti bersama Idul Fitri",
    datetime.date(2025, 4, 3): "Cuti bersama Idul Fitri",
    datetime.date(2025, 4, 4): "Cuti bersama Idul Fitri",
    datetime.date(2025, 4, 7): "Cuti bersama Idul Fitri",
    datetime.date(2025, 4, 18): "Wafat Yesus Kristus",
    datetime.date(2025, 5, 1): "Hari Buruh",
    datetime.date(2025, 5, 12): "Waisak",
    datetime.date(2025, 5, 13): "Cuti bersama Waisak",
    datetime.date(2025, 5, 29): "Kenaikan Yesus Kristus",
    datetime.date(2025, 5, 30): "Cuti bersama Kenaikan Yesus Kristus",
    datetime.date(2025, 6, 6): "Idul Adha",
    datetime.date(2025, 6, 9): "Cuti bersama Idul Adha",
    datetime.date(2025, 6, 27): "Tahun Baru Islam",
    datetime.date(2025, 8, 18): "Cuti bersama Hari Kemerdekaan",
    datetime.date(2025, 9, 5): "Maulid Nabi",
    datetime.date(2025, 12, 25): "Natal",
    datetime.date(2025, 12, 26): "Cuti bersama Natal",
}


IDX_CLOSURES_2026 = {
    datetime.date(2026, 1, 1): "Tahun Baru",
    datetime.date(2026, 1, 16): "Isra Mikraj",
    datetime.date(2026, 2, 16): "Cuti bersama Imlek",
    datetime.date(2026, 2, 17): "Tahun Baru Imlek",
    datetime.date(2026, 3, 18): "Cuti bersama Nyepi",
    datetime.date(2026, 3, 19): "Nyepi",
    datetime.date(2026, 3, 20): "Cuti bersama Idul Fitri",
    datetime.date(2026, 3, 23): "Cuti bersama Idul Fitri",
    datetime.date(2026, 3, 24): "Cuti bersama Idul Fitri",
    datetime.date(2026, 4, 3): "Wafat Yesus Kristus",
    datetime.date(2026, 5, 1): "Hari Buruh",
    datetime.date(2026, 5, 14): "Kenaikan Yesus Kristus",
    datetime.date(2026, 5, 15): "Cuti bersama Kenaikan Yesus Kristus",
    datetime.date(2026, 5, 27): "Idul Adha",
    datetime.date(2026, 5, 28): "Cuti bersama Idul Adha",
    datetime.date(2026, 6, 1): "Hari Lahir Pancasila",
    datetime.date(2026, 6, 16): "Tahun Baru Islam",
    datetime.date(2026, 8, 17): "Hari Kemerdekaan",
    datetime.date(2026, 8, 25): "Maulid Nabi",
    datetime.date(2026, 12, 24): "Cuti bersama Natal",
    datetime.date(2026, 12, 25): "Natal",
}

IDX_CLOSURES = IDX_CLOSURES_2025 | IDX_CLOSURES_2026


def closure_reason(date: datetime.date) -> str | None:
    return IDX_CLOSURES.get(date)


def is_idx_session(date: datetime.date) -> bool:
    return date.weekday() < 5 and closure_reason(date) is None


def next_idx_sessions(after: datetime.date, count: int) -> list[datetime.date]:
    """Return the next ``count`` expected IDX sessions after ``after``."""
    sessions = []
    cursor = after + datetime.timedelta(days=1)
    while len(sessions) < count:
        if is_idx_session(cursor):
            sessions.append(cursor)
        cursor += datetime.timedelta(days=1)
    return sessions


def last_idx_session_on_or_before(date: datetime.date) -> datetime.date:
    """Return the latest expected IDX session at or before ``date``."""
    while not is_idx_session(date):
        date -= datetime.timedelta(days=1)
    return date


def first_idx_session_on_or_after(date: datetime.date) -> datetime.date:
    """Return the first expected IDX session at or after ``date``."""
    while not is_idx_session(date):
        date += datetime.timedelta(days=1)
    return date
