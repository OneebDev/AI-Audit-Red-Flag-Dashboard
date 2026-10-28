"""Tests for the Calendar tab's pure builders and insights."""

from __future__ import annotations

import pandas as pd
import pytest

import calendar_view
from calendar_view import (
    available_years,
    build_month_cells,
    calendar_insights,
    day_entries,
    default_financial_year,
    financial_year_options,
    financial_year_title,
    holiday_name_map,
    month_heatmap,
    month_label,
    month_options,
    year_heatmap,
)
from detection import build_summary, run_all_checks
from utils import FINANCIAL_YEAR_MODES, ISLAMIC_HOLIDAY_SUGGESTIONS, pakistan_holidays

JULY_JUNE, JAN_DEC = FINANCIAL_YEAR_MODES


@pytest.fixture(scope="module")
def holiday_map() -> dict[pd.Timestamp, str]:
    names = {value: name for value, name in pakistan_holidays(2025)}
    for (month, day), name in ISLAMIC_HOLIDAY_SUGGESTIONS:
        names[pd.Timestamp(2025, month, day)] = name
    return names


def test_available_years_and_financial_year_options(checked_demo, holiday_map) -> None:
    assert available_years(checked_demo) == [2025]
    assert financial_year_options(checked_demo, JULY_JUNE) == [2024, 2025]
    assert financial_year_options(checked_demo, JAN_DEC) == [2025]
    assert default_financial_year(checked_demo, JULY_JUNE) == 2025
    assert default_financial_year(checked_demo, JAN_DEC) == 2025


def test_empty_inputs_fall_back_to_the_current_year() -> None:
    current = pd.Timestamp.today().year

    assert available_years(None) == [current]
    assert default_financial_year(None, JAN_DEC) == current
    assert financial_year_options(pd.DataFrame(), JAN_DEC) == [current]


def test_month_options_follow_the_financial_year(checked_demo) -> None:
    july_june = month_options(checked_demo, JULY_JUNE, 2025)
    jan_dec = month_options(checked_demo, JAN_DEC, 2025)

    assert july_june == [(2025, month) for month in range(7, 13)]
    assert jan_dec == [(2025, month) for month in range(1, 13)]
    assert month_label(2025, 11) == "November 2025"
    assert financial_year_title(2024, JULY_JUNE).startswith("2024")
    assert "Jul" in financial_year_title(2024, JULY_JUNE)


def test_holiday_name_map_accepts_mappings_and_iterables() -> None:
    mapped = holiday_name_map({pd.Timestamp("2025-08-14"): "Independence Day"})
    iterable = holiday_name_map([pd.Timestamp("2025-08-14")])
    invalid = holiday_name_map([pd.Timestamp("2025-08-14"), "not-a-date", None])

    assert mapped[pd.Timestamp("2025-08-14")] == "Independence Day"
    assert iterable[pd.Timestamp("2025-08-14")] == "Public holiday"
    assert len(invalid) == 1
    assert holiday_name_map(None) == {}


def test_build_month_cells_marks_weekends_holidays_and_flags(
    checked_demo, holiday_map
) -> None:
    cells = build_month_cells(
        checked_demo, 2025, 11, holidays=holiday_map, weekend_days=(5, 6)
    )

    assert len(cells) == 30
    by_day = {cell["day"]: cell for cell in cells}
    assert by_day[1]["date"] == pd.Timestamp("2025-11-01")
    assert by_day[1]["weekday"] == 5
    assert by_day[1]["is_weekend"] is True
    assert by_day[1]["flagged"] == 1
    assert by_day[1]["critical"] == 1
    assert by_day[1]["entries"] == 1
    assert by_day[9]["holiday"] == "Iqbal Day"
    assert by_day[9]["is_weekend"] is True
    assert by_day[3]["holiday"] is None
    assert by_day[3]["is_weekend"] is False
    assert by_day[8]["is_weekend"] is True
    assert by_day[8]["flagged"] == 1
    assert all(0 <= cell["week"] <= 5 for cell in cells)
    assert all(0 <= cell["weekday"] <= 6 for cell in cells)


def test_build_month_cells_accepts_empty_and_zero_flag_ledgers(make_ledger) -> None:
    checked = run_all_checks(
        make_ledger(
            [
                {"Vendor": "Vendor A", "Amount": 1_234.56},
                {"Vendor": "Vendor B", "Amount": 2_345.67},
            ]
        )
    )

    no_data = build_month_cells(None, 2025, 3)
    zero_flags = build_month_cells(checked, 2025, 3)

    assert len(no_data) == 31
    assert all(cell["flagged"] == 0 for cell in no_data)
    assert len(zero_flags) == 31
    assert all(cell["flagged"] == 0 for cell in zero_flags)
    assert sum(cell["entries"] for cell in zero_flags) == 2


def test_month_heatmap_has_weekend_bands_critical_outlines_and_holiday_star(
    checked_demo, holiday_map
) -> None:
    cells = build_month_cells(
        checked_demo, 2025, 11, holidays=holiday_map, weekend_days=(5, 6)
    )

    figure = month_heatmap(cells, "November 2025", weekend_days=(5, 6))

    assert len(figure.data) == 2  # heatmap + holiday star marker
    assert figure.data[0].type == "heatmap"
    assert figure.data[1].type == "scatter"
    assert len(figure.layout.shapes) == 4  # two weekend bands + two Critical days
    assert figure.layout.height == 360


def test_month_heatmap_without_holidays_has_a_single_trace(make_ledger) -> None:
    checked = run_all_checks(
        make_ledger(
            [
                {"Vendor": "Vendor A", "Amount": 1_234.56},
                {"Vendor": "Vendor B", "Amount": 2_345.67},
            ]
        )
    )
    cells = build_month_cells(checked, 2025, 3)

    figure = month_heatmap(cells, "March 2025")

    assert len(figure.data) == 1
    assert len(figure.layout.shapes) == 2


def test_year_heatmap_is_a_github_style_grid(checked_demo) -> None:
    figure = year_heatmap(checked_demo, 2025, title="2025")

    heatmap = figure.data[0]
    assert heatmap.type == "heatmap"
    assert len(heatmap.z) == 7
    assert len(heatmap.z[0]) >= 52
    assert any(value is not None for row in heatmap.z for value in row)
    assert "2025" in figure.layout.title.text


def test_calendar_insights_match_the_demo(checked_demo, holiday_map) -> None:
    insights = calendar_insights(checked_demo, holidays=holiday_map)

    assert insights["weekend_holiday_count"] == 9
    assert insights["total_flagged"] == 57
    assert insights["busiest_day"] == pd.Timestamp("2025-09-26")
    assert insights["busiest_count"] == 3
    assert insights["month_end_count"] == 7
    assert insights["month_rest_count"] == 50
    assert insights["month_end_share"] == pytest.approx(7 / 57)
    assert insights["top_month"] == pd.Timestamp("2025-11-01")
    assert insights["top_month_risk"] == pytest.approx(465.0)


def test_calendar_insights_handle_zero_flags(make_ledger) -> None:
    checked = run_all_checks(
        make_ledger(
            [
                {"Vendor": "Vendor A", "Amount": 1_234.56},
                {"Vendor": "Vendor B", "Amount": 2_345.67},
            ]
        )
    )

    insights = calendar_insights(checked)
    empty = calendar_insights(None)

    assert insights["total_flagged"] == 0
    assert insights["busiest_day"] is None
    assert insights["top_month"] is None
    assert empty == {
        "weekend_holiday_count": 0,
        "busiest_day": None,
        "busiest_count": 0,
        "month_end_count": 0,
        "month_rest_count": 0,
        "month_end_share": 0.0,
        "top_month": None,
        "top_month_risk": 0.0,
        "total_flagged": 0,
    }


def test_day_entries_returns_highest_risk_first(checked_demo) -> None:
    entries = day_entries(checked_demo, "2025-11-01")

    assert len(entries) == 1
    assert entries.iloc[0]["EntryID"] == "ENT-0601"
    assert entries.iloc[0]["risk_level"] == "Critical"
    assert day_entries(checked_demo, "2026-01-01").empty
    assert day_entries(None, "2025-11-01").empty


def test_calendar_builders_work_with_any_date_range(make_ledger) -> None:
    frame = make_ledger(
        [
            {"Vendor": "Vendor A", "Amount": 1_234.56},
            {"Vendor": "Vendor B", "Amount": 2_345.67},
        ]
    )
    frame["Date"] = pd.to_datetime(["2024-12-31", "2026-01-02"])
    checked = run_all_checks(frame, approval_limit=500_000.0)

    assert available_years(checked) == [2024, 2026]
    assert financial_year_options(checked, JULY_JUNE) == [2024, 2025]
    assert month_options(checked, JAN_DEC, 2024) == [(2024, 12)]
    july_june = month_options(checked, JULY_JUNE, 2024)
    assert july_june[0] == (2024, 12)
    assert july_june[-1] == (2025, 6)
    assert build_month_cells(checked, 2024, 12)
    assert isinstance(calendar_view.calendar_insights(checked), dict)
