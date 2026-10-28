"""Tests for ledger preparation, the six rules, scoring, and the summary."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from detection import (
    ALL_LABELS,
    BENFORD_ALPHA,
    CLEAN_LABEL,
    DEFAULT_APPROVAL_LIMIT,
    DEFAULT_ROUND_THRESHOLD,
    DEFAULT_WEIGHTS,
    FLAG_COLUMNS,
    GROUND_TRUTH_COLUMN,
    MULTIRULE_LABEL,
    REQUIRED_COLUMNS,
    ambiguous_date_count,
    benford_table,
    build_summary,
    check_benford,
    check_duplicates,
    check_round,
    check_self_approval,
    check_threshold,
    check_weekend,
    extract_invoice_reference,
    prepare_ledger,
    risk_level,
    run_all_checks,
    score_risk,
    validate_input,
    validate_schema,
)
from utils import DEFAULT_WEEKEND_DAYS, format_date, pakistan_holidays


def test_constants_match_the_fixed_schema() -> None:
    assert REQUIRED_COLUMNS == (
        "EntryID",
        "Date",
        "Account",
        "Vendor",
        "Description",
        "Amount",
        "PostedBy",
        "ApprovedBy",
    )
    assert GROUND_TRUTH_COLUMN == "GroundTruth"
    assert FLAG_COLUMNS == (
        "flag_duplicate",
        "flag_round",
        "flag_weekend",
        "flag_threshold",
        "flag_self_approval",
        "flag_benford",
    )
    assert DEFAULT_APPROVAL_LIMIT == 500_000.0
    assert DEFAULT_ROUND_THRESHOLD == 1_000.0
    assert DEFAULT_WEEKEND_DAYS == (5, 6)
    assert DEFAULT_WEIGHTS == {
        "flag_self_approval": 35,
        "flag_duplicate": 30,
        "flag_threshold": 25,
        "flag_benford": 20,
        "flag_round": 15,
        "flag_weekend": 10,
    }
    assert ALL_LABELS[-1] == MULTIRULE_LABEL
    assert CLEAN_LABEL == "Clean"


# ---------------------------------------------------------------------------
# Input preparation
# ---------------------------------------------------------------------------


def test_prepare_ledger_trims_text_and_parses_dates() -> None:
    frame = pd.DataFrame(
        {
            "EntryID": [" E1 "],
            "Date": ["03/14/2025"],
            "Account": [" Office Expense "],
            "Vendor": [" Vendor A "],
            "Description": ["  Office supplies  "],
            "Amount": ["1234.50"],
            "PostedBy": [" Alice "],
            "ApprovedBy": [" Bob "],
        }
    )

    prepared = prepare_ledger(frame, input_date_format="MM/DD/YYYY")

    assert prepared.loc[0, "EntryID"] == "E1"
    assert prepared.loc[0, "Vendor"] == "Vendor A"
    assert prepared.loc[0, "Description"] == "Office supplies"
    assert prepared.loc[0, "Date"] == pd.Timestamp("2025-03-14")
    assert prepared.loc[0, "Amount"] == pytest.approx(1_234.50)


def test_prepare_ledger_respects_mm_dd_and_dd_mm_choices() -> None:
    frame = pd.DataFrame({"Date": ["05/06/2025"], "Amount": [10.0]})

    mm_dd = prepare_ledger(frame, input_date_format="MM/DD/YYYY")
    dd_mm = prepare_ledger(frame, input_date_format="DD/MM/YYYY")
    auto = prepare_ledger(frame, input_date_format="Auto-detect")

    assert mm_dd.loc[0, "Date"] == pd.Timestamp("2025-05-06")
    assert dd_mm.loc[0, "Date"] == pd.Timestamp("2025-06-05")
    assert auto.loc[0, "Date"] == pd.Timestamp("2025-05-06")


def test_prepare_ledger_keeps_true_excel_dates() -> None:
    frame = pd.DataFrame({"Date": pd.to_datetime(["2025-08-14"]), "Amount": [1.0]})

    prepared = prepare_ledger(frame, input_date_format="DD/MM/YYYY")

    assert prepared.loc[0, "Date"] == pd.Timestamp("2025-08-14")


def test_ambiguous_date_count_finds_swappable_slash_dates() -> None:
    series = pd.Series(["05/06/2025", "03/14/2025", "2025-01-01", "11/12/2025", None])

    assert ambiguous_date_count(series) == 2


def test_extract_invoice_reference_recognises_common_prefixes() -> None:
    assert extract_invoice_reference("Payment — invoice INV-2025-0142") == "INV-2025-0142"
    assert extract_invoice_reference("bill no PO/99881") == "PO/99881"
    assert extract_invoice_reference("Office supplies") is None
    assert extract_invoice_reference(None) is None


def test_validate_schema_and_input_report_missing_pieces(make_ledger) -> None:
    frame = make_ledger([{"Amount": 1_234.56}, {"Amount": 2_345.67}])

    assert validate_schema(frame) == []
    assert validate_schema(frame.drop(columns=["Vendor"])) == ["Vendor"]
    assert validate_schema(frame, require_ground_truth=True) == [GROUND_TRUTH_COLUMN]

    bad = frame.copy()
    bad["Date"] = "not a date"
    bad["Amount"] = "not a number"
    errors = validate_input(bad)
    assert any("no readable dates" in error for error in errors)
    assert any("not numeric" in error for error in errors)

    assert validate_input(None) == [
        "No ledger data was provided. Upload an Excel or CSV file first."
    ]
    assert validate_input(frame.head(0)) == [
        "The ledger is empty — there are no rows to audit."
    ]
    assert validate_input(frame.head(1)) == [
        "The ledger needs at least two rows to compare postings."
    ]


def test_validate_input_blocks_negative_amounts(make_ledger) -> None:
    frame = make_ledger([{"Amount": -5.0}, {"Amount": 10.0}])

    errors = validate_input(frame)

    assert errors == [
        "Amount contains 1 negative value(s); ledger amounts must be positive."
    ]


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------


def _duplicate_frame(make_ledger) -> pd.DataFrame:
    return make_ledger(
        [
            {"EntryID": "E1", "Vendor": "Vendor A", "Amount": 50_000.0, "Date": pd.Timestamp("2025-03-03")},
            {"EntryID": "E2", "Vendor": "Vendor A", "Amount": 50_000.0, "Date": pd.Timestamp("2025-03-06")},
            {"EntryID": "E3", "Vendor": "Vendor A", "Amount": 50_000.0, "Date": pd.Timestamp("2025-04-01")},
            {"EntryID": "E4", "Vendor": "Vendor B", "Amount": 50_000.0, "Date": pd.Timestamp("2025-03-04")},
        ]
    )


def test_duplicates_flag_both_rows_and_record_the_partner(make_ledger) -> None:
    frame = _duplicate_frame(make_ledger)

    flags, partner, gap = check_duplicates(frame)

    assert flags.tolist() == [True, True, False, False]
    assert partner.loc[0] == "E2"
    assert partner.loc[1] == "E1"
    assert gap.loc[0] == pytest.approx(3.0)
    assert gap.loc[1] == pytest.approx(3.0)
    assert pd.isna(partner.loc[2])


def test_duplicate_window_is_seven_days(make_ledger) -> None:
    frame = make_ledger(
        [
            {"Vendor": "Vendor A", "Amount": 50_000.0, "Date": pd.Timestamp("2025-03-03")},
            {"Vendor": "Vendor A", "Amount": 50_000.0, "Date": pd.Timestamp("2025-03-10")},
            {"Vendor": "Vendor A", "Amount": 60_000.0, "Date": pd.Timestamp("2025-03-11")},
        ]
    )

    flags, _, gap = check_duplicates(frame)

    assert flags.tolist() == [True, True, False]
    assert gap.loc[0] == pytest.approx(7.0)


def test_duplicates_ignore_different_vendors_and_amounts(make_ledger) -> None:
    frame = make_ledger(
        [
            {"Vendor": "Vendor A", "Amount": 50_000.0, "Date": pd.Timestamp("2025-03-03")},
            {"Vendor": "Vendor B", "Amount": 50_000.0, "Date": pd.Timestamp("2025-03-03")},
            {"Vendor": "Vendor A", "Amount": 50_000.01, "Date": pd.Timestamp("2025-03-03")},
        ]
    )

    flags, _, _ = check_duplicates(frame)

    assert not flags.any()


def test_round_rule_uses_threshold_and_minimum(make_ledger) -> None:
    frame = make_ledger(
        [
            {"Amount": 10_000.0},
            {"Amount": 25_000.0},
            {"Amount": 9_000.0},
            {"Amount": 10_500.0},
            {"Amount": 123_456.78},
        ]
    )

    flags = check_round(frame)

    assert flags.tolist() == [True, True, False, False, False]


def test_round_rule_validates_threshold(make_ledger) -> None:
    frame = make_ledger([{"Amount": 10_000.0}])

    with pytest.raises(ValueError):
        check_round(frame, round_threshold=0)

    assert check_round(frame, round_threshold=5_000.0).tolist() == [True]


def test_weekend_rule_supports_both_presets(make_ledger) -> None:
    frame = make_ledger(
        [
            {"Date": pd.Timestamp("2025-03-07")},  # Friday
            {"Date": pd.Timestamp("2025-03-08")},  # Saturday
            {"Date": pd.Timestamp("2025-03-09")},  # Sunday
        ]
    )

    both = check_weekend(frame, weekend_days=(5, 6))
    sunday_only = check_weekend(frame, weekend_days=(6,))

    assert both.tolist() == [False, True, True]
    assert sunday_only.tolist() == [False, False, True]


def test_weekend_rule_flags_pakistan_holidays(make_ledger) -> None:
    frame = make_ledger(
        [
            {"Date": pd.Timestamp("2025-08-14")},  # Independence Day, Thursday
            {"Date": pd.Timestamp("2025-08-15")},  # Friday, not a holiday
        ]
    )
    holidays = [value for value, _ in pakistan_holidays(2025)]

    flags = check_weekend(frame, holidays=holidays)

    assert flags.tolist() == [True, False]


def test_weekend_rule_validates_weekday_numbers(make_ledger) -> None:
    frame = make_ledger([{"Date": pd.Timestamp("2025-03-08")}])

    with pytest.raises(ValueError):
        check_weekend(frame, weekend_days=(7,))
    with pytest.raises(ValueError):
        check_weekend(frame, weekend_days=())


def test_threshold_rule_bounds_are_inclusive(make_ledger) -> None:
    frame = make_ledger(
        [
            {"Amount": 474_999.99},
            {"Amount": 475_000.0},
            {"Amount": 490_000.0},
            {"Amount": 499_950.0},
            {"Amount": 500_000.0},
        ]
    )

    flags = check_threshold(frame, approval_limit=500_000.0)

    assert flags.tolist() == [False, True, True, True, False]


def test_threshold_rule_validates_limit(make_ledger) -> None:
    frame = make_ledger([{"Amount": 10.0}])

    with pytest.raises(ValueError):
        check_threshold(frame, approval_limit=0)


def test_self_approval_is_case_and_space_insensitive(make_ledger) -> None:
    frame = make_ledger(
        [
            {"PostedBy": "Alice", "ApprovedBy": "alice "},
            {"PostedBy": "Alice", "ApprovedBy": "Bob"},
            {"PostedBy": "  ", "ApprovedBy": "  "},
        ]
    )

    assert check_self_approval(frame).tolist() == [True, False, False]


def test_benford_rule_flags_the_manipulated_vendor(checked_demo: pd.DataFrame) -> None:
    madina = checked_demo[checked_demo["Vendor"] == "Madina Traders"]

    assert len(madina) == 18
    assert madina["flag_benford"].all()
    assert madina["vendor_benford_p"].dropna().iloc[0] < BENFORD_ALPHA


def test_benford_skips_vendors_below_the_minimum(checked_demo: pd.DataFrame) -> None:
    rent = checked_demo[checked_demo["Vendor"] == "Pearl Property Rentals"]

    assert len(rent) == 12
    assert not rent["flag_benford"].any()
    assert rent["vendor_benford_p"].isna().all()


def test_benford_finds_an_obvious_fabricated_vendor() -> None:
    frame = pd.DataFrame(
        {
            "EntryID": [f"E{index:02d}" for index in range(16)],
            "Vendor": ["Suspicious Co."] * 16,
            "Amount": [98_123.45 + index * 111.11 for index in range(16)],
        }
    )

    flags, p_values = check_benford(frame)

    assert flags.all()
    assert p_values.dropna().iloc[0] < BENFORD_ALPHA


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def test_score_risk_sums_weights_and_caps_at_100() -> None:
    frame = pd.DataFrame(
        {
            "flag_duplicate": [False, True],
            "flag_round": [False, True],
            "flag_weekend": [False, True],
            "flag_threshold": [False, True],
            "flag_self_approval": [False, True],
            "flag_benford": [False, True],
        }
    )

    scores = score_risk(frame)

    assert scores.tolist() == [0, 100]


def test_score_risk_accepts_custom_weights() -> None:
    frame = pd.DataFrame(
        {
            "flag_duplicate": [True],
            "flag_round": [False],
            "flag_weekend": [False],
            "flag_threshold": [False],
            "flag_self_approval": [False],
            "flag_benford": [False],
        }
    )

    assert score_risk(frame, {"flag_duplicate": 12}).tolist() == [12]

    with pytest.raises(ValueError):
        score_risk(frame, {"unknown": 1})


def test_risk_level_boundaries() -> None:
    assert risk_level(0) == "Low"
    assert risk_level(19) == "Low"
    assert risk_level(20) == "Medium"
    assert risk_level(39) == "Medium"
    assert risk_level(40) == "High"
    assert risk_level(69) == "High"
    assert risk_level(70) == "Critical"
    assert risk_level(100) == "Critical"


# ---------------------------------------------------------------------------
# Full audit
# ---------------------------------------------------------------------------


def test_run_all_checks_returns_the_expected_demo_contract(checked_demo: pd.DataFrame) -> None:
    assert len(checked_demo) == 606
    assert checked_demo["flag_count"].gt(0).sum() == 57
    assert set(FLAG_COLUMNS).issubset(checked_demo.columns)
    assert checked_demo["risk_score"].between(0, 100).all()
    assert checked_demo["risk_level"].value_counts().to_dict() == {
        "Low": 559,
        "Medium": 41,
        "High": 4,
        "Critical": 2,
    }
    assert checked_demo["flag_duplicate"].sum() == 12
    assert checked_demo["flag_round"].sum() == 7
    assert checked_demo["flag_weekend"].sum() == 9
    assert checked_demo["flag_threshold"].sum() == 10
    assert checked_demo["flag_self_approval"].sum() == 11
    assert checked_demo["flag_benford"].sum() == 18


def test_demo_has_no_clean_entry_with_a_flag(checked_demo: pd.DataFrame) -> None:
    clean = checked_demo[checked_demo[GROUND_TRUTH_COLUMN] == CLEAN_LABEL]

    assert len(clean) == 549
    assert clean["flag_count"].sum() == 0


def test_demo_duplicate_pairs_flag_both_rows(checked_demo: pd.DataFrame) -> None:
    duplicates = checked_demo[checked_demo[GROUND_TRUTH_COLUMN] == "Duplicate"]

    assert len(duplicates) == 12
    assert duplicates["flag_duplicate"].all()
    assert duplicates["duplicate_of"].notna().all()
    assert (duplicates["duplicate_gap_days"] <= 7).all()
    assert (duplicates["flag_count"] == 1).all()

    partner_ids = set(duplicates["duplicate_of"])
    assert partner_ids <= set(duplicates["EntryID"])


def test_duplicate_reasons_cite_invoice_reference(checked_demo: pd.DataFrame) -> None:
    with_invoice = checked_demo[checked_demo["duplicate_invoice"].notna()]

    assert len(with_invoice) == 4
    for _, row in with_invoice.iterrows():
        reasons = " ".join(row["flag_reasons"])
        assert f"same invoice reference {row['duplicate_invoice']}" in reasons
        assert "Duplicate of" in reasons


def test_multi_rule_rows_reach_high_or_critical(checked_demo: pd.DataFrame) -> None:
    multi = checked_demo[checked_demo[GROUND_TRUTH_COLUMN] == MULTIRULE_LABEL]

    assert len(multi) == 6
    assert multi["flag_count"].ge(2).all()
    assert multi["risk_level"].value_counts().to_dict() == {"High": 4, "Critical": 2}
    assert multi["risk_score"].min() == 60
    assert multi["risk_score"].max() == 70


def test_reasons_use_rupees_and_mm_dd_yyyy(checked_demo: pd.DataFrame) -> None:
    flagged = checked_demo[checked_demo["flag_count"] > 0]

    for _, row in flagged.iterrows():
        reasons = " ".join(row["flag_reasons"])
        assert reasons.strip()
        assert "$" not in reasons

    duplicate = checked_demo[checked_demo["flag_duplicate"]].iloc[0]
    duplicate_reasons = " ".join(duplicate["flag_reasons"])
    assert "Rs." in duplicate_reasons
    assert format_date(duplicate["Date"]) in duplicate_reasons or "day(s) apart" in duplicate_reasons


def test_holiday_reason_names_the_configured_holiday(make_ledger) -> None:
    frame = make_ledger(
        [
            {"EntryID": "E1", "Date": pd.Timestamp("2025-08-14"), "Amount": 50_000.0},
            {"EntryID": "E2", "Date": pd.Timestamp("2025-08-15"), "Amount": 60_000.0},
        ]
    )

    checked = run_all_checks(
        frame, holidays=[value for value, _ in pakistan_holidays(2025)]
    )

    reasons = " ".join(checked.loc[0, "flag_reasons"])
    assert "configured holiday 08/14/2025" in reasons
    assert checked.loc[0, "flag_weekend"]
    assert not checked.loc[1, "flag_weekend"]


def test_sunday_only_weekend_preference_changes_the_flags(checked_demo: pd.DataFrame) -> None:
    sunday_only = run_all_checks(
        checked_demo[list(REQUIRED_COLUMNS)],
        holidays=None,
        weekend_days=(6,),
    )

    assert sunday_only["flag_weekend"].sum() < checked_demo["flag_weekend"].sum()


def test_custom_approval_limit_changes_threshold_hits(make_ledger) -> None:
    frame = make_ledger(
        [
            {"EntryID": "E1", "Amount": 190_000.0},
            {"EntryID": "E2", "Amount": 490_000.0},
            {"EntryID": "E3", "Amount": 198_000.0},
        ]
    )

    checked = run_all_checks(frame, approval_limit=200_000.0)

    assert checked["flag_threshold"].tolist() == [True, False, True]


def test_text_dates_are_parsed_with_the_selected_order(make_ledger) -> None:
    frame = make_ledger([{"EntryID": "E1"}])
    frame["Date"] = "03/14/2025"

    checked = run_all_checks(frame, input_date_format="MM/DD/YYYY")

    assert checked.loc[0, "Date"] == pd.Timestamp("2025-03-14")


def test_run_all_checks_rejects_missing_columns_and_bad_limits(make_ledger) -> None:
    frame = make_ledger([{"Amount": 1.0}])

    with pytest.raises(ValueError, match="Missing required column"):
        run_all_checks(frame.drop(columns=["Vendor"]))
    with pytest.raises(ValueError):
        run_all_checks(frame, approval_limit=0)


# ---------------------------------------------------------------------------
# Summary and Benford report
# ---------------------------------------------------------------------------


def test_build_summary_demo_numbers(summary_demo: dict[str, object]) -> None:
    assert summary_demo["total_entries"] == 606
    assert summary_demo["flagged_entries"] == 57
    assert summary_demo["flagged_pct"] == pytest.approx(57 / 606 * 100)
    assert summary_demo["amount_at_risk"] == pytest.approx(7_729_596.13)
    assert summary_demo["overall_risk_score"] == pytest.approx(47.3)
    assert summary_demo["overall_risk_level"] == "High"
    assert summary_demo["dominant_pattern"] == "Benford Deviation"
    assert summary_demo["top_vendors"][0]["vendor"] == "CloudTech Karachi"
    assert summary_demo["top_vendors"][0]["flagged_entries"] == 3


def test_build_summary_requires_a_checked_ledger(make_ledger) -> None:
    with pytest.raises(ValueError):
        build_summary(make_ledger([{"Amount": 1.0}]))


def test_build_summary_handles_zero_flags(make_ledger) -> None:
    checked = run_all_checks(
        make_ledger(
            [
                {"Vendor": "Vendor A", "Amount": 1_234.56},
                {"Vendor": "Vendor B", "Amount": 2_345.67},
            ]
        )
    )

    summary = build_summary(checked)

    assert summary["flagged_entries"] == 0
    assert summary["flagged_pct"] == 0.0
    assert summary["amount_at_risk"] == 0.0
    assert summary["overall_risk_score"] == 0.0
    assert summary["overall_risk_level"] == "Low"
    assert summary["top_vendors"] == []
    assert summary["dominant_pattern"] == "None"


def test_benford_table_reports_digits_and_significance(checked_demo: pd.DataFrame) -> None:
    report = benford_table(checked_demo)

    assert report["n"] == 606
    assert len(report["table"]) == 9
    assert report["table"]["Count"].sum() == 606
    assert 0.0 < report["p_value"] <= 1.0
    assert report["significant"] is (report["p_value"] < BENFORD_ALPHA)

    madina = checked_demo[checked_demo["Vendor"] == "Madina Traders"]
    madina_report = benford_table(madina)
    assert madina_report["n"] == 18
    assert madina_report["p_value"] < BENFORD_ALPHA
    assert madina_report["significant"] is True


def test_benford_table_handles_no_amounts(make_ledger) -> None:
    frame = make_ledger([{"Amount": np.nan}])

    report = benford_table(frame)

    assert report["n"] == 0
    assert np.isnan(report["p_value"])
    assert report["significant"] is False


def test_format_date_is_shared_by_reasons(checked_demo: pd.DataFrame) -> None:
    row = checked_demo[checked_demo["flag_weekend"] & ~checked_demo["flag_duplicate"]].iloc[0]
    reasons = " ".join(row["flag_reasons"])

    assert format_date(row["Date"]) in reasons
