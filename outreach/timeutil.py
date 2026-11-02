from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def local_now(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))


def local_midnight_utc(tz: str) -> datetime:
    n = local_now(tz)
    return n.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def add_business_days(start: datetime, days: int) -> datetime:
    d = start
    left = days
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            left -= 1
    return d


def in_business_hours(tz: str, hours: list[int] | tuple[int, int]) -> bool:
    n = local_now(tz)
    return n.weekday() < 5 and hours[0] <= n.hour < hours[1]
