"""Tests for the deterministic explanations, actions, and executive summary."""

from __future__ import annotations

import re

import pandas as pd
import pytest

from ai_explainer import (
    explain_entry,
    generate_executive_summary,
    recommended_actions,
)
from detection import (
    CLEAN_LABEL,
    FLAG_LABELS,
    GROUND_TRUTH_COLUMN,
    build_summary,
    run_all_checks,
)
from utils import format_date

MONEY_PATTERN = re.compile(r"Rs\.\s?[\d,]+(?:\.\d{2})?")
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def _sentence_count(text: str) -> int:
    cleaned = text.replace("Rs.", "Rs").replace("Co.", "Co").replace("Ltd.", "Ltd")
    return len(SENTENCE_END.findall(cleaned))


@pytest.mark.parametrize(
    ("label", "flag", "needle"),
    [
        ("Duplicate", "flag_duplicate", "duplicate"),
        ("RoundAmount", "flag_round", "round"),
        ("Weekend", "flag_weekend", "outside normal business days"),
        ("JustBelowLimit", "flag_threshold", "approval limit"),
        ("SelfApproval", "flag_self_approval", "posted and approved"),
        ("BenfordManip", "flag_benford", "Benford"),
    ],
)
def test_each_rule_is_explained_from_its_own_fields(
    checked_demo: pd.DataFrame, label: str, flag: str, needle: str
) -> None:
    row = checked_demo[checked_demo[GROUND_TRUTH_COLUMN] == label].iloc[0]
    text = explain_entry(row)

    assert row["EntryID"] in text
    assert FLAG_LABELS[flag] in text
    assert needle.lower() in text.lower()
    assert "Rs." in text
    assert "$" not in text
    assert 2 <= _sentence_count(text) <= 3

    if label == "Duplicate":
        assert row["duplicate_of"] in text
    if label == "Weekend":
        assert format_date(row["Date"]) in text


def test_weekend_explanation_names_the_weekday(checked_demo: pd.DataFrame) -> None:
    row = checked_demo[
        (checked_demo[GROUND_TRUTH_COLUMN] == "Weekend")
    ].iloc[0]
    text = explain_entry(row)

    weekday = pd.Timestamp(row["Date"]).strftime("%A")
    assert weekday in text


def test_duplicate_explanation_mentions_a_shared_invoice(checked_demo: pd.DataFrame) -> None:
    row = checked_demo[checked_demo["duplicate_invoice"].notna()].iloc[0]
    text = explain_entry(row)

    assert row["duplicate_invoice"] in text
    assert "invoice" in text.lower()


def test_multi_flag_explanation_names_every_flag() -> None:
    row = {
        "EntryID": "E999",
        "Vendor": "Vendor A",
        "Amount": 50_000.0,
        "Date": "2025-03-08",
        "PostedBy": "Alice",
        "ApprovedBy": "Alice",
        "duplicate_of": "E001",
        "duplicate_gap_days": 2,
        "flag_duplicate": True,
        "flag_round": True,
        "flag_weekend": True,
        "flag_threshold": False,
        "flag_self_approval": True,
        "flag_benford": False,
    }
    text = explain_entry(row)

    for flag in ("Self-Approval", "Duplicate", "Round Amount", "Weekend Posting"):
        assert flag in text
    assert "E001" in text
    assert "Rs. 50,000" in text
    assert 2 <= _sentence_count(text) <= 3


def test_clean_entry_explanation_is_safe(checked_demo: pd.DataFrame) -> None:
    row = checked_demo[checked_demo["flag_count"] == 0].iloc[0]
    text = explain_entry(row)

    assert text.startswith(f"No red-flag rules were triggered for {row['EntryID']}")
    assert _sentence_count(text) == 2
    assert "Rs." not in text


def test_explanations_do_not_invent_amounts(checked_demo: pd.DataFrame) -> None:
    flagged = checked_demo[checked_demo["flag_count"] > 0]
    for _, row in flagged.iterrows():
        text = explain_entry(row)
        allowed = {round(float(row["Amount"]), 2)}
        if pd.notna(row.get("approval_limit_used")):
            allowed.add(round(float(row["approval_limit_used"]), 2))
        for token in MONEY_PATTERN.findall(text):
            value = float(token.replace("Rs.", "").replace(",", "").strip())
            assert round(value, 2) in allowed, token


def test_recommended_actions_are_bounded(checked_demo: pd.DataFrame) -> None:
    clean = checked_demo[checked_demo["flag_count"] == 0].iloc[0]
    flagged = checked_demo[checked_demo["flag_count"] > 0]

    assert len(recommended_actions(clean)) == 2
    for _, row in flagged.head(12).iterrows():
        actions = recommended_actions(row)
        assert 2 <= len(actions) <= 4
        assert len(set(actions)) == len(actions)
        assert "Rs." not in " ".join(actions)


def test_executive_summary_uses_audit_numbers(
    checked_demo: pd.DataFrame, summary_demo: dict[str, object]
) -> None:
    top_entries = checked_demo[checked_demo["flag_count"] > 0].sort_values(
        "risk_score", ascending=False
    ).head(5)
    text = generate_executive_summary(summary_demo, top_entries)

    assert "606" in text
    assert "57" in text
    assert summary_demo["overall_risk_level"] in text
    assert f"{summary_demo['overall_risk_score']:.1f}" in text
    assert "Rs." in text
    assert "$" not in text
    assert summary_demo["dominant_pattern"].lower() in text.lower()
    assert summary_demo["top_vendors"][0]["vendor"] in text
    assert top_entries.iloc[0]["EntryID"] in text
    assert 4 <= _sentence_count(text) <= 6


def test_executive_summary_handles_a_clean_ledger(make_ledger) -> None:
    checked = run_all_checks(
        make_ledger(
            [
                {"Vendor": "Vendor A", "Amount": 1_234.56},
                {"Vendor": "Vendor B", "Amount": 2_345.67},
            ]
        )
    )
    summary = build_summary(checked)
    text = generate_executive_summary(summary, checked.head(0))

    assert "0 entries (0.0%) were flagged" in text
    assert "No entry crossed a red-flag threshold" in text
    assert "Rs. 0" in text
    assert 4 <= _sentence_count(text) <= 6


def test_roman_urdu_explanation_and_actions(checked_demo: pd.DataFrame) -> None:
    row = checked_demo[checked_demo[GROUND_TRUTH_COLUMN] == "SelfApproval"].iloc[0]

    text = explain_entry(row, language="Roman Urdu")
    actions = recommended_actions(row, language="Roman Urdu")

    assert "red flag" in text
    assert "khud" in text.lower()
    assert "$" not in text
    assert len(actions) == 2
    assert all("workpaper" not in action for action in actions)

    amount_row = checked_demo[checked_demo[GROUND_TRUTH_COLUMN] == "JustBelowLimit"].iloc[0]
    amount_text = explain_entry(amount_row, language="Roman Urdu")
    assert "Rs." in amount_text
    assert "$" not in amount_text


def test_roman_urdu_executive_summary(checked_demo: pd.DataFrame, summary_demo: dict[str, object]) -> None:
    top_entries = checked_demo[checked_demo["flag_count"] > 0].head(3)

    text = generate_executive_summary(
        summary_demo, top_entries, language="Roman Urdu"
    )

    assert text.startswith("AuditGuard ne 606")
    assert "Rs." in text
    assert "$" not in text
    assert 4 <= _sentence_count(text) <= 6


def test_explanations_are_deterministic(checked_demo: pd.DataFrame) -> None:
    row = checked_demo[checked_demo["flag_count"] > 0].iloc[0]

    assert explain_entry(row) == explain_entry(row)
    assert explain_entry(row, language="Roman Urdu") == explain_entry(
        row, language="Roman Urdu"
    )


def test_clean_label_constant_is_used(checked_demo: pd.DataFrame) -> None:
    assert (checked_demo[GROUND_TRUTH_COLUMN] == CLEAN_LABEL).sum() == 549
