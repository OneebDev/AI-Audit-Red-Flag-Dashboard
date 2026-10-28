"""Tests for PKR, date, holiday, and financial-year helpers."""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from utils import (
    DEFAULT_FINANCIAL_YEAR_MODE,
    EXCEL_DATE_FORMAT,
    EXCEL_PKR_FORMAT,
    financial_year_label,
    financial_year_months,
    financial_year_range,
    financial_year_start,
    financial_year_start_month,
    format_date,
    format_datetime,
    format_pkr,
    mask_key,
    now_karachi,
    pakistan_holiday_names,
    pakistan_holidays,
    resolve_weekend_days,
)


def test_format_pkr_defaults_to_lakh_crore_grouping() -> None:
    assert format_pkr(1_250_000) == "Rs. 12,50,000"
    assert format_pkr(500_000) == "Rs. 5,00,000"
    assert format_pkr(77_29_596.13) == "Rs. 77,29,596.13"


def test_format_pkr_can_use_international_grouping() -> None:
    assert format_pkr(1_250_000, lakh_crore=False) == "Rs. 1,250,000"
    assert format_pkr(1_234.5, lakh_crore=False) == "Rs. 1,234.50"


def test_format_pkr_short_uses_lakh_and_crore() -> None:
    assert format_pkr(12_500, short=True) == "Rs. 12,500"
    assert format_pkr(1_250_000, short=True) == "Rs. 12.5 Lac"
    assert format_pkr(12_500_000, short=True) == "Rs. 1.2 Cr"


def test_format_pkr_short_can_use_millions() -> None:
    assert format_pkr(1_500, short=True, lakh_crore=False) == "Rs. 1.5K"
    assert format_pkr(2_500_000, short=True, lakh_crore=False) == "Rs. 2.5M"


def test_format_pkr_handles_bad_and_negative_values() -> None:
    assert format_pkr("bad") == "Rs. 0"
    assert format_pkr(None) == "Rs. 0"
    assert format_pkr(float("nan")) == "Rs. 0"
    assert format_pkr(-1_250) == "-Rs. 1,250"


def test_format_date_is_mmddyyyy_everywhere() -> None:
    assert format_date(pd.Timestamp("2025-03-14")) == "03/14/2025"
    assert format_date("2025-12-25") == "12/25/2025"
    assert format_date(pd.NaT) == "—"
    assert format_date(None, "fallback") == "fallback"
    assert EXCEL_DATE_FORMAT == "mm/dd/yyyy"


def test_format_datetime_uses_karachi_timezone() -> None:
    text = format_datetime(pd.Timestamp("2025-03-14 12:30:00", tz="UTC"))
    assert text == "03/14/2025 17:30 PKT"
    assert format_datetime(None) == "—"


def test_now_karachi_returns_aware_time() -> None:
    value = now_karachi()
    assert isinstance(value, datetime)
    assert value.tzinfo is not None
    assert "PKT" in format_datetime(value)


def test_pakistan_fixed_holidays_are_complete() -> None:
    holidays = pakistan_holidays(2025)
    names = {name for _, name in holidays}
    assert len(holidays) == 7
    assert names == {
        "Kashmir Day",
        "Pakistan Day",
        "Labour Day",
        "Youm-e-Takbeer",
        "Independence Day",
        "Iqbal Day",
        "Quaid-e-Azam Day",
    }
    assert (pd.Timestamp(2025, 2, 5), "Kashmir Day") in holidays
    assert (pd.Timestamp(2025, 12, 25), "Quaid-e-Azam Day") in holidays


def test_pakistan_holiday_names_supports_two_years() -> None:
    names = pakistan_holiday_names(2025)
    assert len(names) == 7
    assert names[pd.Timestamp("2025-08-14")] == "Independence Day"
    both = pakistan_holiday_names(2024, start_year=2024)
    assert len(both) == 14
    assert both[pd.Timestamp("2025-03-23")] == "Pakistan Day"


def test_financial_year_modes() -> None:
    mode = DEFAULT_FINANCIAL_YEAR_MODE
    assert financial_year_range(2025, mode) == (
        pd.Timestamp("2025-07-01"),
        pd.Timestamp("2026-06-30"),
    )
    assert financial_year_range(2025, "January–December") == (
        pd.Timestamp("2025-01-01"),
        pd.Timestamp("2025-12-31"),
    )
    assert financial_year_start("2025-06-30", mode) == 2024
    assert financial_year_start("2025-07-01", mode) == 2025
    assert financial_year_start("2025-12-01", "January–December") == 2025
    assert financial_year_label(2025, mode) == "2025–26 (Jul–Jun)"
    assert financial_year_label(2025, "January–December") == "2025 (Jan–Dec)"
    assert financial_year_months(2025, mode)[0] == (2025, 7)
    assert financial_year_months(2025, mode)[-1] == (2026, 6)
    assert len(financial_year_months(2025, "January–December")) == 12


def test_custom_financial_year_start_month() -> None:
    mode = "Custom: 4"
    assert financial_year_start_month(mode) == 4
    assert financial_year_range(2025, mode) == (
        pd.Timestamp("2025-04-01"),
        pd.Timestamp("2026-03-31"),
    )
    assert financial_year_start("2025-03-31", mode) == 2024
    assert financial_year_start("2025-04-01", mode) == 2025
    assert financial_year_label(2025, mode) == "2025–26 (Apr–Mar)"
    months = financial_year_months(2025, mode)
    assert months[0] == (2025, 4)
    assert months[-1] == (2026, 3)
    assert financial_year_start_month("nonsense") == 7
    assert financial_year_start_month("Custom: 99") == 12
    assert financial_year_label(2025, "Custom: 1") == "2025 (Jan–Dec)"


def test_resolve_weekend_days_supports_presets_and_custom() -> None:
    assert resolve_weekend_days("Saturday + Sunday", None) == (5, 6)
    assert resolve_weekend_days("Sunday only", None) == (6,)
    assert resolve_weekend_days("Custom", ["Friday", "Saturday"]) == (4, 5)
    assert resolve_weekend_days("Custom", ["Saturday", "Friday", "Saturday"]) == (4, 5)
    assert resolve_weekend_days("Custom", []) == (5, 6)
    assert resolve_weekend_days("Custom", ["Funday"]) == (5, 6)


def test_excel_formats_and_key_masking() -> None:
    assert EXCEL_PKR_FORMAT == '"Rs. "#,##0.00'
    assert mask_key("gsk_1234567890abcdef") == "gsk_...cdef"
    assert mask_key("short") == "gsk_...****"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("bad", "Rs. 0"), ("", "Rs. 0"), (pd.NA, "Rs. 0")],
)
def test_format_pkr_is_never_empty(raw: object, expected: str) -> None:
    assert format_pkr(raw) == expected
