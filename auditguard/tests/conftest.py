"""Shared pytest fixtures and import path setup for AuditGuard."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from data_generator import generate_ledger  # noqa: E402
from detection import REQUIRED_COLUMNS, build_summary, run_all_checks  # noqa: E402
from utils import ISLAMIC_HOLIDAY_SUGGESTIONS, pakistan_holidays  # noqa: E402

_DEFAULT_ROW = {
    "Date": pd.Timestamp("2025-03-03"),
    "Account": "Office Expense",
    "Vendor": "Vendor A",
    "Description": "Office supplies",
    "Amount": 1_234.56,
    "PostedBy": "Alice",
    "ApprovedBy": "Bob",
}


@pytest.fixture(scope="session")
def demo_ledger() -> pd.DataFrame:
    """Return the reproducible 606-entry labelled Karachi ledger."""
    return generate_ledger()


@pytest.fixture(scope="session")
def demo_holidays() -> list[pd.Timestamp]:
    """Return the fixed and moon-sighting Pakistan holidays used by the app."""
    fixed = [value for value, _ in pakistan_holidays(2025)]
    islamic = [pd.Timestamp(2025, month, day) for (month, day), _ in ISLAMIC_HOLIDAY_SUGGESTIONS]
    return fixed + islamic


@pytest.fixture(scope="session")
def checked_demo(demo_ledger: pd.DataFrame, demo_holidays: list[pd.Timestamp]) -> pd.DataFrame:
    """Return the demo ledger after every detection rule has run."""
    return run_all_checks(demo_ledger, holidays=demo_holidays)


@pytest.fixture(scope="session")
def summary_demo(checked_demo: pd.DataFrame) -> dict[str, object]:
    """Return the dashboard summary for the demo ledger."""
    return build_summary(checked_demo)


@pytest.fixture
def make_ledger() -> Callable[..., pd.DataFrame]:
    """Return a factory that builds small, valid ledger frames from overrides."""

    def _make(rows: list[dict[str, object]]) -> pd.DataFrame:
        records = []
        for position, overrides in enumerate(rows, start=1):
            record = {**_DEFAULT_ROW, "EntryID": f"E{position:03d}"}
            record.update(overrides)
            records.append(record)
        return pd.DataFrame(records, columns=list(REQUIRED_COLUMNS))

    return _make
