"""Rule-based audit tests and risk scoring for AuditGuard.

The module works on a pandas DataFrame with the fixed ledger schema
(EntryID, Date, Account, Vendor, Description, Amount, PostedBy, ApprovedBy).
Every rule is a small function returning a boolean Series so the engine stays
easy to test and explain. ``run_all_checks`` combines the rules into one
audit-ready frame with flags, reasons, and a 0-100 risk score.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

import numpy as np
import pandas as pd
from scipy import stats

from utils import (
    DEFAULT_INPUT_DATE_FORMAT,
    DEFAULT_WEEKEND_DAYS,
    format_date,
    format_pkr,
)

REQUIRED_COLUMNS = (
    "EntryID",
    "Date",
    "Account",
    "Vendor",
    "Description",
    "Amount",
    "PostedBy",
    "ApprovedBy",
)
GROUND_TRUTH_COLUMN = "GroundTruth"
TEST_COLUMNS = REQUIRED_COLUMNS + (GROUND_TRUTH_COLUMN,)

TEXT_COLUMNS = ("EntryID", "Account", "Vendor", "Description", "PostedBy", "ApprovedBy")

CLEAN_LABEL = "Clean"
MULTIRULE_LABEL = "MultiRule"
ANOMALY_LABELS = (
    "Duplicate",
    "RoundAmount",
    "Weekend",
    "JustBelowLimit",
    "SelfApproval",
    "BenfordManip",
)
ALL_LABELS = ANOMALY_LABELS + (MULTIRULE_LABEL,)

FLAG_COLUMNS = (
    "flag_duplicate",
    "flag_round",
    "flag_weekend",
    "flag_threshold",
    "flag_self_approval",
    "flag_benford",
)

FLAG_LABELS = {
    "flag_duplicate": "Duplicate",
    "flag_round": "Round Amount",
    "flag_weekend": "Weekend Posting",
    "flag_threshold": "Just Below Limit",
    "flag_self_approval": "Self-Approval",
    "flag_benford": "Benford Deviation",
}

DEFAULT_WEIGHTS = {
    "flag_self_approval": 35,
    "flag_duplicate": 30,
    "flag_threshold": 25,
    "flag_benford": 20,
    "flag_round": 15,
    "flag_weekend": 10,
}

RISK_LEVELS = ("Low", "Medium", "High", "Critical")
BENFORD_EXPECTED = np.log10(1.0 + 1.0 / np.arange(1, 10))
DUPLICATE_WINDOW_DAYS = 7
MIN_BENFORD_ENTRIES = 15
BENFORD_ALPHA = 0.01
ROUND_MINIMUM = 10_000.0
THRESHOLD_LOW = 0.95
THRESHOLD_HIGH = 0.9999
DEFAULT_APPROVAL_LIMIT = 500_000.0
DEFAULT_ROUND_THRESHOLD = 1_000.0
INVOICE_PATTERN = re.compile(
    r"\b(?:INVOICE|BILL|INV|PO)[-_/# ]?\d{3,}(?:[-_/#]\d+)*\b", re.IGNORECASE
)


# ---------------------------------------------------------------------------
# Input preparation and validation
# ---------------------------------------------------------------------------


def _parse_text_dates(series: pd.Series, input_date_format: str) -> pd.Series:
    """Parse a text date column using the user's chosen format."""
    text = series.astype("object")
    if input_date_format == "DD/MM/YYYY":
        parsed = pd.to_datetime(text, errors="coerce", format="%d/%m/%Y")
    elif input_date_format == "MM/DD/YYYY":
        parsed = pd.to_datetime(text, errors="coerce", format="%m/%d/%Y")
    else:
        parsed = pd.to_datetime(text, errors="coerce", format="mixed")

    missing = parsed.isna()
    if missing.any():
        fallback = pd.to_datetime(text[missing], errors="coerce", format="mixed")
        parsed = parsed.copy()
        parsed.loc[missing] = fallback
    return parsed


def ambiguous_date_count(series: pd.Series) -> int:
    """Count slash dates whose day and month could be swapped (e.g. 05/06/2025)."""
    pattern = re.compile(r"^\s*(\d{1,2})[/-](\d{1,2})[/-](\d{2,4})\s*$")
    count = 0
    for value in series.astype("object"):
        if pd.isna(value):
            continue
        match = pattern.match(str(value))
        if not match:
            continue
        first, second = int(match.group(1)), int(match.group(2))
        if first <= 12 and second <= 12 and first != second:
            count += 1
    return count


def extract_invoice_reference(value: object) -> str | None:
    """Return an invoice/PO reference from a description, if present."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    match = INVOICE_PATTERN.search(str(value))
    return match.group(0).upper() if match else None


def validate_schema(frame: pd.DataFrame, require_ground_truth: bool = False) -> list[str]:
    """Return the names of required ledger columns that are missing."""
    if frame is None or not isinstance(frame, pd.DataFrame):
        return list(REQUIRED_COLUMNS)

    present = {str(column).strip() for column in frame.columns}
    required = list(TEST_COLUMNS if require_ground_truth else REQUIRED_COLUMNS)
    return [column for column in required if column not in present]


def prepare_ledger(
    frame: pd.DataFrame,
    input_date_format: str = DEFAULT_INPUT_DATE_FORMAT,
) -> pd.DataFrame:
    """Return a cleaned copy with trimmed text, parsed dates, and numeric amounts.

    True Excel date cells are kept as dates. Text dates are parsed with the
    chosen ``input_date_format`` (``MM/DD/YYYY``, ``DD/MM/YYYY``, or
    ``Auto-detect``), with an ISO fallback for any value that does not match.
    """
    if not isinstance(frame, pd.DataFrame):
        raise TypeError("Ledger data must be a pandas DataFrame.")

    cleaned = frame.copy()
    cleaned.columns = [str(column).strip() for column in cleaned.columns]
    cleaned = cleaned.dropna(how="all").reset_index(drop=True)

    for column in TEXT_COLUMNS:
        if column not in cleaned.columns:
            continue
        values = cleaned[column].astype("object")
        cleaned[column] = values.map(
            lambda value: value.strip() if isinstance(value, str) else value
        )
        cleaned[column] = cleaned[column].replace({"": np.nan})

    if "Date" in cleaned.columns:
        if pd.api.types.is_datetime64_any_dtype(cleaned["Date"]):
            parsed = pd.to_datetime(cleaned["Date"], errors="coerce")
        else:
            parsed = _parse_text_dates(cleaned["Date"], input_date_format)
        cleaned["Date"] = parsed.dt.normalize()
    if "Amount" in cleaned.columns:
        cleaned["Amount"] = pd.to_numeric(cleaned["Amount"], errors="coerce")

    return cleaned


def validate_input(
    frame: pd.DataFrame,
    input_date_format: str = DEFAULT_INPUT_DATE_FORMAT,
) -> list[str]:
    """Return friendly, blocking problems found in an uploaded ledger.

    Partial problems (a handful of unparseable rows) are reported by the app as
    warnings; this function only blocks an audit when the data cannot be used.
    """
    if not isinstance(frame, pd.DataFrame):
        return ["No ledger data was provided. Upload an Excel or CSV file first."]
    if frame.empty:
        return ["The ledger is empty — there are no rows to audit."]

    working = frame.copy()
    working.columns = [str(column).strip() for column in working.columns]
    missing = [column for column in REQUIRED_COLUMNS if column not in working.columns]
    if missing:
        return ["Missing required column(s): " + ", ".join(missing)]

    errors: list[str] = []

    if pd.api.types.is_datetime64_any_dtype(working["Date"]):
        dates = pd.to_datetime(working["Date"], errors="coerce")
    else:
        dates = _parse_text_dates(working["Date"], input_date_format)
    if dates.isna().all():
        errors.append(
            "The Date column contains no readable dates — use MM/DD/YYYY "
            "(for example 03/14/2025) or YYYY-MM-DD."
        )

    amounts = pd.to_numeric(working["Amount"], errors="coerce")
    if amounts.isna().all():
        errors.append(
            "The Amount column is not numeric — remove currency symbols, text, "
            "and thousands separators."
        )
    elif (amounts.dropna() < 0).any():
        negative = int((amounts.dropna() < 0).sum())
        errors.append(f"Amount contains {negative} negative value(s); ledger amounts must be positive.")

    if len(working) == 1:
        errors.append("The ledger needs at least two rows to compare postings.")

    return errors


# ---------------------------------------------------------------------------
# Individual rules
# ---------------------------------------------------------------------------


def _entry_ids(frame: pd.DataFrame) -> pd.Series:
    """Return a non-empty display identifier for every row."""
    ids = frame["EntryID"].astype("object")
    fallback = pd.Series(
        [f"ROW-{position + 1:05d}" for position in range(len(frame))],
        index=frame.index,
        dtype="object",
    )
    cleaned = ids.map(lambda value: str(value).strip() if pd.notna(value) else "")
    return cleaned.where(cleaned.ne(""), fallback)


def _leading_digits(amounts: pd.Series) -> pd.Series:
    """Return the leading digit (1-9) of each positive amount above 1."""
    values = pd.to_numeric(amounts, errors="coerce").abs()
    usable = values[values >= 1]
    exponent = np.floor(np.log10(usable.to_numpy(dtype=float)))
    digits = np.floor(usable.to_numpy(dtype=float) / np.power(10.0, exponent))
    return pd.Series(np.clip(digits, 1, 9).astype(int), index=usable.index)


def check_duplicates(
    frame: pd.DataFrame,
    window_days: int = DUPLICATE_WINDOW_DAYS,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Flag every posting that repeats the same vendor and amount within a window.

    Both rows of a duplicate pair are flagged. For each flagged row the
    ``duplicate_of`` series records the closest partner's EntryID and
    ``gap_days`` records the absolute number of days between the pair.
    """
    flags = pd.Series(False, index=frame.index, dtype=bool)
    first_id = pd.Series(np.nan, index=frame.index, dtype="object")
    gap_days = pd.Series(np.nan, index=frame.index, dtype="float")

    usable = frame["Vendor"].notna() & frame["Amount"].notna() & frame["Date"].notna()
    if not usable.any():
        return flags, first_id, gap_days

    work = pd.DataFrame(
        {
            "date": frame.loc[usable, "Date"],
            "vendor_key": frame.loc[usable, "Vendor"].astype(str).str.casefold(),
            "amount_key": frame.loc[usable, "Amount"].round(2),
            "entry_id": _entry_ids(frame).loc[usable],
        }
    )
    work = work.sort_values("date", kind="stable")

    for _, group in work.groupby(["vendor_key", "amount_key"], sort=False):
        if len(group) < 2:
            continue
        dates = group["date"].to_numpy(dtype="datetime64[ns]")
        ids = group["entry_id"].to_numpy(dtype=object)
        indices = group.index.to_numpy()
        for position in range(len(group)):
            deltas = (dates - dates[position]) / np.timedelta64(1, "D")
            window = np.where((np.abs(deltas) > 0) & (np.abs(deltas) <= window_days))[0]
            if window.size == 0:
                continue
            earlier = window[dates[window] < dates[position]]
            if earlier.size:
                partner = int(earlier[np.argmax(dates[earlier])])
            else:
                later = window[dates[window] > dates[position]]
                partner = int(later[np.argmin(dates[later])])
            flags.at[indices[position]] = True
            first_id.at[indices[position]] = ids[partner]
            gap_days.at[indices[position]] = float(abs(deltas[partner]))

    return flags, first_id, gap_days


def check_round(
    frame: pd.DataFrame,
    round_threshold: float = 1000.0,
    minimum: float = ROUND_MINIMUM,
) -> pd.Series:
    """Flag large amounts that are exact multiples of a round threshold."""
    if round_threshold <= 0:
        raise ValueError("round_threshold must be positive.")
    amounts = pd.to_numeric(frame["Amount"], errors="coerce")
    remainder = np.mod(amounts, round_threshold)
    is_multiple = (remainder.abs() < 0.005) | ((remainder - round_threshold).abs() < 0.005)
    return (amounts >= minimum) & is_multiple


def check_weekend(
    frame: pd.DataFrame,
    holidays: Iterable[object] | None = None,
    weekend_days: Iterable[int] = DEFAULT_WEEKEND_DAYS,
) -> pd.Series:
    """Flag postings dated on a configured weekend day or holiday.

    ``weekend_days`` uses Monday=0 ... Sunday=6. Pakistan commonly observes
    Saturday + Sunday (the default); some offices observe Sunday only.
    """
    days = tuple(int(day) for day in weekend_days)
    if not days or any(day < 0 or day > 6 for day in days):
        raise ValueError("weekend_days must contain weekday numbers from 0 to 6.")
    dates = pd.to_datetime(frame["Date"], errors="coerce")
    flags = dates.dt.dayofweek.isin(days)
    if holidays is not None:
        parsed = pd.to_datetime(
            pd.Series(list(holidays)), errors="coerce", format="mixed"
        ).dropna()
        if not parsed.empty:
            holiday_set = set(parsed.dt.normalize().to_numpy())
            flags = flags | dates.dt.normalize().isin(holiday_set)
    return flags.fillna(False).astype(bool)


def check_threshold(
    frame: pd.DataFrame,
    approval_limit: float = DEFAULT_APPROVAL_LIMIT,
) -> pd.Series:
    """Flag amounts sitting between 95% and 99.99% of the approval limit."""
    if approval_limit <= 0:
        raise ValueError("approval_limit must be positive.")
    lower = approval_limit * THRESHOLD_LOW
    upper = approval_limit * THRESHOLD_HIGH
    return frame["Amount"].between(lower, upper, inclusive="both").fillna(False)


def check_self_approval(frame: pd.DataFrame) -> pd.Series:
    """Flag entries where the same person posted and approved the payment."""
    posted = frame["PostedBy"].astype("object").fillna("").astype(str).str.strip().str.casefold()
    approved = frame["ApprovedBy"].astype("object").fillna("").astype(str).str.strip().str.casefold()
    return (posted != "") & (approved != "") & (posted == approved)


def check_benford(
    frame: pd.DataFrame,
    min_entries: int = MIN_BENFORD_ENTRIES,
    alpha: float = BENFORD_ALPHA,
) -> tuple[pd.Series, pd.Series]:
    """Flag every entry of a vendor whose first-digit mix breaks Benford's Law.

    A vendor needs at least ``min_entries`` usable amounts. A chi-square test
    compares its digit counts with Benford's expected distribution; p < alpha
    is treated as evidence of fabricated or manipulated amounts.
    """
    flags = pd.Series(False, index=frame.index, dtype=bool)
    p_values = pd.Series(np.nan, index=frame.index, dtype="float")

    digits = _leading_digits(frame["Amount"])
    if digits.empty:
        return flags, p_values

    vendor_key = frame.loc[digits.index, "Vendor"].astype(str).str.casefold()
    vendor_key = vendor_key.replace({"nan": ""})
    usable = vendor_key.ne("")
    digits = digits[usable]
    vendor_key = vendor_key[usable]

    vendor_p: dict[str, float] = {}
    for key, group in digits.groupby(vendor_key, sort=False):
        count = len(group)
        if count < min_entries:
            continue
        observed = np.array([(group == digit).sum() for digit in range(1, 10)], dtype=float)
        if observed.sum() == 0:
            continue
        expected = BENFORD_EXPECTED * observed.sum()
        p_value = float(stats.chisquare(observed, f_exp=expected).pvalue)
        vendor_p[str(key)] = p_value

    if not vendor_p:
        return flags, p_values

    all_vendor_keys = frame["Vendor"].astype(str).str.casefold().replace({"nan": ""})
    for key, p_value in vendor_p.items():
        rows = all_vendor_keys.index[all_vendor_keys == key]
        p_values.loc[rows] = p_value
        if p_value < alpha:
            flags.loc[rows] = True

    return flags, p_values


# ---------------------------------------------------------------------------
# Scoring and explanations
# ---------------------------------------------------------------------------


def _merge_weights(weights: Mapping[str, float] | None) -> dict[str, float]:
    """Return default weights updated with validated user overrides."""
    merged = dict(DEFAULT_WEIGHTS)
    if not weights:
        return merged
    for key, value in weights.items():
        if key not in DEFAULT_WEIGHTS:
            raise ValueError(f"Unknown weight key: {key}")
        merged[key] = max(0.0, float(value))
    return merged


def score_risk(frame: pd.DataFrame, weights: Mapping[str, float] | None = None) -> pd.Series:
    """Return a capped 0-100 risk score from the active flags and weights."""
    resolved = _merge_weights(weights)
    score = pd.Series(0.0, index=frame.index)
    for column, weight in resolved.items():
        score = score + frame[column].astype(bool).astype(float) * weight
    return score.clip(lower=0.0, upper=100.0).round(0).astype(int)


def risk_level(score: float | int) -> str:
    """Map a numeric risk score to Low, Medium, High, or Critical."""
    if score >= 70:
        return "Critical"
    if score >= 40:
        return "High"
    if score >= 20:
        return "Medium"
    return "Low"


def risk_levels(scores: pd.Series) -> pd.Series:
    """Vectorized risk-level mapping for a score Series."""
    return pd.Series(
        np.select(
            [scores >= 70, scores >= 40, scores >= 20],
            ["Critical", "High", "Medium"],
            default="Low",
        ),
        index=scores.index,
    )


def _money(value: float) -> str:
    """Format a number as a Pakistani rupee amount."""
    return format_pkr(value)


def _percent(value: float) -> str:
    """Format a ratio as a percentage with sensible precision."""
    return f"{value * 100:.2f}".rstrip("0").rstrip(".") + "%"


def _build_reasons(
    frame: pd.DataFrame,
    weights: Mapping[str, float],
    holiday_dates: set[pd.Timestamp],
) -> pd.Series:
    """Create a short, numeric reason per flagged row, ordered by weight."""
    reasons: list[list[str]] = []

    for row_index in frame.index:
        row = frame.loc[row_index]
        found: list[tuple[float, str]] = []

        if bool(row["flag_self_approval"]):
            found.append(
                (
                    weights["flag_self_approval"],
                    f"Posted and approved by the same person ({row['PostedBy']}).",
                )
            )
        if bool(row["flag_duplicate"]):
            gap = row.get("duplicate_gap_days")
            gap_text = f"{int(gap)} day(s) apart" if pd.notna(gap) else "within 7 days"
            invoice = row.get("duplicate_invoice")
            invoice_text = (
                f" and the same invoice reference {invoice}" if pd.notna(invoice) and invoice else ""
            )
            found.append(
                (
                    weights["flag_duplicate"],
                    f"Duplicate of {row['duplicate_of']} ({gap_text}): same vendor, "
                    f"amount {_money(float(row['Amount']))}{invoice_text}.",
                )
            )
        if bool(row["flag_threshold"]):
            limit = row.get("approval_limit_used", np.nan)
            if pd.notna(limit) and float(limit) > 0:
                found.append(
                    (
                        weights["flag_threshold"],
                        f"{_money(float(row['Amount']))} is "
                        f"{_percent(float(row['Amount']) / float(limit))} of the "
                        f"{_money(float(limit))} approval limit.",
                    )
                )
            else:
                found.append(
                    (
                        weights["flag_threshold"],
                        f"{_money(float(row['Amount']))} sits just below the approval limit.",
                    )
                )
        if bool(row["flag_benford"]):
            p_value = row.get("vendor_benford_p")
            p_text = f"p = {p_value:.4f}" if pd.notna(p_value) else "p < 0.01"
            found.append(
                (
                    weights["flag_benford"],
                    f"Vendor {row['Vendor']} deviates from Benford's Law ({p_text}).",
                )
            )
        if bool(row["flag_round"]):
            found.append(
                (
                    weights["flag_round"],
                    f"{_money(float(row['Amount']))} is an exact multiple of "
                    "Rs. 1,000 and at least Rs. 10,000.",
                )
            )
        if bool(row["flag_weekend"]):
            date = pd.Timestamp(row["Date"])
            if date.normalize() in holiday_dates:
                when = f"the configured holiday {format_date(date)}"
            else:
                when = f"a weekend ({date:%A} {format_date(date)})"
            found.append((weights["flag_weekend"], f"Posted on {when}."))

        found.sort(key=lambda item: item[0], reverse=True)
        reasons.append([text for _, text in found])

    return pd.Series(reasons, index=frame.index, dtype="object")


def _normalize_holidays(holidays: Iterable[object] | None) -> set[pd.Timestamp]:
    """Return normalized holiday timestamps for reason messages."""
    if holidays is None:
        return set()
    parsed = pd.to_datetime(
        pd.Series(list(holidays)), errors="coerce", format="mixed"
    ).dropna()
    return set(parsed.dt.normalize())


def _as_holiday_values(holidays: object) -> Iterable[object] | None:
    """Accept a list, index, or comma-separated string of holiday dates."""
    if holidays is None:
        return None
    if isinstance(holidays, str):
        return [part.strip() for part in holidays.split(",") if part.strip()]
    return holidays


# ---------------------------------------------------------------------------
# Full audit
# ---------------------------------------------------------------------------


def run_all_checks(
    df: pd.DataFrame,
    approval_limit: float = DEFAULT_APPROVAL_LIMIT,
    round_threshold: float = DEFAULT_ROUND_THRESHOLD,
    holidays: Iterable[object] | None = None,
    weights: Mapping[str, float] | None = None,
    weekend_days: Iterable[int] = DEFAULT_WEEKEND_DAYS,
    input_date_format: str = DEFAULT_INPUT_DATE_FORMAT,
) -> pd.DataFrame:
    """Run every rule and return a copy enriched with flags, score, and reasons."""
    if approval_limit <= 0:
        raise ValueError("approval_limit must be positive.")

    frame = prepare_ledger(df, input_date_format=input_date_format)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ValueError("Missing required column(s): " + ", ".join(missing))

    resolved_weights = _merge_weights(weights)
    holiday_values = _as_holiday_values(holidays)

    frame["flag_duplicate"], frame["duplicate_of"], frame["duplicate_gap_days"] = (
        check_duplicates(frame)
    )
    frame["flag_round"] = check_round(frame, round_threshold=round_threshold)
    frame["flag_weekend"] = check_weekend(
        frame, holiday_values, weekend_days=weekend_days
    )
    frame["flag_threshold"] = check_threshold(frame, approval_limit=approval_limit)
    frame["flag_self_approval"] = check_self_approval(frame)
    frame["flag_benford"], frame["vendor_benford_p"] = check_benford(frame)

    invoice_refs = frame["Description"].map(extract_invoice_reference)
    id_to_ref = dict(zip(_entry_ids(frame), invoice_refs))
    partner_refs = frame["duplicate_of"].map(
        lambda value: id_to_ref.get(str(value)) if pd.notna(value) else None
    )
    same_reference = (
        invoice_refs.notna()
        & partner_refs.notna()
        & (
            invoice_refs.astype(str).str.upper()
            == partner_refs.astype(str).str.upper()
        )
    )
    frame["duplicate_invoice"] = invoice_refs.where(same_reference)

    for column in FLAG_COLUMNS:
        frame[column] = frame[column].astype(bool)

    frame["flag_count"] = frame[list(FLAG_COLUMNS)].sum(axis=1).astype(int)
    frame["risk_score"] = score_risk(frame, resolved_weights)
    frame["risk_level"] = risk_levels(frame["risk_score"])
    frame["approval_limit_used"] = float(approval_limit)
    frame["flag_reasons"] = _build_reasons(
        frame,
        resolved_weights,
        _normalize_holidays(holiday_values),
    )

    return frame


# ---------------------------------------------------------------------------
# Summary and Benford reporting
# ---------------------------------------------------------------------------


def benford_table(df: pd.DataFrame) -> dict[str, object]:
    """Compare observed first digits with Benford's Law.

    Returns a dict with the digit table, overall chi-square p-value, the number
    of usable amounts, and whether the deviation is significant at 1%.
    """
    amounts = pd.to_numeric(df.get("Amount"), errors="coerce")
    digits = _leading_digits(amounts)
    counts = np.array(
        [int((digits == digit).sum()) for digit in range(1, 10)],
        dtype=float,
    )
    total = int(counts.sum())
    actual = counts / total * 100.0 if total else np.zeros(9)

    table = pd.DataFrame(
        {
            "Digit": np.arange(1, 10),
            "Expected %": BENFORD_EXPECTED * 100.0,
            "Actual %": actual,
            "Count": counts.astype(int),
        }
    )

    if total > 0:
        p_value = float(stats.chisquare(counts, f_exp=BENFORD_EXPECTED * total).pvalue)
    else:
        p_value = float("nan")

    return {
        "table": table,
        "p_value": p_value,
        "n": total,
        "significant": bool(total > 0 and p_value < BENFORD_ALPHA),
    }


def build_summary(df: pd.DataFrame) -> dict[str, object]:
    """Summarize a checked ledger for dashboards, reports, and explanations."""
    if "risk_score" not in df.columns or "flag_count" not in df.columns:
        raise ValueError("build_summary expects the output of run_all_checks.")

    total_entries = int(len(df))
    flagged_mask = df["flag_count"] > 0
    flagged_entries = int(flagged_mask.sum())
    flagged_pct = float(flagged_entries / total_entries * 100.0) if total_entries else 0.0

    amounts = pd.to_numeric(df.get("Amount"), errors="coerce").abs()
    amount_at_risk = float(amounts[flagged_mask].sum()) if flagged_entries else 0.0
    total_amount = float(amounts.sum()) if total_entries else 0.0

    flag_counts = {column: int(df[column].sum()) for column in FLAG_COLUMNS}
    risk_counts = {level: int((df["risk_level"] == level).sum()) for level in RISK_LEVELS}

    avg_risk_score = float(df["risk_score"].mean()) if total_entries else 0.0
    avg_flagged_risk = (
        float(df.loc[flagged_mask, "risk_score"].mean()) if flagged_entries else 0.0
    )
    if flagged_entries:
        density = flagged_entries / total_entries * 100.0
        overall_risk_score = round(min(100.0, avg_flagged_risk * 0.7 + density * 3.0), 1)
    else:
        overall_risk_score = 0.0

    top_vendors: list[dict[str, object]] = []
    if flagged_entries:
        flagged = df.loc[flagged_mask].copy()
        flagged["abs_amount"] = pd.to_numeric(flagged["Amount"], errors="coerce").abs()
        grouped = (
            flagged.groupby("Vendor", dropna=False)
            .agg(
                flagged_entries=("flag_count", "size"),
                amount_at_risk=("abs_amount", "sum"),
                max_risk_score=("risk_score", "max"),
            )
            .sort_values(["amount_at_risk", "max_risk_score"], ascending=False)
            .head(5)
        )
        top_vendors = [
            {
                "vendor": str(vendor),
                "flagged_entries": int(row["flagged_entries"]),
                "amount_at_risk": float(row["amount_at_risk"]),
                "max_risk_score": int(row["max_risk_score"]),
            }
            for vendor, row in grouped.iterrows()
        ]

    dominant_flag = max(flag_counts, key=flag_counts.get) if any(flag_counts.values()) else None

    return {
        "total_entries": total_entries,
        "flagged_entries": flagged_entries,
        "flagged_pct": flagged_pct,
        "amount_at_risk": amount_at_risk,
        "total_amount": total_amount,
        "flag_counts": flag_counts,
        "risk_counts": risk_counts,
        "avg_risk_score": avg_risk_score,
        "avg_flagged_risk": avg_flagged_risk,
        "overall_risk_score": overall_risk_score,
        "overall_risk_level": risk_level(overall_risk_score),
        "top_vendors": top_vendors,
        "dominant_flag": dominant_flag,
        "dominant_pattern": FLAG_LABELS.get(dominant_flag, "None") if dominant_flag else "None",
    }
