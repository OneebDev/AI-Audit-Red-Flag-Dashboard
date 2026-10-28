"""Plain-English and Roman Urdu explanations for flagged entries.

The templates are deterministic and grounded only in the entry's own fields.
Optional Groq wording lives in :mod:`groq_client`; every failed or ungrounded
LLM response falls back to these templates.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pandas as pd

from detection import FLAG_COLUMNS, FLAG_LABELS
from utils import format_date, format_pkr

FLAG_ORDER = (
    "flag_self_approval",
    "flag_duplicate",
    "flag_threshold",
    "flag_benford",
    "flag_round",
    "flag_weekend",
)

_FLAG_WHY = {
    "flag_duplicate": (
        "Double payments inflate expenses and can hide funds leaving the company.",
        "A repeated posting may be an accidental double payment or a deliberate duplicate.",
    ),
    "flag_round": (
        "Exact round figures often mean an estimate or manual adjustment rather than a checked invoice.",
        "Round totals are easy to create without support and deserve a closer look.",
    ),
    "flag_weekend": (
        "Weekend and holiday postings skip normal review hours and can slip through thin controls.",
        "Off-hours postings are harder for supervisors to challenge before they settle.",
    ),
    "flag_threshold": (
        "Amounts parked just under a limit can bypass the next level of approval.",
        "Structuring below an approval threshold defeats the control it is meant to trigger.",
    ),
    "flag_self_approval": (
        "Self-approval breaks segregation of duties, the core control against fraud.",
        "When one person posts and approves, no second pair of eyes checks the payment.",
    ),
    "flag_benford": (
        "A vendor whose leading digits break Benford's Law may be using fabricated amounts.",
        "Digit patterns that ignore Benford's Law are a recognised sign of made-up numbers.",
    ),
}

_FLAG_WHY_UR = {
    "flag_duplicate": "Double payment kharche barha deta hai aur paisa nikalne ko chhupa sakta hai.",
    "flag_round": "Bilkul round amount aksar estimate ya manual adjustment hoti hai, checked invoice nahi.",
    "flag_weekend": "Weekend ya holiday ki posting normal review hours se bach jati hai.",
    "flag_threshold": "Limit ke bilkul neeche amount rakh kar agli approval bypass ki ja sakti hai.",
    "flag_self_approval": "Self-approval segregation of duties ko todta hai, jo fraud ke khilaf bunyadi control hai.",
    "flag_benford": "Vendor ke leading digits Benford's Law se match nahi karte, jo banaye gaye numbers ki alamat ho sakti hai.",
}

_FLAG_ACTION = {
    "flag_duplicate": "match the payment to the original invoice and reverse any true double payment",
    "flag_round": "obtain the supplier invoice and recalculate the amount from source documents",
    "flag_weekend": "confirm the posting date with the preparer and inspect the batch log",
    "flag_threshold": "confirm who approved the commitment and whether the purchase was split",
    "flag_self_approval": "have an independent manager re-approve the entry and document the exception",
    "flag_benford": "sample the vendor's invoices and test amounts against purchase orders",
}

_ACTION_LIST = {
    "flag_duplicate": "Trace the posting to the original invoice and confirm whether the payment was made twice.",
    "flag_round": "Obtain the supplier invoice and recalculate the total from the underlying documents.",
    "flag_weekend": "Ask the preparer to explain the posting date and review the after-hours batch log.",
    "flag_threshold": "Confirm whether the purchase was split and who approved the commitment.",
    "flag_self_approval": "Escalate to an independent manager for re-approval and document the exception.",
    "flag_benford": "Sample the vendor's recent invoices and compare amounts with purchase orders and receipts.",
}

_ACTION_LIST_UR = {
    "flag_duplicate": "Posting ko original invoice se match karke double payment check karein.",
    "flag_round": "Supplier invoice le kar amount dobara calculate karein.",
    "flag_weekend": "Preparer se posting date poochhein aur batch log dekhein.",
    "flag_threshold": "Check karein ke purchase split hui thi ya nahi aur kis ne approve kiya.",
    "flag_self_approval": "Independent manager se dobara approval karwayein aur exception note karein.",
    "flag_benford": "Vendor ke invoices sample karke purchase orders se compare karein.",
}

_DUPLICATE_PHRASES = (
    "It repeats {first}'s posting for {vendor} at {amount}, {gap} later",
    "This is a second {vendor} posting at {amount}, {gap} after {first}",
    "The same vendor and amount as {first} appears again {gap} later",
)
_GAP_FALLBACK = "a week"

_ROUND_PHRASES = (
    "the {amount} total is an exact round figure",
    "the amount lands exactly on {amount}, a round figure",
    "a perfectly round {amount} was entered",
)


def _text(value: object, fallback: str) -> str:
    """Return trimmed text or a fallback for missing values."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return fallback
    text = str(value).strip()
    return text or fallback


def _money(value: object) -> str:
    """Format a numeric value as Pakistani rupees, or describe it neutrally."""
    try:
        if value is None or (not isinstance(value, str) and pd.isna(value)):
            raise ValueError
        return format_pkr(float(value))
    except (TypeError, ValueError):
        return "an unknown amount"


def _date_label(value: object) -> str:
    """Format a date as ``Saturday 03/08/2025`` when possible."""
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError):
        return "an unreadable date"
    if pd.isna(timestamp):
        return "an unreadable date"
    return f"{timestamp:%A} {format_date(timestamp)}"


def _active_flags(entry: Mapping[str, object]) -> list[str]:
    """Return the triggered flag columns in risk-weight order."""
    active = []
    for column in FLAG_ORDER:
        value = entry.get(column, False)
        if bool(value) is True or str(value).lower() == "true":
            active.append(column)
    return active


def _variant(entry: Mapping[str, object], options: Sequence[str]) -> str:
    """Pick a deterministic template variant from the entry ID."""
    seed = sum(ord(char) for char in _text(entry.get("EntryID"), "entry"))
    return options[seed % len(options)]


def _gap_text(entry: Mapping[str, object]) -> str:
    """Describe the duplicate gap using only the entry's own data."""
    gap = entry.get("duplicate_gap_days")
    try:
        days = int(float(gap))
    except (TypeError, ValueError):
        return _GAP_FALLBACK
    return f"{days} day{'s' if days != 1 else ''}"


def _invoice_clause(entry: Mapping[str, object]) -> str:
    """Mention a shared invoice reference when present."""
    reference = entry.get("duplicate_invoice")
    if reference is None or (not isinstance(reference, str) and pd.isna(reference)):
        return ""
    return f", including invoice {reference}"


def _detail_clause(column: str, entry: Mapping[str, object]) -> str:
    """Build one factual clause for a triggered flag."""
    amount = _money(entry.get("Amount"))
    vendor = _text(entry.get("Vendor"), "the vendor")

    if column == "flag_duplicate":
        first = _text(entry.get("duplicate_of"), "an earlier entry")
        phrase = _variant(entry, _DUPLICATE_PHRASES)
        clause = phrase.format(first=first, vendor=vendor, amount=amount, gap=_gap_text(entry))
        return clause + _invoice_clause(entry)

    if column == "flag_round":
        return _variant(entry, _ROUND_PHRASES).format(amount=amount)

    if column == "flag_weekend":
        return (
            f"it was posted on {_date_label(entry.get('Date'))}, outside normal "
            f"business days, for {amount}"
        )

    if column == "flag_threshold":
        limit = entry.get("approval_limit_used")
        try:
            share = float(entry.get("Amount")) / float(limit) * 100.0
            return f"the {amount} sits at {share:.2f}% of the {_money(limit)} approval limit"
        except (TypeError, ValueError, ZeroDivisionError):
            return f"the {amount} sits just below the approval limit"

    if column == "flag_self_approval":
        poster = _text(entry.get("PostedBy"), "the same person")
        return f"{poster} both posted and approved the {amount} payment"

    if column == "flag_benford":
        p_value = entry.get("vendor_benford_p")
        try:
            return (
                f"the {amount} posting belongs to a vendor whose leading-digit mix "
                f"departs from Benford's Law (p = {float(p_value):.4f})"
            )
        except (TypeError, ValueError):
            return (
                f"the {amount} posting belongs to a vendor whose leading-digit mix "
                "departs from Benford's Law"
            )

    return FLAG_LABELS.get(column, column).lower()


def _detail_clause_ur(column: str, entry: Mapping[str, object]) -> str:
    """Build one Roman Urdu factual clause for a triggered flag."""
    amount = _money(entry.get("Amount"))
    vendor = _text(entry.get("Vendor"), "vendor")

    if column == "flag_duplicate":
        first = _text(entry.get("duplicate_of"), "pehli entry")
        return (
            f"{first} ki {vendor} posting {amount} ke saath {_gap_text(entry)} ke andar "
            f"dobara aayi hai{_invoice_clause(entry)}"
        )
    if column == "flag_round":
        return f"{amount} bilkul round figure hai"
    if column == "flag_weekend":
        return (
            f"yeh {_date_label(entry.get('Date'))} ko weekend ya holiday par post hui "
            f"hai, amount {amount}"
        )
    if column == "flag_threshold":
        limit = entry.get("approval_limit_used")
        try:
            share = float(entry.get("Amount")) / float(limit) * 100.0
            return f"{amount} approval limit {_money(limit)} ke {share:.2f}% par hai"
        except (TypeError, ValueError, ZeroDivisionError):
            return f"{amount} approval limit ke bilkul neeche hai"
    if column == "flag_self_approval":
        poster = _text(entry.get("PostedBy"), "isi shakhs")
        return f"{poster} ne {amount} ki posting bhi khud ki aur approval bhi khud di"
    if column == "flag_benford":
        return (
            f"vendor ke leading digits Benford's Law se match nahi karte; yeh posting "
            f"{amount} ki hai"
        )
    return FLAG_LABELS.get(column, column).lower()


def _join_clauses(clauses: Sequence[str], conjunction: str = "and") -> str:
    """Join detail clauses with commas and a final conjunction."""
    if not clauses:
        return ""
    if len(clauses) == 1:
        return clauses[0]
    if len(clauses) == 2:
        return f"{clauses[0]} {conjunction} {clauses[1]}"
    return ", ".join(clauses[:-1]) + f", {conjunction} {clauses[-1]}"


def explain_entry(row: Mapping[str, object], language: str = "English") -> str:
    """Explain an entry in two or three sentences and name every red flag.

    The wording is grounded in the entry's own fields: IDs, amounts, dates,
    names, and percentages all come from the row so an auditor can verify them.
    """
    flags = _active_flags(row)
    entry_id = _text(row.get("EntryID"), "This entry")
    roman_urdu = language == "Roman Urdu"

    if not flags:
        if roman_urdu:
            return (
                f"{entry_id} ke liye koi red-flag rule trigger nahi hua. "
                "Yeh entry normal audit sampling se guzar sakti hai."
            )
        return (
            f"No red-flag rules were triggered for {entry_id}. "
            "The entry can proceed through normal audit sampling."
        )

    labels = [FLAG_LABELS.get(column, column) for column in flags]
    count_text = f"{len(labels)} red flag{'s' if len(labels) != 1 else ''}"

    if roman_urdu:
        intro = f"{entry_id} mein {count_text} hain: {_join_clauses(labels, 'aur')}."
        details = _join_clauses(
            [_detail_clause_ur(column, row) for column in flags], "aur"
        )
        detail_sentence = details[0].upper() + details[1:] + "."
        closing = (
            f"{_FLAG_WHY_UR[flags[0]]} Pehla qadam: "
            f"{_ACTION_LIST_UR[flags[0]]}"
        )
        return " ".join((intro, detail_sentence, closing))

    intro = f"{entry_id} shows {count_text}: {_join_clauses(labels)}."
    details = _join_clauses([_detail_clause(column, row) for column in flags])
    detail_sentence = details[0].upper() + details[1:] + "."
    why = _variant(row, _FLAG_WHY[flags[0]])
    actions = [_FLAG_ACTION[column] for column in flags[:2]]
    closing = f"{why.rstrip('.')}; next, {_join_clauses(actions)}."
    return " ".join((intro, detail_sentence, closing))


def recommended_actions(
    row: Mapping[str, object],
    language: str = "English",
) -> list[str]:
    """Return two to four concrete audit procedures for an entry."""
    flags = _active_flags(row)
    roman_urdu = language == "Roman Urdu"
    if not flags:
        if roman_urdu:
            return [
                "Entry ko normal audit sampling ke liye select karein.",
                "Is posting ke liye mazeed procedure ki zaroorat nahi.",
            ]
        return [
            "Select the entry for normal audit sampling.",
            "No additional procedures are needed for this posting.",
        ]

    actions = [
        (_ACTION_LIST_UR if roman_urdu else _ACTION_LIST)[column] for column in flags[:3]
    ]
    actions.append(
        "Evidence aur nateeja audit record mein darj karein."
        if roman_urdu
        else "Record the evidence and outcome in the audit workpaper."
    )
    return actions[:4]


def generate_executive_summary(
    summary: Mapping[str, object],
    top_entries: pd.DataFrame | Sequence[Mapping[str, object]] | None = None,
    language: str = "English",
) -> str:
    """Write a four-to-six sentence executive summary from the audit numbers."""
    total = int(summary.get("total_entries", 0))
    flagged = int(summary.get("flagged_entries", 0))
    pct = float(summary.get("flagged_pct", 0.0))
    risk_score = float(summary.get("overall_risk_score", 0.0))
    risk_level = _text(summary.get("overall_risk_level"), "Low")
    amount = float(summary.get("amount_at_risk", 0.0))
    pattern = _text(summary.get("dominant_pattern"), "No dominant pattern")
    vendors = summary.get("top_vendors") or []

    entries = []
    if isinstance(top_entries, pd.DataFrame):
        entries = top_entries.head(1).to_dict("records")
    elif top_entries:
        entries = list(top_entries)[:1]

    roman_urdu = language == "Roman Urdu"
    if roman_urdu:
        sentences = [
            f"AuditGuard ne {total:,} journal entries review ki hain aur overall risk "
            f"{risk_level} {risk_score:.1f} out of 100 rakha hai.",
            f"{flagged:,} entries ({pct:.1f}%) flag hui hain, jin ki exposure "
            f"{_money(amount)} hai.",
        ]
        if flagged and pattern != "None":
            sentences.append(
                f"Sab se bara pattern {pattern.lower()} hai, jo reviewer ko us rule ki "
                "taraf le jata hai jis se sab se zyada hits aa rahe hain."
            )
        elif not flagged:
            sentences.append(
                "Koi entry red-flag threshold cross nahi kar saki, is liye routine "
                "sampling is period ke liye munasib control hai."
            )
        if vendors:
            riskiest = vendors[0]
            sentences.append(
                f"{_text(riskiest.get('vendor'), 'Top vendor')} ke paas sab se zyada "
                f"flagged exposure {_money(riskiest.get('amount_at_risk', 0))} hai, "
                f"{int(riskiest.get('flagged_entries', 0))} entries mein."
            )
        if entries:
            top = entries[0]
            sentences.append(
                f"Sab se pehle {_text(top.get('EntryID'), 'top entry')} dekhein "
                f"(risk score {int(top.get('risk_score', 0))})."
            )
        sentences.append(
            "Agla qadam: duplicate payments clear karein, self-approved entries ko "
            "independent manager se dobara approve karwayein, aur Benford se hatne "
            "wale vendors ka sample lein."
        )
        return " ".join(sentences[:6])

    sentences = [
        f"AuditGuard reviewed {total:,} journal entries and rated overall risk "
        f"{risk_level} at {risk_score:.1f} out of 100.",
        f"{flagged:,} entries ({pct:.1f}%) were flagged, representing "
        f"{_money(amount)} of exposure.",
    ]

    if flagged and pattern != "None":
        sentences.append(
            f"The dominant pattern is {pattern.lower()}, which points reviewers "
            "toward the rule that is producing the most hits."
        )
    elif not flagged:
        sentences.append(
            "No entry crossed a red-flag threshold, so routine sampling remains "
            "the appropriate control for this period."
        )

    if vendors:
        riskiest = vendors[0]
        vendor_name = _text(riskiest.get("vendor"), "the top vendor")
        vendor_amount = _money(riskiest.get("amount_at_risk", 0))
        sentences.append(
            f"{vendor_name} carries the largest flagged exposure at {vendor_amount} "
            f"across {int(riskiest.get('flagged_entries', 0))} entries."
        )

    if entries:
        top = entries[0]
        top_id = _text(top.get("EntryID"), "the highest-risk entry")
        top_flags = [
            FLAG_LABELS.get(column, column)
            for column in FLAG_COLUMNS
            if str(top.get(column, False)).lower() == "true" or top.get(column) is True
        ]
        flag_text = _join_clauses(top_flags) if top_flags else "multiple indicators"
        sentences.append(
            f"Start with {top_id} ({flag_text}, risk score "
            f"{int(top.get('risk_score', 0))}) because it ranks highest under the "
            "current weights."
        )

    sentences.append(
        "Recommended next steps: clear duplicate payments first, re-approve "
        "self-approved entries independently, and sample vendors whose digit "
        "patterns break Benford's Law."
    )

    return " ".join(sentences[:6])
