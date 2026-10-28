"""Synthetic Karachi ledger generator for AuditGuard demos and accuracy tests.

``generate_ledger`` builds twelve months of 2025 bookkeeping data for a
mid-sized Karachi company, then injects a fixed, labelled set of anomalies.
The default ledger contains 606 rows:

* 549 ``Clean`` rows (weekday, non-holiday, no round amount, no self-approval,
  and no repeated vendor + amount inside seven days);
* 51 single-rule anomalies: 6 duplicate pairs (12 rows, both labelled
  ``Duplicate``), 5 round amounts, 5 weekend postings, 6 just-below-limit,
  5 self-approvals, and all 18 rows of ``Madina Traders`` labelled
  ``BenfordManip``;
* 6 ``MultiRule`` rows that trip two or three rules and reach High/Critical.

Run ``python data_generator.py`` to write the labelled and blind workbooks to
``data/``.
"""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from detection import ANOMALY_LABELS, CLEAN_LABEL, GROUND_TRUTH_COLUMN, REQUIRED_COLUMNS
from utils import ISLAMIC_HOLIDAY_SUGGESTIONS, PAKISTAN_FIXED_HOLIDAYS, pakistan_holidays

# ---------------------------------------------------------------------------
# Reference data
# ---------------------------------------------------------------------------

VENDOR_ACCOUNTS: dict[str, str] = {
    "Madina Traders": "Office Expense",
    "Saddar Stationery House": "Office Expense",
    "Clifton Office Supplies": "Office Expense",
    "Gulshan Paper Mart": "Office Expense",
    "Pearl Property Rentals": "Rent",
    "Clifton Heights Realty": "Rent",
    "K-Electric": "Utilities",
    "Karachi Water Board": "Utilities",
    "Sui Southern Gas": "Utilities",
    "Shaheen Travels": "Travel",
    "Indus Air Services": "Travel",
    "Systems Pakistan": "Software",
    "CloudTech Karachi": "Software",
    "SecureNet Solutions": "Software",
    "Al-Noor Facilities": "Repairs",
    "Saddar Maintenance Co.": "Repairs",
    "Green Acres Landscaping": "Repairs",
    "Apex Consulting Karachi": "Consulting",
    "Sterling Advisory Pakistan": "Consulting",
    "Indus Steel & Materials": "Raw Materials",
    "Port Qasim Supplies": "Raw Materials",
    "TechHarbor Components": "Raw Materials",
    "Pixel Media Karachi": "Marketing",
    "BlueWave Advertising": "Marketing",
    "Harbor Point Insurance": "Insurance",
}

ACCOUNTS = tuple(dict.fromkeys(VENDOR_ACCOUNTS.values()))
EMPLOYEES = (
    "Ayesha Khan",
    "Bilal Ahmed",
    "Fatima Noor",
    "Hamza Sheikh",
    "Sana Iqbal",
    "Usman Tariq",
)

ACCOUNT_DESCRIPTIONS: dict[str, tuple[str, ...]] = {
    "Office Expense": (
        "Office supplies restock — paper, toner, and stationery",
        "Printer consumables and desk accessories for the finance floor",
        "Quarterly office consumables replenishment",
    ),
    "Rent": (
        "Monthly lease payment for head-office premises",
        "Rent instalment for the Clifton office suite",
        "Lease payment covering office and storage space",
    ),
    "Utilities": (
        "Electricity and water charges for the month",
        "Monthly power and water utility billing",
        "Utility services invoice — electricity and waste water",
    ),
    "Travel": (
        "Employee travel booking — flights and hotel",
        "Client visit travel: airfare and accommodation",
        "Conference travel expenses for the sales team",
    ),
    "Software": (
        "Annual software licence renewal",
        "SaaS subscription and seat expansion",
        "Enterprise software maintenance and support",
    ),
    "Repairs": (
        "Emergency HVAC repair and maintenance service",
        "Building repairs — plumbing and electrical",
        "Preventive maintenance visit and spare parts",
    ),
    "Consulting": (
        "Advisory services — process improvement engagement",
        "Consulting fees for finance transformation review",
        "External advisory support for internal controls",
    ),
    "Raw Materials": (
        "Raw material batch purchase — steel and components",
        "Production inputs: alloy stock and fasteners",
        "Bulk materials order for the assembly line",
    ),
    "Marketing": (
        "Digital marketing campaign — social and social search ads",
        "Brand campaign production and media placement",
        "Event sponsorship and promotional print run",
    ),
    "Insurance": (
        "Quarterly commercial insurance premium",
        "Property and liability insurance instalment",
        "Corporate insurance renewal premium",
    ),
}

BENFORD_VENDOR = "Madina Traders"
RENT_VENDOR = "Pearl Property Rentals"
BENFORD_VENDOR_ROWS = 18
RENT_VENDOR_ROWS = 12
DUPLICATE_PAIRS = 6
DUPLICATE_ROWS = DUPLICATE_PAIRS * 2
ROUND_COUNT = 5
WEEKEND_COUNT = 5
THRESHOLD_COUNT = 6
SELF_APPROVAL_COUNT = 5
SINGLE_ANOMALY_ROWS = DUPLICATE_ROWS + ROUND_COUNT + WEEKEND_COUNT + THRESHOLD_COUNT + SELF_APPROVAL_COUNT + BENFORD_VENDOR_ROWS
MULTIRULE_COUNT = 6
MULTIRULE_LABEL = "MultiRule"
DEFAULT_ENTRIES = 606
CLEAN_ROWS = DEFAULT_ENTRIES - SINGLE_ANOMALY_ROWS - MULTIRULE_COUNT

ROUND_AMOUNTS = (25_000.0, 50_000.0, 75_000.0, 120_000.0, 200_000.0)
RENT_AMOUNT = 185_432.50
APPROVAL_LIMIT = 500_000.0

HOLIDAY_DATES_2025 = tuple(
    [pd.Timestamp(2025, month, day) for (month, day), _ in PAKISTAN_FIXED_HOLIDAYS]
    + [
        pd.Timestamp(2025, month, day)
        for (month, day), _ in ISLAMIC_HOLIDAY_SUGGESTIONS
    ]
)

DATASET_NAME = "AuditGuard_Karachi_Dataset.xlsx"
BLIND_DATASET_NAME = "AuditGuard_Karachi_Dataset_blind.xlsx"
DATA_DIR = Path(__file__).resolve().parent / "data"


# ---------------------------------------------------------------------------
# Clean ledger
# ---------------------------------------------------------------------------


def _business_days() -> pd.DatetimeIndex:
    """Return every weekday in 2025 that is not a configured holiday."""
    days = pd.bdate_range("2025-01-01", "2025-12-31")
    holidays = set(HOLIDAY_DATES_2025)
    return pd.DatetimeIndex([day for day in days if day not in holidays])


def _first_working_day(year: int, month: int) -> pd.Timestamp:
    """Return the first weekday of a month that is not a holiday."""
    holidays = set(HOLIDAY_DATES_2025)
    day = pd.Timestamp(year, month, 1)
    while day.dayofweek >= 5 or day in holidays:
        day += timedelta(days=1)
    return day


def _vendor_column(rng: np.random.Generator, n: int) -> np.ndarray:
    """Allocate fixed Benford/rent vendors and balance the remaining vendors."""
    others = [
        vendor
        for vendor in VENDOR_ACCOUNTS
        if vendor not in (BENFORD_VENDOR, RENT_VENDOR)
    ]
    special = BENFORD_VENDOR_ROWS + RENT_VENDOR_ROWS
    if n < special + len(others):
        raise ValueError("The ledger is too small to hold the required vendors.")
    remaining = n - special
    balanced = [others[index % len(others)] for index in range(remaining)]
    vendors = np.array(
        [BENFORD_VENDOR] * BENFORD_VENDOR_ROWS
        + [RENT_VENDOR] * RENT_VENDOR_ROWS
        + balanced,
        dtype=object,
    )
    rng.shuffle(vendors)
    return vendors


def _clean_amounts(rng: np.random.Generator, n: int) -> np.ndarray:
    """Return log-normal PKR amounts between 1,000 and 380,000, never round."""
    raw = rng.lognormal(mean=np.log(38_000.0), sigma=0.85, size=n)
    amounts = np.clip(np.round(raw, 2), 1_000.0, 379_999.99)
    remainder = np.mod(amounts, 1000.0)
    round_mask = (remainder < 0.005) | ((1000.0 - remainder) < 0.005)
    amounts[round_mask] += 0.37
    return np.round(np.clip(amounts, 1_000.0, 379_999.99), 2)


def _fabricated_amounts(rng: np.random.Generator, count: int) -> list[float]:
    """Return non-round amounts whose first digit is always 5-9."""
    values: list[float] = []
    while len(values) < count:
        digit = int(rng.integers(5, 10))
        magnitude = 10 ** int(rng.integers(3, 5))
        value = digit * magnitude + float(rng.uniform(0, magnitude))
        value = round(min(value, 379_000.0), 2)
        remainder = value % 1000
        if remainder < 0.005 or 1000 - remainder < 0.005:
            value = round(value + 0.41, 2)
        if value not in values:
            values.append(value)
    return values


def _clean_frame(rng: np.random.Generator, n: int) -> pd.DataFrame:
    """Build the baseline clean ledger before any anomalies are injected."""
    vendors = _vendor_column(rng, n)
    accounts = np.array([VENDOR_ACCOUNTS[vendor] for vendor in vendors], dtype=object)
    business_days = _business_days()
    dates = pd.to_datetime(rng.choice(business_days, size=n)).normalize().to_numpy()
    amounts = _clean_amounts(rng, n)

    rent_positions = np.flatnonzero(vendors == RENT_VENDOR).tolist()
    for month, position in zip(range(1, 13), rent_positions):
        dates[position] = _first_working_day(2025, month)
        amounts[position] = RENT_AMOUNT

    benford_positions = np.flatnonzero(vendors == BENFORD_VENDOR).tolist()
    fabricated = _fabricated_amounts(rng, len(benford_positions))
    for position, amount in zip(benford_positions, fabricated):
        amounts[position] = amount
    descriptions = np.array(
        [
            ACCOUNT_DESCRIPTIONS[account][
                int(rng.integers(len(ACCOUNT_DESCRIPTIONS[account])))
            ]
            for account in accounts
        ],
        dtype=object,
    )
    for position in rng.choice(n, size=max(1, n // 6), replace=False).tolist():
        descriptions[position] = (
            f"{descriptions[position]} — invoice INV-2025-{1000 + position:04d}"
        )

    posted_by = rng.choice(EMPLOYEES, size=n)
    approved_by = np.empty(n, dtype=object)
    for position, poster in enumerate(posted_by):
        alternatives = [name for name in EMPLOYEES if name != poster]
        approved_by[position] = alternatives[int(rng.integers(len(alternatives)))]

    frame = pd.DataFrame(
        {
            "EntryID": [f"ENT-{position + 1:04d}" for position in range(n)],
            "Date": pd.to_datetime(dates).normalize(),
            "Account": accounts,
            "Vendor": vendors,
            "Description": descriptions,
            "Amount": amounts,
            "PostedBy": posted_by,
            "ApprovedBy": approved_by,
            GROUND_TRUTH_COLUMN: CLEAN_LABEL,
        }
    )
    frame.loc[frame["Vendor"] == BENFORD_VENDOR, GROUND_TRUTH_COLUMN] = "BenfordManip"
    return _resolve_clean_collisions(frame)


def _resolve_clean_collisions(frame: pd.DataFrame) -> pd.DataFrame:
    """Nudge amounts so no clean vendor repeats an amount within seven days."""
    work = frame.sort_values(["Vendor", "Date"], kind="stable")
    for _, group in work.groupby("Vendor", sort=False):
        used: list[tuple[pd.Timestamp, float]] = []
        for row_index, row in group.iterrows():
            date = pd.Timestamp(row["Date"])
            amount = float(row["Amount"])
            if row["Vendor"] == RENT_VENDOR or row["Vendor"] == BENFORD_VENDOR:
                used.append((date, amount))
                continue
            for previous_date, previous_amount in used:
                if abs((date - previous_date).days) <= 7 and abs(amount - previous_amount) < 0.005:
                    amount = round(amount + 0.13, 2)
                    while amount % 1000 < 0.005:
                        amount = round(amount + 0.13, 2)
            frame.at[row_index, "Amount"] = amount
            used.append((date, amount))
    return frame


# ---------------------------------------------------------------------------
# Single-rule anomaly injection
# ---------------------------------------------------------------------------


def _next_business_day(date: pd.Timestamp) -> pd.Timestamp:
    """Move a date forward to the next weekday that is not a holiday."""
    holidays = set(HOLIDAY_DATES_2025)
    candidate = pd.Timestamp(date)
    while candidate.dayofweek >= 5 or candidate in holidays:
        candidate += timedelta(days=1)
    return candidate


def _weekend_date(rng: np.random.Generator) -> pd.Timestamp:
    """Return a Saturday or Sunday in 2025 that is not a configured holiday."""
    while True:
        date = pd.Timestamp("2025-01-01") + timedelta(
            days=int(rng.integers(0, 365))
        )
        if date.dayofweek >= 5 and date not in set(HOLIDAY_DATES_2025):
            return date


def _inject_duplicates(
    frame: pd.DataFrame,
    rng: np.random.Generator,
    pool: list[int],
    used: set[int],
) -> None:
    """Copy six clean postings onto later dates and label both rows."""
    cursor = 0
    pairs = 0
    while pairs < DUPLICATE_PAIRS and cursor < len(pool) - 1:
        source = pool[cursor]
        cursor += 1
        if source in used:
            continue
        source_date = pd.Timestamp(frame.at[source, "Date"])
        if source_date > pd.Timestamp("2025-12-20"):
            continue
        target = None
        for candidate in pool[cursor:]:
            if candidate not in used and candidate != source:
                target = candidate
                break
        if target is None:
            break

        injection_date = _next_business_day(
            source_date + timedelta(days=int(rng.integers(1, 6)))
        )
        for column in (
            "Account",
            "Vendor",
            "Description",
            "Amount",
            "PostedBy",
            "ApprovedBy",
        ):
            frame.at[target, column] = frame.at[source, column]
        frame.at[target, "Date"] = injection_date
        frame.at[target, GROUND_TRUTH_COLUMN] = "Duplicate"
        frame.at[source, GROUND_TRUTH_COLUMN] = "Duplicate"

        if pairs == 0:
            reference = " — invoice INV-2025-0142"
            frame.at[source, "Description"] = f"{frame.at[source, 'Description']}{reference}"
            frame.at[target, "Description"] = f"{frame.at[target, 'Description']}{reference}"

        used.add(source)
        used.add(target)
        pairs += 1


def _inject_round(
    frame: pd.DataFrame,
    pool: list[int],
    used: set[int],
) -> None:
    """Set exact round amounts on clean weekday postings."""
    cursor = 0
    injected = 0
    while injected < ROUND_COUNT and cursor < len(pool):
        target = pool[cursor]
        cursor += 1
        if target in used:
            continue
        frame.at[target, "Amount"] = ROUND_AMOUNTS[injected]
        frame.at[target, GROUND_TRUTH_COLUMN] = "RoundAmount"
        used.add(target)
        injected += 1


def _inject_weekend(
    frame: pd.DataFrame,
    rng: np.random.Generator,
    pool: list[int],
    used: set[int],
) -> None:
    """Move clean postings onto a weekend day."""
    cursor = 0
    injected = 0
    while injected < WEEKEND_COUNT and cursor < len(pool):
        target = pool[cursor]
        cursor += 1
        if target in used:
            continue
        frame.at[target, "Date"] = _weekend_date(rng)
        frame.at[target, GROUND_TRUTH_COLUMN] = "Weekend"
        used.add(target)
        injected += 1


def _inject_threshold(
    frame: pd.DataFrame,
    rng: np.random.Generator,
    pool: list[int],
    used: set[int],
    approval_limit: float,
) -> None:
    """Set amounts between 95% and 99.9% of the approval limit."""
    lower = approval_limit * 0.95
    upper = approval_limit * 0.999
    cursor = 0
    injected = 0
    while injected < THRESHOLD_COUNT and cursor < len(pool):
        target = pool[cursor]
        cursor += 1
        if target in used:
            continue
        amount = round(float(rng.uniform(lower, upper)), 2)
        if amount % 1000 < 0.005 or 1000 - amount % 1000 < 0.005:
            amount = round(amount + 0.17, 2)
        frame.at[target, "Amount"] = amount
        frame.at[target, GROUND_TRUTH_COLUMN] = "JustBelowLimit"
        used.add(target)
        injected += 1


def _inject_self_approval(
    frame: pd.DataFrame,
    pool: list[int],
    used: set[int],
) -> None:
    """Make the poster their own approver on clean weekday postings."""
    cursor = 0
    injected = 0
    while injected < SELF_APPROVAL_COUNT and cursor < len(pool):
        target = pool[cursor]
        cursor += 1
        if target in used:
            continue
        frame.at[target, "ApprovedBy"] = frame.at[target, "PostedBy"]
        frame.at[target, GROUND_TRUTH_COLUMN] = "SelfApproval"
        used.add(target)
        injected += 1


def _inject_single_anomalies(
    frame: pd.DataFrame,
    rng: np.random.Generator,
    approval_limit: float,
) -> pd.DataFrame:
    """Inject the 51 single-rule labelled anomalies."""
    eligible = [
        int(index)
        for index in frame.index
        if frame.at[index, "Vendor"] not in (BENFORD_VENDOR, RENT_VENDOR)
    ]
    pool = [int(index) for index in rng.permutation(eligible)]
    used: set[int] = set()

    _inject_duplicates(frame, rng, pool, used)
    _inject_round(frame, pool, used)
    _inject_weekend(frame, rng, pool, used)
    _inject_threshold(frame, rng, pool, used, approval_limit)
    _inject_self_approval(frame, pool, used)
    return frame


# ---------------------------------------------------------------------------
# Multi-rule rows
# ---------------------------------------------------------------------------


def _multi_rule_frame(
    rng: np.random.Generator,
    start_position: int,
    approval_limit: float,
) -> pd.DataFrame:
    """Build six rows that trip two or three rules (High/Critical)."""
    lower = approval_limit * 0.95
    upper = approval_limit * 0.999
    weekend_dates = [
        pd.Timestamp("2025-11-01"),  # Saturday
        pd.Timestamp("2025-11-02"),  # Sunday
        pd.Timestamp("2025-11-08"),  # Saturday
        pd.Timestamp("2025-11-15"),  # Saturday
    ]
    weekday_dates = [pd.Timestamp("2025-11-03"), pd.Timestamp("2025-11-04")]

    specs = [
        # 2 x SelfApproval + Weekend + JustBelowLimit = Critical (70)
        ("Apex Consulting Karachi", "Consulting", weekend_dates[0], round(float(rng.uniform(lower, upper)), 2)),
        ("Sterling Advisory Pakistan", "Consulting", weekend_dates[1], round(float(rng.uniform(lower, upper)), 2)),
        # 2 x SelfApproval + JustBelowLimit = High (60)
        ("Indus Steel & Materials", "Raw Materials", weekday_dates[0], round(float(rng.uniform(lower, upper)), 2)),
        ("Port Qasim Supplies", "Raw Materials", weekday_dates[1], round(float(rng.uniform(lower, upper)), 2)),
        # 2 x SelfApproval + RoundAmount + Weekend = High (60)
        ("Pixel Media Karachi", "Marketing", weekend_dates[2], 84_000.0),
        ("BlueWave Advertising", "Marketing", weekend_dates[3], 96_000.0),
    ]

    rows = []
    for offset, (vendor, account, date, amount) in enumerate(specs, start=1):
        poster = str(rng.choice(EMPLOYEES))
        rows.append(
            {
                "EntryID": f"ENT-{start_position + offset:04d}",
                "Date": date,
                "Account": account,
                "Vendor": vendor,
                "Description": f"{ACCOUNT_DESCRIPTIONS[account][0]} — invoice INV-2025-9{offset:03d}",
                "Amount": amount,
                "PostedBy": poster,
                "ApprovedBy": poster,
                GROUND_TRUTH_COLUMN: MULTIRULE_LABEL,
            }
        )
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def generate_ledger(
    n: int = DEFAULT_ENTRIES,
    seed: int = 42,
    approval_limit: float = APPROVAL_LIMIT,
) -> pd.DataFrame:
    """Generate a labelled Karachi ledger with exactly ``n`` entries.

    The default 606-row sample holds 549 Clean rows, 51 single-rule anomalies,
    and 6 MultiRule rows. ``n`` includes the six MultiRule rows when the ledger
    is large enough to hold the fixed anomaly sample.
    """
    if n < 120:
        raise ValueError("n must be at least 120 to hold the labelled anomaly sample.")
    if approval_limit <= 0:
        raise ValueError("approval_limit must be positive.")

    rng = np.random.default_rng(seed)
    multi_rows = MULTIRULE_COUNT if n >= 200 else 0
    base_n = n - multi_rows
    frame = _clean_frame(rng, base_n)
    frame = _inject_single_anomalies(frame, rng, approval_limit)
    if multi_rows:
        multi = _multi_rule_frame(rng, base_n, approval_limit)
        frame = pd.concat([frame, multi], ignore_index=True)
    frame[GROUND_TRUTH_COLUMN] = frame[GROUND_TRUTH_COLUMN].fillna(CLEAN_LABEL)
    return frame[list(REQUIRED_COLUMNS) + [GROUND_TRUTH_COLUMN]]


def holidays_frame() -> pd.DataFrame:
    """Return the Pakistan holidays sheet rows with names and notes."""
    rows = []
    for (month, day), name in PAKISTAN_FIXED_HOLIDAYS:
        rows.append(
            {
                "Date": pd.Timestamp(2025, month, day),
                "Holiday": name,
                "Type": "Pakistan public holiday",
            }
        )
    for (month, day), name in ISLAMIC_HOLIDAY_SUGGESTIONS:
        rows.append(
            {
                "Date": pd.Timestamp(2025, month, day),
                "Holiday": name,
                "Type": "Moon-sighting dependent — verify before use",
            }
        )
    return pd.DataFrame(rows)


def about_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Return the About sheet summary for the labelled dataset."""
    counts = Counter(frame[GROUND_TRUTH_COLUMN])
    rows = [
        ("Dataset", "AuditGuard Karachi demo ledger"),
        ("Prepared in", "Karachi, Pakistan (Asia/Karachi)"),
        ("Year", 2025),
        ("Currency", "Pakistani Rupee (PKR, Rs.)"),
        ("Total rows", len(frame)),
        ("Clean rows", counts.get(CLEAN_LABEL, 0)),
        ("Duplicate rows (6 pairs)", counts.get("Duplicate", 0)),
        ("RoundAmount rows", counts.get("RoundAmount", 0)),
        ("Weekend rows", counts.get("Weekend", 0)),
        ("JustBelowLimit rows", counts.get("JustBelowLimit", 0)),
        ("SelfApproval rows", counts.get("SelfApproval", 0)),
        ("BenfordManip rows (Madina Traders)", counts.get("BenfordManip", 0)),
        ("MultiRule rows", counts.get(MULTIRULE_LABEL, 0)),
        ("Approval limit", "Rs. 500,000"),
        ("Labelled anomalies", sum(counts.get(label, 0) for label in ANOMALY_LABELS) + counts.get(MULTIRULE_LABEL, 0)),
        (
            "Note",
            "Islamic holiday dates depend on moon sighting and must be verified. "
            "Journal-entry testing for fraud risk is a concept from ISA 240.",
        ),
    ]
    return pd.DataFrame(rows, columns=["Item", "Value"])


def write_datasets(directory: str | Path | None = None) -> tuple[Path, Path]:
    """Write the labelled and blind Karachi workbooks and return their paths."""
    target = Path(directory) if directory is not None else DATA_DIR
    target.mkdir(parents=True, exist_ok=True)
    frame = generate_ledger()

    labelled_path = target / DATASET_NAME
    blind_path = target / BLIND_DATASET_NAME

    with pd.ExcelWriter(labelled_path, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Ledger", index=False)
        holidays_frame().to_excel(writer, sheet_name="Pakistan_Holidays_2025", index=False)
        about_frame(frame).to_excel(writer, sheet_name="About", index=False)

    with pd.ExcelWriter(blind_path, engine="openpyxl") as writer:
        frame.drop(columns=[GROUND_TRUTH_COLUMN]).to_excel(
            writer, sheet_name="Ledger", index=False
        )

    return labelled_path, blind_path


def main() -> None:
    """Write the Karachi datasets and print the ground-truth counts."""
    labelled_path, blind_path = write_datasets()
    frame = generate_ledger()
    counts = Counter(frame[GROUND_TRUTH_COLUMN])

    print(f"Generated {len(frame):,} entries across 2025.")
    print(f"Labelled workbook: {labelled_path}")
    print(f"Blind workbook:    {blind_path}")
    print("Ground-truth counts:")
    for label in (*ANOMALY_LABELS, MULTIRULE_LABEL, CLEAN_LABEL):
        print(f"  {label:<14} {counts.get(label, 0):>4}")


if __name__ == "__main__":
    main()
