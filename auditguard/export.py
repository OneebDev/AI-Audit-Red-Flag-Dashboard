"""Excel audit report builder and ground-truth accuracy scoring."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import BytesIO

import numpy as np
import pandas as pd
from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from detection import (
    ALL_LABELS,
    ANOMALY_LABELS,
    CLEAN_LABEL,
    DEFAULT_WEIGHTS,
    FLAG_COLUMNS,
    FLAG_LABELS,
    GROUND_TRUTH_COLUMN,
    MULTIRULE_LABEL,
    RISK_LEVELS,
    risk_level,
)
from utils import (
    EXCEL_DATE_FORMAT,
    EXCEL_PKR_FORMAT,
    format_date,
    format_datetime,
    now_karachi,
)

_HEADER_FILL = PatternFill("solid", fgColor="1F1B3A")
_HEADER_FONT = Font(bold=True, color="FFFFFF")
_ALT_ROW_FILL = PatternFill("solid", fgColor="F3F6FB")
_HEADER_BORDER = Border(bottom=Side(style="thin", color="7C5CFF"))
_TITLE_FONT = Font(bold=True, size=18, color="1F1B3A")
_SECTION_FONT = Font(bold=True, size=12, color="4C1D95")
_MUTED_FONT = Font(italic=True, color="6B7280")
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")

_RISK_FILLS = {
    "Low": PatternFill("solid", fgColor="DCFCE7"),
    "Medium": PatternFill("solid", fgColor="FEF3C7"),
    "High": PatternFill("solid", fgColor="FFEDD5"),
    "Critical": PatternFill("solid", fgColor="FEE2E2"),
}

GT_TO_FLAG = {
    "Duplicate": "flag_duplicate",
    "RoundAmount": "flag_round",
    "Weekend": "flag_weekend",
    "JustBelowLimit": "flag_threshold",
    "SelfApproval": "flag_self_approval",
    "BenfordManip": "flag_benford",
}

REPORT_COLUMNS = (
    "EntryID",
    "Date",
    "Account",
    "Vendor",
    "Description",
    "Amount",
    "PostedBy",
    "ApprovedBy",
    "risk_score",
    "risk_level",
    "flag_reasons",
    "duplicate_of",
    "risk_flags",
    GROUND_TRUTH_COLUMN,
) + FLAG_COLUMNS

_FLAGGED_HEADERS = {
    "EntryID": "Entry ID",
    "Date": "Date",
    "Account": "Account",
    "Vendor": "Vendor",
    "Description": "Description",
    "Amount": "Amount (Rs.)",
    "PostedBy": "Posted By",
    "ApprovedBy": "Approved By",
    "risk_score": "Risk Score",
    "risk_level": "Risk Level",
    "flag_reasons": "Reasons",
    "duplicate_of": "Duplicate Of",
    "risk_flags": "Flags",
    GROUND_TRUTH_COLUMN: "Ground Truth",
    "flag_duplicate": "Duplicate",
    "flag_round": "Round Amount",
    "flag_weekend": "Weekend",
    "flag_threshold": "Just Below Limit",
    "flag_self_approval": "Self-Approval",
    "flag_benford": "Benford",
}


def _safe_sheet_name(name: str) -> str:
    """Remove characters Excel forbids in worksheet names."""
    cleaned = "".join(char for char in name if char not in r"[]:*?/\\").strip()
    return (cleaned or "Ledger")[:31]


def _neutralize_formula_cells(worksheet: Worksheet) -> None:
    """Force formula-like text cells to plain strings to prevent Excel injection."""
    for row in worksheet.iter_rows(min_row=1):
        for cell in row:
            if isinstance(cell.value, str) and cell.value.lstrip().startswith(
                _FORMULA_PREFIXES
            ):
                cell.data_type = "s"


def _style_header(worksheet: Worksheet, row: int, columns: int) -> None:
    """Apply the dark header style to a row."""
    for column in range(1, columns + 1):
        cell = worksheet.cell(row=row, column=column)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.border = _HEADER_BORDER
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def _write_table(
    worksheet: Worksheet,
    start_row: int,
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    number_formats: Mapping[int, str] | None = None,
) -> int:
    """Write a styled table and return the next free row."""
    for offset, header in enumerate(headers, start=1):
        worksheet.cell(row=start_row, column=offset, value=header)
    _style_header(worksheet, start_row, len(headers))

    for row_offset, values in enumerate(rows, start=1):
        excel_row = start_row + row_offset
        for column, value in enumerate(values, start=1):
            cell = worksheet.cell(row=excel_row, column=column, value=value)
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            if row_offset % 2 == 0:
                cell.fill = _ALT_ROW_FILL
            if number_formats and column in number_formats:
                cell.number_format = number_formats[column]
    return start_row + len(rows) + 2


def dataframe_to_excel_bytes(
    frame: pd.DataFrame,
    sheet_name: str = "Ledger",
) -> bytes:
    """Render a DataFrame as a styled ``.xlsx`` workbook and return its bytes."""
    buffer = BytesIO()
    safe_name = _safe_sheet_name(sheet_name)

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name=safe_name)
        worksheet = writer.sheets[safe_name]
        _neutralize_formula_cells(worksheet)

        worksheet.freeze_panes = "A2"
        worksheet.sheet_view.showGridLines = False
        worksheet.row_dimensions[1].height = 24
        if worksheet.max_row >= 1:
            worksheet.auto_filter.ref = worksheet.dimensions

        for cell in worksheet[1]:
            cell.fill = _HEADER_FILL
            cell.font = _HEADER_FONT
            cell.alignment = Alignment(horizontal="center", vertical="center")
            cell.border = _HEADER_BORDER

        for row_index in range(2, worksheet.max_row + 1):
            if row_index % 2 == 0:
                for cell in worksheet[row_index]:
                    cell.fill = _ALT_ROW_FILL

        for column_index, column_name in enumerate(frame.columns, start=1):
            letter = get_column_letter(column_index)
            sample = frame[column_name].astype(str).head(200)
            width = max([len(str(column_name))] + [len(value) for value in sample]) + 2
            worksheet.column_dimensions[letter].width = min(max(width, 11), 48)

            if pd.api.types.is_datetime64_any_dtype(frame[column_name]):
                for cell in worksheet[letter][1:]:
                    cell.number_format = EXCEL_DATE_FORMAT

            if column_name == "Amount":
                for cell in worksheet[letter][1:]:
                    cell.number_format = EXCEL_PKR_FORMAT

        if "Description" in frame.columns:
            description_letter = get_column_letter(
                list(frame.columns).index("Description") + 1
            )
            for cell in worksheet[description_letter][1:]:
                cell.alignment = Alignment(vertical="top", wrap_text=True)

    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Accuracy against GroundTruth
# ---------------------------------------------------------------------------


def _safe_ratio(numerator: int, denominator: int) -> float:
    """Return a ratio, or 0 when the denominator is zero."""
    return float(numerator) / float(denominator) if denominator else 0.0


def compute_accuracy(df: pd.DataFrame) -> dict[str, object] | None:
    """Score flags against GroundTruth, overall and per anomaly type.

    The overall calculation treats any flag as a predicted anomaly and any
    non-Clean label as a real anomaly. A MultiRule row is only counted as
    detected when at least two flags fire. Per-type metrics use one-vs-rest
    over the single-rule labels; MultiRule rows are reported separately so
    their intentional extra flags do not look like false alarms.
    """
    if GROUND_TRUTH_COLUMN not in df.columns:
        return None

    truth = df[GROUND_TRUTH_COLUMN].fillna(CLEAN_LABEL).astype(str)
    flag_count = df["flag_count"].fillna(0).astype(int)
    multi_mask = truth == MULTIRULE_LABEL
    predicted = (flag_count > 0) & (~multi_mask | (flag_count >= 2))
    actual = truth != CLEAN_LABEL

    tp = int((actual & predicted).sum())
    fp = int((~actual & predicted).sum())
    fn = int((actual & ~predicted).sum())
    tn = int((~actual & ~predicted).sum())
    precision = _safe_ratio(tp, tp + fp)
    recall = _safe_ratio(tp, tp + fn)
    f1 = _safe_ratio(2 * precision * recall, precision + recall) if precision + recall else 0.0

    single_rule_mask = ~multi_mask
    per_type = []
    for label in ANOMALY_LABELS:
        column = GT_TO_FLAG[label]
        label_mask = truth == label
        rule_mask = df[column].fillna(False).astype(bool)
        label_tp = int((label_mask & rule_mask).sum())
        label_fp = int((single_rule_mask & ~label_mask & rule_mask).sum())
        label_fn = int((label_mask & ~rule_mask).sum())
        label_precision = _safe_ratio(label_tp, label_tp + label_fp)
        label_recall = _safe_ratio(label_tp, label_tp + label_fn)
        label_f1 = (
            _safe_ratio(2 * label_precision * label_recall, label_precision + label_recall)
            if label_precision + label_recall
            else 0.0
        )
        per_type.append(
            {
                "type": label,
                "tp": label_tp,
                "fp": label_fp,
                "fn": label_fn,
                "support": int(label_mask.sum()),
                "flagged": int(rule_mask.sum()),
                "precision": label_precision,
                "recall": label_recall,
                "f1": label_f1,
            }
        )

    multi_tp = int((multi_mask & predicted).sum())
    multi_fn = int((multi_mask & ~predicted).sum())
    multi_recall = _safe_ratio(multi_tp, multi_tp + multi_fn)
    per_type.append(
        {
            "type": MULTIRULE_LABEL,
            "tp": multi_tp,
            "fp": 0,
            "fn": multi_fn,
            "support": int(multi_mask.sum()),
            "flagged": multi_tp,
            "precision": 1.0 if multi_tp else 0.0,
            "recall": multi_recall,
            "f1": multi_recall,
        }
    )

    missed = df.loc[actual & ~predicted].copy()
    false_alarms = df.loc[~actual & predicted].copy()

    return {
        "overall": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "tn": tn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "accuracy": _safe_ratio(tp + tn, len(df)),
        },
        "per_type": per_type,
        "tested_entries": int(len(df)),
        "injected": int(actual.sum()),
        "predicted": int(predicted.sum()),
        "missed": missed,
        "false_alarms": false_alarms,
    }


# ---------------------------------------------------------------------------
# Workbook report
# ---------------------------------------------------------------------------


def _explanation_map(explanations: object) -> dict[str, str]:
    """Normalize explanations from a mapping or a list of records."""
    if explanations is None:
        return {}
    if isinstance(explanations, Mapping):
        return {str(key): str(value) for key, value in explanations.items()}
    result = {}
    for item in explanations:
        if not isinstance(item, Mapping):
            continue
        entry_id = str(item.get("EntryID", ""))
        text = item.get("explanation") or item.get("text") or ""
        result[entry_id] = str(text)
    return result


def _prepare_flagged(df_flagged: pd.DataFrame) -> pd.DataFrame:
    """Return only flagged rows, sorted by risk, with display-friendly flags."""
    frame = df_flagged.copy()
    if "flag_count" in frame.columns:
        frame = frame[frame["flag_count"] > 0]
    if "risk_score" in frame.columns:
        frame = frame.sort_values("risk_score", ascending=False, kind="stable")
    frame = frame.reset_index(drop=True)

    if "risk_flags" not in frame.columns:
        frame["risk_flags"] = frame.apply(
            lambda row: ", ".join(
                FLAG_LABELS[column]
                for column in FLAG_COLUMNS
                if bool(row.get(column, False))
            ),
            axis=1,
        )
    if "flag_reasons" in frame.columns:
        frame["flag_reasons"] = frame["flag_reasons"].map(
            lambda value: "; ".join(str(reason) for reason in value)
            if isinstance(value, list)
            else str(value)
        )
    return frame


def _summary_sheet(
    worksheet: Worksheet,
    summary: Mapping[str, object],
    frame: pd.DataFrame,
) -> None:
    """Write the Summary sheet with KPIs, live formulas, and native charts."""
    worksheet.sheet_view.showGridLines = False
    worksheet.merge_cells("A1:F1")
    title = worksheet["A1"]
    title.value = "AuditGuard Audit Report — Karachi"
    title.font = _TITLE_FONT
    title.alignment = Alignment(vertical="center")
    worksheet.row_dimensions[1].height = 30

    worksheet.merge_cells("A2:F2")
    meta = worksheet["A2"]
    meta.value = (
        f"Generated {format_datetime(now_karachi())} · Prepared in Karachi, Pakistan · "
        "Synthetic demo data"
    )
    meta.font = _MUTED_FONT

    worksheet["A4"] = "Key metrics"
    worksheet["A4"].font = _SECTION_FONT

    flagged_columns = [column for column in REPORT_COLUMNS if column in frame.columns]
    risk_level_letter = get_column_letter(
        flagged_columns.index("risk_level") + 1
        if "risk_level" in flagged_columns
        else 10
    )
    amount_letter = get_column_letter(
        flagged_columns.index("Amount") + 1 if "Amount" in flagged_columns else 6
    )
    risk_score_letter = get_column_letter(
        flagged_columns.index("risk_score") + 1 if "risk_score" in flagged_columns else 9
    )

    metrics = [
        ("Total entries", int(summary.get("total_entries", 0)), "#,##0"),
        ("Flagged entries", 0, "#,##0"),
        ("Flagged %", 0, "0.0%"),
        ("Amount at risk (Rs.)", 0, EXCEL_PKR_FORMAT),
        ("Average risk score", float(summary.get("avg_risk_score", 0.0)), "0.0"),
        ("Overall risk score", float(summary.get("overall_risk_score", 0.0)), "0.0"),
        ("Overall risk level", str(summary.get("overall_risk_level", "Low")), "General"),
    ]
    for offset, (label, value, number_format) in enumerate(metrics, start=5):
        worksheet.cell(row=offset, column=1, value=label).font = Font(bold=True)
        cell = worksheet.cell(row=offset, column=2, value=value)
        cell.number_format = number_format

    # Live formulas keep the report usable when an auditor edits the detail rows.
    worksheet["B6"] = "=COUNTA('Flagged Entries'!$A$2:$A$100000)"
    worksheet["B7"] = "=IFERROR(B6/B5,0)"
    worksheet["B8"] = (
        f"=SUMIF('Flagged Entries'!${risk_score_letter}:${risk_score_letter},\">0\","
        f"'Flagged Entries'!${amount_letter}:${amount_letter})"
    )

    worksheet["A13"] = "Entries by risk level"
    worksheet["A13"].font = _SECTION_FONT
    worksheet["A14"] = "Risk level"
    worksheet["B14"] = "Count"
    _style_header(worksheet, 14, 2)
    for offset, level in enumerate(RISK_LEVELS, start=15):
        worksheet.cell(row=offset, column=1, value=level)
        cell = worksheet.cell(
            row=offset,
            column=2,
            value=f"=COUNTIF('Flagged Entries'!${risk_level_letter}:${risk_level_letter},\"{level}\")",
        )
        cell.number_format = "#,##0"
        worksheet.cell(row=offset, column=1).fill = _RISK_FILLS[level]

    worksheet["A20"] = "Rule hits by flag type"
    worksheet["A20"].font = _SECTION_FONT
    worksheet["A21"] = "Flag type"
    worksheet["B21"] = "Count"
    worksheet["C21"] = "Amount"
    worksheet["D21"] = "Weight"
    _style_header(worksheet, 21, 4)

    for offset, column in enumerate(FLAG_COLUMNS, start=22):
        label = FLAG_LABELS[column]
        amount = float(
            pd.to_numeric(frame.loc[frame[column].astype(bool), "Amount"], errors="coerce")
            .abs()
            .sum()
        ) if column in frame.columns and not frame.empty else 0.0
        flag_letter = get_column_letter(
            flagged_columns.index(column) + 1
            if column in flagged_columns
            else 15 + FLAG_COLUMNS.index(column)
        )
        worksheet.cell(row=offset, column=1, value=label)
        worksheet.cell(
            row=offset,
            column=2,
            value=f"=COUNTIF('Flagged Entries'!${flag_letter}:${flag_letter},TRUE)",
        ).number_format = "#,##0"
        worksheet.cell(row=offset, column=3, value=amount).number_format = EXCEL_PKR_FORMAT
        worksheet.cell(row=offset, column=4, value=float(DEFAULT_WEIGHTS[column]))

    total_row = 22 + len(FLAG_COLUMNS)
    worksheet.cell(row=total_row, column=1, value="Total rule hits").font = Font(bold=True)
    worksheet.cell(
        row=total_row, column=2, value=f"=SUM(B22:B{total_row - 1})"
    ).font = Font(bold=True)

    widths = {"A": 25, "B": 16, "C": 16, "D": 10, "E": 12, "F": 12}
    for letter, width in widths.items():
        worksheet.column_dimensions[letter].width = width

    bar = BarChart()
    bar.type = "bar"
    bar.style = 10
    bar.title = "Rule hits by flag type"
    bar.y_axis.title = "Entries"
    bar.x_axis.title = "Flag"
    data = Reference(worksheet, min_col=2, min_row=21, max_row=21 + len(FLAG_COLUMNS))
    categories = Reference(
        worksheet, min_col=1, min_row=22, max_row=21 + len(FLAG_COLUMNS)
    )
    bar.add_data(data, titles_from_data=True)
    bar.set_categories(categories)
    bar.legend = None
    if bar.series:
        bar.series[0].graphicalProperties.solidFill = "22D3EE"
    worksheet.add_chart(bar, "F4")

    pie = PieChart()
    pie.title = "Risk level mix"
    pie_data = Reference(worksheet, min_col=2, min_row=14, max_row=14 + len(RISK_LEVELS))
    pie_categories = Reference(
        worksheet, min_col=1, min_row=15, max_row=14 + len(RISK_LEVELS)
    )
    pie.add_data(pie_data, titles_from_data=True)
    pie.set_categories(pie_categories)
    worksheet.add_chart(pie, "F21")


def _flagged_sheet(worksheet: Worksheet, frame: pd.DataFrame) -> None:
    """Write the Flagged Entries sheet with filters, formats, and risk fills."""
    columns = [column for column in REPORT_COLUMNS if column in frame.columns]
    headers = [_FLAGGED_HEADERS.get(column, column) for column in columns]

    for index, header in enumerate(headers, start=1):
        worksheet.cell(row=1, column=index, value=header)
    _style_header(worksheet, 1, len(headers))
    worksheet.freeze_panes = "A2"
    worksheet.row_dimensions[1].height = 30
    worksheet.sheet_view.showGridLines = False

    for row_offset, (_, row) in enumerate(frame.iterrows(), start=2):
        for column_index, column in enumerate(columns, start=1):
            value = row[column]
            if isinstance(value, (list, tuple)):
                value = "; ".join(str(part) for part in value)
            if isinstance(value, (np.bool_, bool)):
                value = bool(value)
            elif pd.isna(value) if not isinstance(value, (list, tuple)) else False:
                value = None
            cell = worksheet.cell(row=row_offset, column=column_index, value=value)
            cell.alignment = Alignment(vertical="top", wrap_text=column == "Description")

            if column == "Date" and value is not None:
                cell.number_format = EXCEL_DATE_FORMAT
            elif column == "Amount":
                cell.number_format = EXCEL_PKR_FORMAT
            elif column == "risk_score":
                cell.number_format = "0"

        level = str(row.get("risk_level", "Low"))
        fill = _RISK_FILLS.get(level)
        if fill:
            for column_index in range(1, len(columns) + 1):
                worksheet.cell(row=row_offset, column=column_index).fill = fill

    last_row = max(1, len(frame) + 1)
    last_col = max(1, len(columns))
    worksheet.auto_filter.ref = f"A1:{get_column_letter(last_col)}{last_row}"

    widths = {
        "EntryID": 14,
        "Date": 12,
        "Account": 17,
        "Vendor": 26,
        "Description": 38,
        "Amount": 14,
        "PostedBy": 16,
        "ApprovedBy": 16,
        "risk_score": 11,
        "risk_level": 12,
        "flag_reasons": 60,
        "duplicate_of": 14,
        "risk_flags": 34,
        GROUND_TRUTH_COLUMN: 16,
    }
    for column_index, column in enumerate(columns, start=1):
        worksheet.column_dimensions[get_column_letter(column_index)].width = widths.get(
            column, 14
        )

    _neutralize_formula_cells(worksheet)


def _breakdown_sheet(worksheet: Worksheet, frame: pd.DataFrame) -> None:
    """Write counts and amounts by flag type and by vendor."""
    worksheet.sheet_view.showGridLines = False
    worksheet.merge_cells("A1:F1")
    worksheet["A1"] = "Flag Breakdown"
    worksheet["A1"].font = _TITLE_FONT
    worksheet.row_dimensions[1].height = 28

    flagged_total = max(1, len(frame))
    rows = []
    for column in FLAG_COLUMNS:
        mask = frame[column].astype(bool) if column in frame.columns else pd.Series(False, index=frame.index)
        count = int(mask.sum())
        amount = float(pd.to_numeric(frame.loc[mask, "Amount"], errors="coerce").abs().sum())
        rows.append(
            (
                FLAG_LABELS[column],
                count,
                amount,
                _safe_ratio(count, flagged_total),
                float(DEFAULT_WEIGHTS[column]),
            )
        )

    next_row = _write_table(
        worksheet,
        3,
        ("Flag type", "Flagged entries", "Amount (Rs.)", "% of flagged", "Weight"),
        rows,
        number_formats={2: "#,##0", 3: EXCEL_PKR_FORMAT, 4: "0.0%", 5: "0"},
    )

    vendor_rows = []
    if not frame.empty:
        working = frame.copy()
        working["abs_amount"] = pd.to_numeric(working["Amount"], errors="coerce").abs()
        for vendor, group in working.groupby("Vendor", dropna=False):
            top_flag = ""
            if not group.empty:
                counts = {
                    FLAG_LABELS[column]: int(group[column].astype(bool).sum())
                    for column in FLAG_COLUMNS
                    if column in group.columns
                }
                if counts and max(counts.values()) > 0:
                    top_flag = max(counts, key=counts.get)
            vendor_rows.append(
                (
                    str(vendor),
                    len(group),
                    float(group["abs_amount"].sum()),
                    int(group["risk_score"].max()) if "risk_score" in group else 0,
                    top_flag,
                )
            )
        vendor_rows.sort(key=lambda item: item[2], reverse=True)

    _write_table(
        worksheet,
        next_row,
        ("Vendor", "Flagged entries", "Amount (Rs.)", "Max risk", "Most common flag"),
        vendor_rows[:40],
        number_formats={2: "#,##0", 3: EXCEL_PKR_FORMAT, 4: "0"},
    )

    for letter, width in {"A": 28, "B": 16, "C": 18, "D": 16, "E": 22}.items():
        worksheet.column_dimensions[letter].width = width


def _explanations_sheet(
    worksheet: Worksheet,
    frame: pd.DataFrame,
    explanations: Mapping[str, str],
) -> None:
    """Write rule-based or LLM explanations with wrapped text."""
    worksheet.sheet_view.showGridLines = False
    headers = ("Entry ID", "Risk Level", "Amount (Rs.)", "Flags", "Explanation")
    rows = []
    for _, row in frame.iterrows():
        entry_id = str(row.get("EntryID", ""))
        text = explanations.get(entry_id, "")
        rows.append(
            (
                entry_id,
                str(row.get("risk_level", "")),
                float(row.get("Amount", 0) or 0),
                str(row.get("risk_flags", "")),
                text,
            )
        )

    _write_table(worksheet, 1, headers, rows, number_formats={3: EXCEL_PKR_FORMAT})
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = f"A1:E{max(1, len(rows) + 1)}"
    widths = {"A": 14, "B": 12, "C": 14, "D": 34, "E": 100}
    for letter, width in widths.items():
        worksheet.column_dimensions[letter].width = width
    for cell in worksheet["E"][1:]:
        cell.alignment = Alignment(vertical="top", wrap_text=True)
    _neutralize_formula_cells(worksheet)


def _methodology_sheet(worksheet: Worksheet) -> None:
    """Document each rule, its logic, and its risk weight."""
    worksheet.sheet_view.showGridLines = False
    worksheet.merge_cells("A1:D1")
    worksheet["A1"] = "Methodology"
    worksheet["A1"].font = _TITLE_FONT
    worksheet.row_dimensions[1].height = 28

    rows = (
        (
            "Duplicate",
            "Same vendor and amount within 7 days; both rows are flagged and the partner Entry ID is recorded. A shared invoice reference is reported as stronger evidence.",
            DEFAULT_WEIGHTS["flag_duplicate"],
        ),
        (
            "Round amount",
            "Amount is an exact multiple of the round threshold (Rs. 1,000) and at least Rs. 10,000.",
            DEFAULT_WEIGHTS["flag_round"],
        ),
        (
            "Weekend posting",
            "Posting date falls on a configured weekend day (Saturday + Sunday by default) or a configured Pakistan holiday.",
            DEFAULT_WEIGHTS["flag_weekend"],
        ),
        (
            "Just below limit",
            "Amount sits between 95% and 99.99% of the approval limit (Rs. 500,000 by default).",
            DEFAULT_WEIGHTS["flag_threshold"],
        ),
        (
            "Self-approval",
            "ApprovedBy matches PostedBy, breaking segregation of duties.",
            DEFAULT_WEIGHTS["flag_self_approval"],
        ),
        (
            "Benford deviation",
            "Vendors with 15+ entries are tested with a first-digit chi-square against Benford's Law; p < 0.01 flags every entry of that vendor.",
            DEFAULT_WEIGHTS["flag_benford"],
        ),
    )
    next_row = _write_table(
        worksheet,
        3,
        ("Rule", "Logic", "Risk weight"),
        rows,
        number_formats={3: "0"},
    )

    notes = (
        ("Risk levels", "Low 0-19, Medium 20-39, High 40-69, Critical 70+."),
        (
            "Risk score",
            "Sum of active rule weights, capped at 100. Advanced settings can change weights and thresholds.",
        ),
        (
            "Overall risk score",
            "0.7 × average risk of flagged entries + 3 × flagged percentage, capped at 100.",
        ),
        (
            "Amount at risk",
            "Absolute amount of every entry with at least one flag, shown in PKR (Rs.).",
        ),
        (
            "ISA 240",
            "Journal-entry testing for fraud risk is a concept from ISA 240. AuditGuard "
            "supports the auditor's risk assessment; it is decision support, not an audit opinion.",
        ),
    )
    _write_table(worksheet, next_row, ("Topic", "Definition"), notes)

    for letter, width in {"A": 24, "B": 90, "C": 14, "D": 14}.items():
        worksheet.column_dimensions[letter].width = width
    for row in worksheet.iter_rows(min_row=3):
        for cell in row:
            cell.alignment = Alignment(vertical="top", wrap_text=True)


def build_audit_report(
    df_flagged: pd.DataFrame,
    summary: Mapping[str, object],
    explanations: object = None,
) -> bytes:
    """Build the five-sheet Excel audit report and return its bytes."""
    from openpyxl import Workbook

    frame = _prepare_flagged(df_flagged)
    explanation_lookup = _explanation_map(explanations)

    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "Summary"
    _summary_sheet(summary_sheet, summary, frame)

    flagged_sheet = workbook.create_sheet("Flagged Entries")
    _flagged_sheet(flagged_sheet, frame)

    breakdown_sheet = workbook.create_sheet("Flag Breakdown")
    _breakdown_sheet(breakdown_sheet, frame)

    explanations_sheet = workbook.create_sheet("AI Explanations")
    _explanations_sheet(explanations_sheet, frame, explanation_lookup)

    methodology_sheet = workbook.create_sheet("Methodology")
    _methodology_sheet(methodology_sheet)

    for sheet, color in (
        (summary_sheet, "7C3AED"),
        (flagged_sheet, "22D3EE"),
        (breakdown_sheet, "34D399"),
        (explanations_sheet, "FBBF24"),
        (methodology_sheet, "FB923C"),
    ):
        sheet.sheet_properties.tabColor = color

    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
