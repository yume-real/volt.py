"""In-world calendar time.

A single seconds-since-epoch conversion backs both :attr:`total_seconds` and
:meth:`add_seconds`, so the two can never disagree.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class Time:
    year: int = 0
    month: int = 1
    day: int = 1
    hour: int = 0
    minute: int = 0
    second: int = 0
    hours_in_day: int = 24
    days_in_month: int = 30
    months_in_year: int = 12
    days_passed_from_start: int = 0

    @property
    def days_in_year(self) -> int:
        return max(1, self.months_in_year * self.days_in_month)

    @property
    def seconds_in_day(self) -> int:
        return max(1, self.hours_in_day) * 3600

    @property
    def short_time(self) -> str:
        return "%dY%dM%dD %02d:%02d:%02d" % (
            self.year,
            self.month,
            self.day,
            self.hour,
            self.minute,
            self.second,
        )

    @property
    def total_days(self) -> int:
        return (
            self.year * self.days_in_year
            + (self.month - 1) * self.days_in_month
            + (self.day - 1)
        )

    def total_seconds(self) -> int:
        return (
            self.total_days * self.seconds_in_day
            + self.hour * 3600
            + self.minute * 60
            + self.second
        )

    def compare(self, other: "Time") -> int:
        return self.total_seconds() - other.total_seconds()

    def add_seconds(self, seconds: int) -> "Time":
        seconds = int(seconds)
        if seconds == 0:
            return self.copy()
        total = self.total_seconds() + seconds
        seconds_in_day = self.seconds_in_day
        days_passed, remainder = divmod(total, seconds_in_day)
        days_passed_from_start = self.days_passed_from_start

        if seconds >= 0:
            days_passed_from_start += max(0, days_passed - self.total_days)
        else:
            days_passed_from_start += min(0, days_passed - self.total_days)

        hour, remainder = divmod(remainder, 3600)
        minute, second = divmod(remainder, 60)

        year, rest = divmod(days_passed, self.days_in_year)
        month, day = divmod(rest, self.days_in_month)
        return Time(
            year=year,
            month=month + 1,
            day=day + 1,
            hour=hour,
            minute=minute,
            second=second,
            hours_in_day=self.hours_in_day,
            days_in_month=self.days_in_month,
            months_in_year=self.months_in_year,
            days_passed_from_start=days_passed_from_start,
        )

    def copy(self) -> "Time":
        return Time.from_json(self.to_json())

    def to_json(self) -> Dict[str, Any]:
        return {
            "year": self.year,
            "month": self.month,
            "day": self.day,
            "hour": self.hour,
            "minute": self.minute,
            "second": self.second,
            "hoursInDay": self.hours_in_day,
            "daysInMonth": self.days_in_month,
            "monthsInYear": self.months_in_year,
            "daysPassedFromStart": self.days_passed_from_start,
        }

    @classmethod
    def from_json(cls, json: Any) -> "Time":
        data = json if isinstance(json, dict) else {}

        def as_int(key: str, default: int) -> int:
            value = data.get(key, default)
            try:
                return int(value)
            except (TypeError, ValueError):
                return default

        return cls(
            year=as_int("year", 0),
            month=max(1, as_int("month", 1)),
            day=max(1, as_int("day", 1)),
            hour=as_int("hour", 0),
            minute=as_int("minute", 0),
            second=as_int("second", 0),
            hours_in_day=max(1, as_int("hoursInDay", 24)),
            days_in_month=max(1, as_int("daysInMonth", 30)),
            months_in_year=max(1, as_int("monthsInYear", 12)),
            days_passed_from_start=as_int("daysPassedFromStart", 0),
        )