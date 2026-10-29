"""Application-level tests: uploads, settings, Groq keys, and Streamlit smoke runs."""

from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from openpyxl import Workbook
from streamlit.testing.v1 import AppTest

import app
from detection import FLAG_COLUMNS, GROUND_TRUTH_COLUMN, build_summary, run_all_checks
from export import dataframe_to_excel_bytes

APP_PATH = Path(__file__).resolve().parents[1] / "app.py"
TABS = [
    "Overview",
    "Flagged Entries",
    "AI Insights",
    "Calendar",
    "Export & Accuracy",
    "Guide",
]


def _clean_ledger() -> pd.DataFrame:
    """Return a two-row ledger that triggers none of the six rules."""
    return pd.DataFrame(
        {
            "EntryID": ["E1", "E2"],
            "Date": pd.to_datetime(["2025-03-03", "2025-03-04"]),
            "Account": ["Office Expense", "Rent"],
            "Vendor": ["Vendor A", "Vendor B"],
            "Description": ["Office supplies", "Monthly rent"],
            "Amount": [1_234.56, 2_345.67],
            "PostedBy": ["Alice", "Bob"],
            "ApprovedBy": ["Bob", "Alice"],
        }
    )


def _demo_app() -> AppTest:
    test = AppTest.from_file(str(APP_PATH), default_timeout=60)
    test.run()
    next(button for button in test.button if button.label == "Load Demo Data").click()
    test.run()
    return test


def _visible_text(test: AppTest) -> str:
    """Collect the user-visible text elements rendered on the page."""
    parts: list[str] = []
    for name in (
        "markdown",
        "caption",
        "title",
        "header",
        "subheader",
        "info",
        "warning",
        "error",
        "success",
    ):
        elements = getattr(test, name, [])
        for element in elements:
            value = getattr(element, "value", "")
            if isinstance(value, str):
                parts.append(value)
    return "\n".join(parts)


def test_app_starts_with_empty_states() -> None:
    test = AppTest.from_file(str(APP_PATH), default_timeout=60)
    test.run()

    assert list(test.exception) == []
    assert [tab.label for tab in test.tabs] == TABS
    assert any("No ledger loaded yet" in item.value for item in test.markdown)
    assert any("EntryID" in item.value for item in test.markdown)
    assert test.session_state["status"] == "Ready"
    assert {button.label for button in test.button} >= {
        "Load Demo Data",
        "Run Audit",
        "Reset advanced settings",
    }

    assert test.session_state["approval_limit"] == 500_000.0
    assert test.session_state["round_threshold"] == 1_000.0
    assert test.session_state["weekend_choice"] == "Saturday + Sunday"
    assert test.session_state["input_date_format"] == "MM/DD/YYYY"
    assert test.session_state["financial_year_mode"] == "July–June (Pakistan)"
    assert test.session_state["use_lakh_crore"] is True
    assert test.session_state["use_llm"] is False
    assert test.session_state["top_n"] == 10
    assert test.session_state["groq_keys"] == []


def test_demo_data_runs_the_full_audit() -> None:
    test = _demo_app()

    assert list(test.exception) == []
    assert test.session_state["status"] == "Audit complete"
    summary = test.session_state["summary"]
    assert summary["total_entries"] == 606
    assert summary["flagged_entries"] == 57
    assert summary["overall_risk_level"] == "High"
    assert len(test.dataframe) >= 3
    assert any("Executive summary" in item.value for item in test.markdown)
    assert any("Audit complete" in item.value for item in test.markdown)
    assert any("Showing 57 of 57 flagged entries" in item.value for item in test.markdown)

    calendar_fy = next(item for item in test.selectbox if item.key == "calendar_fy")
    calendar_month = next(item for item in test.selectbox if item.key == "calendar_month")
    assert calendar_fy.value == "2025–26 (Jul–Jun)"
    assert calendar_month.value == "December 2025"
    assert any(item.label == "Inspect a day" for item in test.date_input)

    explain = next(
        item for item in test.slider if item.label.startswith("Entries to explain")
    )
    explain.set_value(25).run()
    assert list(test.exception) == []
    assert test.session_state["top_n"] == 25
    assert any("Top 25 entries to investigate first" in item.value for item in test.markdown)


def test_custom_weekend_and_financial_year_settings() -> None:
    test = _demo_app()

    weekend = next(item for item in test.selectbox if item.key == "weekend_choice")
    weekend.set_value("Custom").run()
    custom = next(item for item in test.multiselect if item.key == "custom_weekend_days")
    custom.set_value(["Friday", "Saturday"]).run()
    assert list(test.exception) == []
    assert test.session_state["custom_weekend_days"] == ["Friday", "Saturday"]

    fy = next(item for item in test.selectbox if item.key == "financial_year_mode")
    fy.set_value("Custom start month").run()
    month = next(item for item in test.selectbox if item.key == "fy_start_month")
    month.set_value("March").run()
    assert list(test.exception) == []
    calendar_fy = next(item for item in test.selectbox if item.key == "calendar_fy")
    assert calendar_fy.value == "2025–26 (Mar–Feb)"


def test_risk_donut_labels_include_shares_and_stay_inside_the_ring() -> None:
    summary = build_summary(run_all_checks(_clean_ledger()))

    donut = app._risk_donut(summary)
    pie = donut.data[0]
    assert str(pie.textposition) == "inside"
    assert str(pie.textinfo) == "percent"
    assert list(pie.labels) == [
        "Low · 100.0%",
        "Medium · 0.0%",
        "High · 0.0%",
        "Critical · 0.0%",
    ]
    assert donut.layout.margin.b >= 56


def test_flagged_display_styles_normal_tables() -> None:
    display = pd.DataFrame({"Risk Level": ["High"]})

    rendered = app._flagged_display_table(display)

    assert isinstance(rendered, pd.io.formats.style.Styler)


def test_flagged_display_bypasses_styling_for_large_tables() -> None:
    display = pd.DataFrame(
        {"Risk Level": ["High"] * (app.FLAGGED_STYLE_MAX_ROWS + 1)}
    )

    rendered = app._flagged_display_table(display)

    assert rendered is display


def test_rendered_interface_uses_rupees_not_dollars() -> None:
    test = _demo_app()

    visible = _visible_text(test)

    assert "Rs." in visible
    assert "$" not in visible
    assert "MM/DD/YYYY" in visible
    assert "Karachi" in visible


def test_investigation_filters_narrow_the_flagged_table() -> None:
    test = _demo_app()

    flag_filter = next(item for item in test.selectbox if item.key == "filter_flag")
    flag_filter.set_value("Self-Approval").run()
    assert list(test.exception) == []
    assert any("Showing 11 of 57" in item.value for item in test.markdown)
    assert test.dataframe[0].value.shape[0] == 11

    flag_filter = next(item for item in test.selectbox if item.key == "filter_flag")
    flag_filter.set_value("All flag types")
    risk_filter = next(item for item in test.multiselect if item.key == "filter_risk")
    risk_filter.set_value(["Medium"]).run()
    assert list(test.exception) == []
    assert any("Showing 41 of 57" in item.value for item in test.markdown)

    risk_filter = next(item for item in test.multiselect if item.key == "filter_risk")
    risk_filter.set_value(["Low", "Medium", "High", "Critical"]).run()
    vendor_filter = next(item for item in test.selectbox if item.key == "filter_vendor")
    vendor_filter.set_value("Apex Consulting Karachi").run()
    assert list(test.exception) == []
    assert any("Showing 2 of 57" in item.value for item in test.markdown)

    min_risk = next(item for item in test.slider if item.key == "filter_min_risk")
    min_risk.set_value(100).run()
    assert list(test.exception) == []
    assert any("Showing 0 of 57" in item.value for item in test.markdown)
    assert any("No entries match these filters" in item.value for item in test.info)

    min_risk = next(item for item in test.slider if item.key == "filter_min_risk")
    min_risk.set_value(0)
    vendor_filter = next(item for item in test.selectbox if item.key == "filter_vendor")
    vendor_filter.set_value("All vendors")
    flag_filter = next(item for item in test.selectbox if item.key == "filter_flag")
    flag_filter.set_value("Duplicate").run()
    assert list(test.exception) == []
    assert any("Showing 12 of 57" in item.value for item in test.markdown)

    flag_filter = next(item for item in test.selectbox if item.key == "filter_flag")
    flag_filter.set_value("All flag types").run()
    search = next(item for item in test.text_input if item.key == "filter_search")
    search.set_value("advisory").run()
    assert list(test.exception) == []
    assert any("Showing 5 of 57" in item.value for item in test.markdown)

    search = next(item for item in test.text_input if item.key == "filter_search")
    search.set_value("")
    date_filter = next(item for item in test.date_input if item.label == "Date range")
    date_filter.set_value((date(2025, 12, 1), date(2025, 12, 18))).run()
    assert list(test.exception) == []
    assert any("Showing 3 of 57" in item.value for item in test.markdown)


def test_zero_flag_ledger_shows_a_clean_state() -> None:
    clean = _clean_ledger()
    test = AppTest.from_file(str(APP_PATH), default_timeout=60)
    test.run()
    test.session_state["raw_frame"] = clean
    test.session_state["raw_name"] = "Clean test ledger"
    test.run()
    next(button for button in test.button if button.label == "Run Audit").click().run()

    assert list(test.exception) == []
    assert test.session_state["summary"]["flagged_entries"] == 0
    assert any("Clean ledger — zero flags" in item.value for item in test.markdown)


def test_zero_flag_overview_charts_hide_their_axes() -> None:
    checked = run_all_checks(_clean_ledger())
    summary = build_summary(checked)

    flags = app._flags_figure(summary)
    timeline = app._timeline_figure(checked)
    vendors = app._vendor_figure(summary)
    for figure in (flags, timeline, vendors):
        assert figure.layout.xaxis.visible is False
        assert figure.layout.yaxis.visible is False
    assert "No flags" in flags.layout.annotations[0].text
    assert "No flagged entries" in timeline.layout.annotations[0].text
    assert "No vendor exposure" in vendors.layout.annotations[0].text


def test_read_upload_supports_csv_excel_and_ledger_sheet(make_ledger) -> None:
    frame = make_ledger(
        [
            {"Vendor": "Vendor A", "Amount": 1_234.56},
            {"Vendor": "Vendor B", "Amount": 2_345.67},
        ]
    )

    csv_bytes = frame.to_csv(index=False, sep=";").encode("utf-8")
    csv_frame = app._read_upload(csv_bytes, "ledger.csv")
    assert list(csv_frame.columns) == list(frame.columns)
    assert len(csv_frame) == 2
    assert csv_frame["Amount"].tolist() == [1_234.56, 2_345.67]

    xlsx_frame = app._read_upload(dataframe_to_excel_bytes(frame), "ledger.xlsx")
    assert list(xlsx_frame.columns) == list(frame.columns)
    assert len(xlsx_frame) == 2

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame({"Note": ["not the ledger"]}).to_excel(
            writer, sheet_name="Notes", index=False
        )
        frame.to_excel(writer, sheet_name="Ledger", index=False)
    picked = app._read_upload(buffer.getvalue(), "multi.xlsx")
    assert list(picked.columns) == list(frame.columns)
    assert len(picked) == 2

    with pytest.raises(Exception):
        app._read_upload(b"this is not a workbook", "broken.xlsx")

    empty_buffer = io.BytesIO()
    Workbook().save(empty_buffer)
    assert app._read_upload(empty_buffer.getvalue(), "empty.xlsx").empty


def test_parse_holidays_accepts_both_date_orders() -> None:
    assert app._parse_holidays("") == ([], 0)
    assert app._parse_holidays("03/31/2025, 2025-12-25") == (
        [pd.Timestamp("2025-03-31"), pd.Timestamp("2025-12-25")],
        0,
    )
    assert app._parse_holidays("12/25/2025; 11/09/2025") == (
        [pd.Timestamp("2025-12-25"), pd.Timestamp("2025-11-09")],
        0,
    )
    valid, invalid = app._parse_holidays("not-a-date, 2025-01-01")
    assert valid == [pd.Timestamp("2025-01-01")]
    assert invalid == 1


def test_date_bounds_normalizes_partial_ranges() -> None:
    day = date(2025, 12, 1)
    next_day = date(2025, 12, 2)

    assert app._date_bounds(None) == (None, None)
    assert app._date_bounds(day) == (day, day)
    assert app._date_bounds((day,)) == (day, day)
    assert app._date_bounds([day, next_day]) == (day, next_day)
    assert app._date_bounds(()) == (None, None)


def test_groq_keys_live_in_session_and_stay_masked() -> None:
    test = AppTest.from_file(str(APP_PATH), default_timeout=60)
    test.run()
    first = "gsk_abcdEFGH1234567890abcd"
    second = "gsk_wxyzQRST0987654321wxyz"
    keys = f"{first}\n{second}"

    input_box = next(item for item in test.text_input if item.key == "groq_key_input")
    input_box.set_value(keys).run()
    next(button for button in test.button if button.label == "Add key").click().run()

    assert test.session_state["groq_keys"] == [first, second]
    assert test.session_state["groq_key_input"] == ""
    captions = "\n".join(item.value for item in test.caption)
    assert "gsk_...abcd" in captions
    assert "gsk_...wxyz" in captions
    assert first not in captions
    assert second not in captions
    assert all(first not in item.value for item in test.markdown)

    next(button for button in test.button if button.key == "remove_key_0").click().run()
    assert test.session_state["groq_keys"] == [second]

    next(button for button in test.button if button.label == "Clear all keys").click().run()
    assert test.session_state["groq_keys"] == []


def test_formatting_helpers() -> None:
    assert app._text(None, "fallback") == "fallback"
    assert app._text("  value  ") == "value"
    assert app._text(pd.NA, "fallback") == "fallback"
    assert app._money(1_234.5, lakh_crore=True) == "Rs. 1,234.50"
    assert app._money(1_250_000, lakh_crore=True) == "Rs. 12,50,000"
    assert app._money(1_250_000, lakh_crore=False) == "Rs. 1,250,000"
    assert app._money("bad", lakh_crore=True) == "Rs. 0"
    assert app._compact_money(999) == "Rs. 999"
    assert app._compact_money(1_500) == "Rs. 1,500"
    assert app._compact_money(2_500_000) == "Rs. 25.0 Lac"
    assert app._compact_money("bad") == "Rs. 0"
    assert app._go_config() == {"displayModeBar": False, "responsive": True}


def test_row_helpers(checked_demo: pd.DataFrame) -> None:
    row = checked_demo[checked_demo["flag_count"] > 0].iloc[0]
    flags = app._flags_text(row)
    assert flags
    active = [column for column in FLAG_COLUMNS if row[column]]
    assert len(flags.split(", ")) == len(active)

    assert "#f87171" in app._risk_cell("Critical")
    assert "#34d399" in app._risk_cell("nonsense")


def test_csv_export_uses_rupees_and_mm_dd_yyyy(checked_demo: pd.DataFrame) -> None:
    flagged = checked_demo[checked_demo["flag_count"] > 0]

    csv_frame = app._csv_frame(flagged)

    assert "Amount (Rs.)" in csv_frame.columns
    assert all(value.startswith("Rs. ") for value in csv_frame["Amount (Rs.)"])
    assert csv_frame["Date"].str.fullmatch(r"\d{2}/\d{2}/\d{4}").all()
    assert GROUND_TRUTH_COLUMN not in csv_frame.columns
