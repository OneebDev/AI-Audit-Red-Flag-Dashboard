"""Shared PKR, date, and Karachi-localization helpers for AuditGuard.

All user-facing amounts go through :func:`format_pkr` and all dates through
:func:`format_date`, so the dashboard, CSV, Excel report, explanations, and
tests agree on ``Rs.`` and ``MM/DD/YYYY``.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

PKR_PREFIX = "Rs."
KARACHI_TZ = ZoneInfo("Asia/Karachi")
EXCEL_PKR_FORMAT = '"Rs. "#,##0.00'
EXCEL_DATE_FORMAT = "mm/dd/yyyy"

WEEKEND_PRESETS = {
    "Saturday + Sunday": (5, 6),
    "Sunday only": (6,),
}
DEFAULT_WEEKEND_DAYS = WEEKEND_PRESETS["Saturday + Sunday"]
WEEKDAY_NAMES = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)
CUSTOM_WEEKEND_OPTION = "Custom"


def resolve_weekend_days(
    choice: str, picked: list[str] | tuple[str, ...] | None
) -> tuple[int, ...]:
    """Return weekday numbers (Monday = 0) for a preset or custom selection."""
    if choice == CUSTOM_WEEKEND_OPTION:
        try:
            days = tuple(sorted({WEEKDAY_NAMES.index(name) for name in picked or ()}))
        except ValueError:
            return DEFAULT_WEEKEND_DAYS
        return days or DEFAULT_WEEKEND_DAYS
    return WEEKEND_PRESETS.get(choice, DEFAULT_WEEKEND_DAYS)

PAKISTAN_FIXED_HOLIDAYS = (
    ((2, 5), "Kashmir Day"),
    ((3, 23), "Pakistan Day"),
    ((5, 1), "Labour Day"),
    ((5, 28), "Youm-e-Takbeer"),
    ((8, 14), "Independence Day"),
    ((11, 9), "Iqbal Day"),
    ((12, 25), "Quaid-e-Azam Day"),
)

ISLAMIC_HOLIDAY_SUGGESTIONS = (
    ((3, 31), "Eid ul Fitr (moon-sighting dependent)"),
    ((6, 7), "Eid ul Adha (moon-sighting dependent)"),
    ((7, 6), "Ashura (moon-sighting dependent)"),
    ((9, 5), "Eid Milad un Nabi (moon-sighting dependent)"),
)

INPUT_DATE_FORMATS = ("Auto-detect", "MM/DD/YYYY", "DD/MM/YYYY")
DEFAULT_INPUT_DATE_FORMAT = "MM/DD/YYYY"
FINANCIAL_YEAR_MODES = ("July–June (Pakistan)", "January–December")
DEFAULT_FINANCIAL_YEAR_MODE = FINANCIAL_YEAR_MODES[0]
CUSTOM_FINANCIAL_YEAR_MODE = "Custom start month"
CUSTOM_FY_MODE_PREFIX = "Custom:"
MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def _indian_group(integer_text: str) -> str:
    """Group digits in the South Asian style: 12,50,000 instead of 1,250,000."""
    if len(integer_text) <= 3:
        return integer_text
    head, tail = integer_text[:-3], integer_text[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def _international_group(integer_text: str) -> str:
    """Group digits in threes: 1,250,000."""
    groups = []
    while len(integer_text) > 3:
        groups.insert(0, integer_text[-3:])
        integer_text = integer_text[:-3]
    groups.insert(0, integer_text)
    return ",".join(groups)


def format_pkr(
    amount: object,
    short: bool = False,
    lakh_crore: bool = True,
) -> str:
    """Format an amount as Pakistani rupees.

    ``format_pkr(1_250_000)`` returns ``"Rs. 12,50,000"`` with the default
    ``lakh_crore=True`` and ``"Rs. 1,250,000"`` with ``lakh_crore=False``.
    ``short=True`` returns ``"Rs. 12.5 Lac"`` or ``"Rs. 1.2 Cr"``. Whole
    amounts omit decimals; fractional amounts keep two.
    """
    try:
        value = float(amount)
    except (TypeError, ValueError):
        value = 0.0
    if pd.isna(value):
        value = 0.0

    sign = "-" if value < 0 else ""
    absolute = abs(value)

    if short:
        if lakh_crore:
            if absolute >= 1_00_00_000:
                return f"{sign}{PKR_PREFIX} {absolute / 1_00_00_000:,.1f} Cr"
            if absolute >= 1_00_000:
                return f"{sign}{PKR_PREFIX} {absolute / 1_00_000:,.1f} Lac"
        else:
            if absolute >= 1_000_000_000:
                return f"{sign}{PKR_PREFIX} {absolute / 1_000_000_000:,.1f}B"
            if absolute >= 1_000_000:
                return f"{sign}{PKR_PREFIX} {absolute / 1_000_000:,.1f}M"
            if absolute >= 1_000:
                return f"{sign}{PKR_PREFIX} {absolute / 1_000:,.1f}K"
        return f"{sign}{PKR_PREFIX} {absolute:,.0f}"

    has_fraction = abs(absolute - round(absolute)) >= 0.005
    if has_fraction:
        integer_text, decimal_text = f"{absolute:.2f}".split(".")
    else:
        integer_text, decimal_text = f"{absolute:.0f}", ""

    grouped = (
        _indian_group(integer_text)
        if lakh_crore
        else _international_group(integer_text)
    )
    suffix = f".{decimal_text}" if decimal_text else ""
    return f"{sign}{PKR_PREFIX} {grouped}{suffix}"


def format_date(value: object, fallback: str = "—") -> str:
    """Return a date as ``MM/DD/YYYY`` or a friendly fallback."""
    if value is None:
        return fallback
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return fallback
    if pd.isna(timestamp):
        return fallback
    return timestamp.strftime("%m/%d/%Y")


def format_datetime(value: object, fallback: str = "—") -> str:
    """Return a timestamp as ``MM/DD/YYYY HH:MM`` in Asia/Karachi."""
    if value is None:
        return fallback
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return fallback
    if pd.isna(timestamp):
        return fallback
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    return timestamp.tz_convert(KARACHI_TZ).strftime("%m/%d/%Y %H:%M PKT")


def now_karachi() -> datetime:
    """Return the current time in Karachi, Pakistan."""
    return datetime.now(KARACHI_TZ)


def pakistan_holidays(year: int | str = 2025) -> list[tuple[pd.Timestamp, str]]:
    """Return the seven fixed Pakistan public holidays for a year."""
    year_int = int(year)
    return [
        (pd.Timestamp(year_int, month, day), name)
        for (month, day), name in PAKISTAN_FIXED_HOLIDAYS
    ]


def pakistan_holiday_names(
    year: int | str = 2025,
    start_year: int | None = None,
) -> dict[pd.Timestamp, str]:
    """Return a date-to-name mapping for fixed holidays, optionally a FY range."""
    year_int = int(year)
    years = {year_int}
    if start_year is not None:
        years.add(int(start_year))
        years.add(int(start_year) + 1)
    names: dict[pd.Timestamp, str] = {}
    for item_year in sorted(years):
        for date, name in pakistan_holidays(item_year):
            names[date] = name
    return names


def mask_key(key: str) -> str:
    """Mask a Groq key as ``gsk_...abcd`` without revealing the middle."""
    text = str(key or "")
    if len(text) <= 8:
        return "gsk_...****"
    return f"{text[:4]}...{text[-4:]}"


def financial_year_start_month(mode: str) -> int:
    """Return the first month (1-12) of the configured financial year."""
    if mode == FINANCIAL_YEAR_MODES[1]:
        return 1
    if mode.startswith(CUSTOM_FY_MODE_PREFIX):
        try:
            month = int(mode.split(":", 1)[1].strip())
        except (IndexError, ValueError):
            return 7
        return min(12, max(1, month))
    return 7


def financial_year_range(start_year: int, mode: str) -> tuple[pd.Timestamp, pd.Timestamp]:
    """Return the inclusive start and end of a financial year."""
    year = int(start_year)
    month = financial_year_start_month(mode)
    start = pd.Timestamp(year, month, 1)
    end = start + pd.DateOffset(months=12) - pd.Timedelta(1, unit="D")
    return start, end


def financial_year_start(value: object, mode: str) -> int:
    """Return the start year of the financial year containing a date."""
    timestamp = pd.Timestamp(value)
    month = financial_year_start_month(mode)
    return int(timestamp.year) if timestamp.month >= month else int(timestamp.year) - 1


def financial_year_label(start_year: int, mode: str) -> str:
    """Return a readable financial-year label."""
    if mode == FINANCIAL_YEAR_MODES[1]:
        return f"{int(start_year)} (Jan–Dec)"
    month = financial_year_start_month(mode)
    if month == 1:
        return f"{int(start_year)} (Jan–Dec)"
    if month == 7:
        return f"{int(start_year)}–{str(int(start_year) + 1)[-2:]} (Jul–Jun)"
    end_month = 12 if month == 1 else month - 1
    start_name = MONTH_NAMES[month - 1][:3]
    end_name = MONTH_NAMES[end_month - 1][:3]
    return (
        f"{int(start_year)}–{str(int(start_year) + 1)[-2:]} "
        f"({start_name}–{end_name})"
    )


def financial_year_months(start_year: int, mode: str) -> list[tuple[int, int]]:
    """Return every (year, month) inside a financial year."""
    year = int(start_year)
    month = financial_year_start_month(mode)
    return [(year, item) for item in range(month, 13)] + [
        (year + 1, item) for item in range(1, month)
    ]
