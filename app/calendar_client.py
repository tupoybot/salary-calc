from __future__ import annotations

import calendar as pycalendar
from datetime import date, timedelta

import httpx

from app.calculator import YearCalendar


ISDAYOFF_URL = "https://isdayoff.ru/api/getdata"


class IsDayOffCalendarProvider:
    """Loads and caches Russian production calendar data from isDayOff."""

    def __init__(self, timeout: float = 8.0) -> None:
        self.timeout = timeout
        self._cache: dict[int, YearCalendar] = {}

    def get_year(self, year: int) -> YearCalendar:
        if year not in self._cache:
            self._cache[year] = self._fetch_year(year)
        return self._cache[year]

    def _fetch_year(self, year: int) -> YearCalendar:
        params = {
            "year": str(year),
            "cc": "ru",
            "pre": "1",
            "holiday": "1",
        }

        try:
            response = httpx.get(ISDAYOFF_URL, params=params, timeout=self.timeout)
            response.raise_for_status()
            raw_codes = "".join(ch for ch in response.text if ch.isdigit())
            expected = 366 if pycalendar.isleap(year) else 365
            if len(raw_codes) != expected:
                raise ValueError(
                    f"isDayOff returned {len(raw_codes)} day codes, expected {expected}"
                )
            return YearCalendar(
                year=year,
                codes=_codes_to_dates(year, raw_codes),
                source="isdayoff.ru",
                fallback=False,
            )
        except Exception as exc:  # pragma: no cover - exercised only on network failure
            return _fallback_weekday_calendar(year, str(exc))


def _codes_to_dates(year: int, codes: str) -> dict[date, str]:
    start = date(year, 1, 1)
    return {
        start + timedelta(days=offset): code
        for offset, code in enumerate(codes)
    }


def _fallback_weekday_calendar(year: int, reason: str) -> YearCalendar:
    days = 366 if pycalendar.isleap(year) else 365
    start = date(year, 1, 1)
    codes: dict[date, str] = {}
    for offset in range(days):
        day = start + timedelta(days=offset)
        codes[day] = "0" if day.weekday() < 5 else "1"

    return YearCalendar(
        year=year,
        codes=codes,
        source=f"fallback weekday calendar: {reason}",
        fallback=True,
    )

