"""AuditGuard — AI-powered audit red-flag dashboard (Streamlit entry point).

Localized for Karachi, Pakistan: amounts in Pakistani rupees, dates in
MM/DD/YYYY, Asia/Karachi timestamps, Pakistani weekends and public holidays,
and an optional Groq-powered explainer that only ever sees structured facts.
"""

from __future__ import annotations

import hashlib
import html
import io
import json
import re
from collections.abc import Mapping
from contextlib import nullcontext
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import ai_explainer
import calendar_view
import groq_client
import ui
from data_generator import DATASET_NAME, generate_ledger, write_datasets
from detection import (
    DEFAULT_APPROVAL_LIMIT,
    DEFAULT_ROUND_THRESHOLD,
    DEFAULT_WEIGHTS,
    FLAG_COLUMNS,
    FLAG_LABELS,
    GROUND_TRUTH_COLUMN,
    REQUIRED_COLUMNS,
    RISK_LEVELS,
    ambiguous_date_count,
    benford_table,
    build_summary,
    prepare_ledger,
    run_all_checks,
    validate_input,
)
from export import build_audit_report, compute_accuracy, dataframe_to_excel_bytes
from utils import (
    CUSTOM_FINANCIAL_YEAR_MODE,
    CUSTOM_FY_MODE_PREFIX,
    CUSTOM_WEEKEND_OPTION,
    DEFAULT_FINANCIAL_YEAR_MODE,
    DEFAULT_INPUT_DATE_FORMAT,
    FINANCIAL_YEAR_MODES,
    INPUT_DATE_FORMATS,
    ISLAMIC_HOLIDAY_SUGGESTIONS,
    MONTH_NAMES,
    WEEKDAY_NAMES,
    WEEKEND_PRESETS,
    financial_year_label,
    financial_year_months,
    format_date,
    format_datetime,
    format_pkr,
    now_karachi,
    pakistan_holidays,
    resolve_weekend_days,
)

try:  # Optional .env support; keys still live only in session state.
    from dotenv import load_dotenv

    load_dotenv()
except Exception:  # pragma: no cover - python-dotenv is optional at runtime
    pass

XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FLAG_LABEL_OPTIONS = {FLAG_LABELS[column]: column for column in FLAG_COLUMNS}
MAPPING_PLACEHOLDER = "— select column —"
DEMO_PATH = Path(__file__).resolve().parent / "data" / DATASET_NAME
GROQ_TEMPERATURE = 0.2
GROQ_MAX_TOKENS = 220
DEFAULT_LANGUAGE = "English"
LANGUAGES = ("English", "Roman Urdu")
FLAGGED_STYLE_MAX_ROWS = 500

GROQ_STATUS_TEXT = {
    "valid": "Key works.",
    "invalid": "Key rejected (401/403).",
    "rate-limited": "Rate limited (429); try later.",
    "error": "Network or server error.",
}

st.set_page_config(
    page_title="AuditGuard · Audit Red-Flag Dashboard",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Cached data builders
# ---------------------------------------------------------------------------


@st.cache_data(show_spinner=False)
def _demo_frame() -> pd.DataFrame:
    """Load the Karachi dataset's Ledger sheet, generating it if missing."""
    if DEMO_PATH.exists():
        try:
            workbook = pd.ExcelFile(DEMO_PATH, engine="openpyxl")
            sheet = "Ledger" if "Ledger" in workbook.sheet_names else workbook.sheet_names[0]
            return workbook.parse(sheet)
        except Exception:
            pass
    frame = generate_ledger()
    try:
        write_datasets()
    except Exception:
        pass
    return frame


@st.cache_data(show_spinner=False)
def _sample_workbook_bytes() -> bytes:
    """Return a downloadable labelled sample workbook."""
    return dataframe_to_excel_bytes(generate_ledger(), "AuditGuardKarachi")


@st.cache_data(show_spinner=False)
def _demo_holiday_text() -> str:
    """Return the moon-sighting holiday dates stored in the demo workbook."""
    if not DEMO_PATH.exists():
        return ""
    try:
        frame = pd.read_excel(
            DEMO_PATH, sheet_name="Pakistan_Holidays_2025", engine="openpyxl"
        )
    except Exception:
        return ""
    if frame.empty or "Date" not in frame.columns:
        return ""
    types = frame.get("Type", pd.Series("", index=frame.index)).astype(str)
    moon_rows = frame.loc[types.str.contains("moon", case=False, na=False), "Date"]
    dates = pd.to_datetime(moon_rows, errors="coerce").dropna()
    return ",\n".join(format_date(value) for value in dates)


# ---------------------------------------------------------------------------
# State and data loading
# ---------------------------------------------------------------------------


def _init_state() -> None:
    """Initialize session keys used across reruns."""
    defaults: dict[str, object] = {
        "raw_frame": None,
        "raw_name": None,
        "upload_digest": None,
        "upload_error": None,
        "mapping_error": None,
        "audit_frame": None,
        "summary": None,
        "audit_errors": [],
        "audit_warnings": [],
        "holiday_names": {},
        "status": "Ready",
        "exec_summary": None,
        "exec_summary_language": None,
        "llm_cache": {},
        "approval_limit": float(DEFAULT_APPROVAL_LIMIT),
        "round_threshold": float(DEFAULT_ROUND_THRESHOLD),
        "use_pakistan_holidays": True,
        "extra_holidays_text": "",
        "weekend_choice": "Saturday + Sunday",
        "custom_weekend_days": ["Saturday", "Sunday"],
        "input_date_format": DEFAULT_INPUT_DATE_FORMAT,
        "financial_year_mode": DEFAULT_FINANCIAL_YEAR_MODE,
        "fy_start_month": "July",
        "use_lakh_crore": True,
        "use_llm": False,
        "groq_keys": [],
        "groq_key_input": "",
        "groq_key_status": {},
        "groq_models": groq_client.fallback_models(),
        "groq_models_error": "",
        "groq_model": groq_client.DEFAULT_MODEL,
        "ai_language": DEFAULT_LANGUAGE,
        "top_n": 10,
        "last_run": None,
    }
    for column in FLAG_COLUMNS:
        defaults[f"weight_{column}"] = float(DEFAULT_WEIGHTS[column])
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def _reset_audit() -> None:
    """Clear derived audit state when the ledger or settings change."""
    st.session_state.audit_frame = None
    st.session_state.summary = None
    st.session_state.audit_errors = []
    st.session_state.audit_warnings = []
    st.session_state.status = "Ready"
    st.session_state.exec_summary = None
    st.session_state.exec_summary_language = None
    st.session_state.llm_cache = {}
    st.session_state.last_run = None


def _read_upload(raw_bytes: bytes, file_name: str) -> pd.DataFrame:
    """Read an uploaded CSV or Excel file into a DataFrame.

    Excel workbooks use the ``Ledger`` sheet when present and the first sheet
    otherwise, so the labelled demo workbook and the blind upload both work.
    """
    lower_name = file_name.lower()
    if lower_name.endswith(".csv"):
        try:
            return pd.read_csv(
                io.BytesIO(raw_bytes),
                sep=None,
                engine="python",
                encoding="utf-8-sig",
            )
        except UnicodeDecodeError:
            return pd.read_csv(
                io.BytesIO(raw_bytes),
                sep=None,
                engine="python",
                encoding="latin-1",
            )
    workbook = pd.ExcelFile(io.BytesIO(raw_bytes), engine="openpyxl")
    sheet = "Ledger" if "Ledger" in workbook.sheet_names else workbook.sheet_names[0]
    return workbook.parse(sheet)


def _handle_upload(uploaded_file: object) -> None:
    """Read a newly uploaded file once, then clear stale audit results."""
    if uploaded_file is None:
        st.session_state.upload_digest = None
        return

    raw_bytes = uploaded_file.getvalue()
    digest = hashlib.sha256(raw_bytes).hexdigest()
    if digest == st.session_state.upload_digest:
        return

    st.session_state.upload_digest = digest
    st.session_state.mapping_error = None
    try:
        frame = _read_upload(raw_bytes, uploaded_file.name)
    except Exception as exc:
        st.session_state.raw_frame = None
        st.session_state.raw_name = None
        st.session_state.upload_error = (
            f"Could not read “{uploaded_file.name}”. Check that it is a valid "
            f".xlsx or .csv file. Details: {exc}"
        )
        _reset_audit()
        return

    if frame is None or frame.empty:
        st.session_state.raw_frame = None
        st.session_state.raw_name = None
        st.session_state.upload_error = "The uploaded file contains no data rows."
        _reset_audit()
        return

    frame.columns = [str(column).strip() for column in frame.columns]
    st.session_state.raw_frame = frame
    st.session_state.raw_name = uploaded_file.name
    st.session_state.upload_error = None
    _reset_audit()


def _load_demo(attached_digest: str | None) -> None:
    """Load the Karachi demo ledger and run the audit immediately."""
    frame = _demo_frame()
    st.session_state.raw_frame = frame
    st.session_state.raw_name = f"Karachi demo · {len(frame):,} entries · 2025"
    st.session_state.upload_digest = attached_digest
    st.session_state.upload_error = None
    st.session_state.mapping_error = None
    if not st.session_state.extra_holidays_text:
        st.session_state.extra_holidays_text = _demo_holiday_text()
    _reset_audit()
    _run_audit()


def _parse_holidays(text: str) -> tuple[list[pd.Timestamp], int]:
    """Parse a holiday list and return valid normalized dates plus errors.

    Accepts comma-, semicolon-, or newline-separated values in MM/DD/YYYY,
    YYYY-MM-DD, or DD/MM/YYYY order (MM/DD wins for ambiguous slash dates).
    """
    parts = [
        part.strip() for part in re.split(r"[,;\n]+", str(text or "")) if part.strip()
    ]
    valid: list[pd.Timestamp] = []
    invalid = 0
    for part in parts:
        value = pd.NaT
        for date_format in ("%m/%d/%Y", "%Y-%m-%d", "%d/%m/%Y"):
            value = pd.to_datetime(part, format=date_format, errors="coerce")
            if not pd.isna(value):
                break
        if pd.isna(value):
            invalid += 1
        else:
            valid.append(pd.Timestamp(value).normalize())
    return valid, invalid


def _date_bounds(value: object) -> tuple[object | None, object | None]:
    """Normalize a date_input value (single date, 1-tuple, or 2-tuple)."""
    if isinstance(value, (tuple, list)):
        if len(value) == 2:
            return value[0], value[1]
        if len(value) == 1:
            return value[0], value[0]
        return None, None
    if value:
        return value, value
    return None, None


def _holiday_map() -> tuple[dict[pd.Timestamp, str], int]:
    """Return holiday dates with names plus the count of unparseable entries."""
    names: dict[pd.Timestamp, str] = {}
    if st.session_state.use_pakistan_holidays:
        years = {2025}
        raw_frame = st.session_state.raw_frame
        if isinstance(raw_frame, pd.DataFrame) and "Date" in raw_frame.columns:
            prepared = prepare_ledger(
                raw_frame, input_date_format=st.session_state.input_date_format
            )
            dates = prepared["Date"].dropna()
            if not dates.empty:
                years = {int(year) for year in dates.dt.year.unique()}
        for year in sorted(years):
            for value, name in pakistan_holidays(year):
                names[value] = name

    extras, invalid = _parse_holidays(st.session_state.extra_holidays_text)
    for value in extras:
        names.setdefault(value, "Additional holiday (moon-sighting)")
    return names, invalid


def _weekend_days() -> tuple[int, ...]:
    """Return the selected weekend weekday numbers (Monday = 0)."""
    return resolve_weekend_days(
        st.session_state.weekend_choice,
        st.session_state.get("custom_weekend_days"),
    )


def _financial_year_mode() -> str:
    """Return the effective financial-year mode, including a custom start month."""
    mode = st.session_state.financial_year_mode
    if mode == CUSTOM_FINANCIAL_YEAR_MODE:
        month = MONTH_NAMES.index(st.session_state.fy_start_month) + 1
        return f"{CUSTOM_FY_MODE_PREFIX} {month}"
    return mode


def _run_audit() -> bool:
    """Validate, run every rule, and store the audit result in session state."""
    raw_frame = st.session_state.raw_frame
    if raw_frame is None:
        st.session_state.audit_errors = ["Load a ledger before running the audit."]
        return False

    input_format = st.session_state.input_date_format
    errors = validate_input(raw_frame, input_date_format=input_format)
    if errors:
        st.session_state.audit_errors = errors
        st.session_state.audit_frame = None
        st.session_state.summary = None
        st.session_state.status = "Ready"
        return False

    warnings: list[str] = []
    if input_format == "Auto-detect" and "Date" in raw_frame.columns:
        ambiguous = ambiguous_date_count(raw_frame["Date"])
        if ambiguous:
            warnings.append(
                f"{ambiguous:,} date(s) could be read two ways (for example "
                "05/06/2025). Choose MM/DD/YYYY or DD/MM/YYYY in the sidebar if "
                "the timeline looks wrong."
            )

    prepared = prepare_ledger(raw_frame, input_date_format=input_format)
    invalid_dates = int(prepared["Date"].isna().sum())
    if invalid_dates:
        examples = ", ".join(
            _text(value, f"row {position + 1}")
            for position, value in enumerate(
                prepared.loc[prepared["Date"].isna(), "EntryID"].head(3).tolist()
            )
        )
        suffix = f" (for example {examples})" if examples else ""
        warnings.append(
            f"{invalid_dates:,} row(s) have dates that could not be read with "
            f"{input_format}{suffix}. Date-based rules skip them; try a different "
            "input date format."
        )
    invalid_amounts = int(prepared["Amount"].isna().sum())
    if invalid_amounts:
        warnings.append(
            f"{invalid_amounts:,} row(s) have non-numeric amounts and will skip "
            "amount-based rules."
        )

    holiday_names, invalid_holidays = _holiday_map()
    if invalid_holidays:
        warnings.append(
            f"{invalid_holidays} holiday date(s) could not be parsed and were ignored. "
            "Use MM/DD/YYYY or YYYY-MM-DD."
        )

    weights = {
        column: float(st.session_state[f"weight_{column}"]) for column in FLAG_COLUMNS
    }
    weekend_days = _weekend_days()

    try:
        with st.spinner(
            "Running duplicate, round, weekend, threshold, self-approval, and Benford checks…"
        ):
            checked = run_all_checks(
                raw_frame,
                approval_limit=float(st.session_state.approval_limit),
                round_threshold=float(st.session_state.round_threshold),
                holidays=list(holiday_names),
                weights=weights,
                weekend_days=weekend_days,
                input_date_format=input_format,
            )
            summary = build_summary(checked)
    except Exception as exc:
        st.session_state.audit_errors = [f"The audit could not run: {exc}"]
        st.session_state.audit_frame = None
        st.session_state.summary = None
        st.session_state.status = "Ready"
        return False

    st.session_state.audit_frame = checked
    st.session_state.summary = summary
    st.session_state.audit_errors = []
    st.session_state.audit_warnings = warnings
    st.session_state.holiday_names = holiday_names
    st.session_state.status = "Audit complete"
    st.session_state.exec_summary = None
    st.session_state.exec_summary_language = None
    st.session_state.llm_cache = {}
    st.session_state.last_run = now_karachi()
    st.toast(
        f"Audit complete: {summary['flagged_entries']:,} flagged of "
        f"{summary['total_entries']:,} entries"
    )
    return True


# ---------------------------------------------------------------------------
# Groq key management (session state only)
# ---------------------------------------------------------------------------


def _effective_groq_keys() -> list[str]:
    """Return session keys first, then optional GROQ_API_KEYS environment keys."""
    combined = groq_client.normalize_keys(st.session_state.get("groq_keys", []))
    for key in groq_client.env_keys():
        if key not in combined:
            combined.append(key)
    return combined


def _add_groq_keys() -> None:
    """Callback that adds one or more pasted keys without echoing them."""
    new_keys = groq_client.normalize_keys(st.session_state.get("groq_key_input", ""))
    if new_keys:
        existing = list(st.session_state.get("groq_keys", []))
        for key in new_keys:
            if key not in existing:
                existing.append(key)
        st.session_state.groq_keys = existing
    st.session_state.groq_key_input = ""


def _remove_groq_key(index: int) -> None:
    """Callback that removes one key by position."""
    keys = list(st.session_state.get("groq_keys", []))
    if 0 <= index < len(keys):
        removed = keys.pop(index)
        st.session_state.groq_keys = keys
        st.session_state.groq_key_status.pop(groq_client.masked(removed), None)


def _clear_groq_keys() -> None:
    """Callback that clears every session key."""
    st.session_state.groq_keys = []
    st.session_state.groq_key_status = {}


def _test_groq_key(index: int) -> None:
    """Callback that checks one key and stores a status label."""
    keys = list(st.session_state.get("groq_keys", []))
    if not 0 <= index < len(keys):
        return
    key = keys[index]
    status = groq_client.GroqClient([key]).test_key(key)
    st.session_state.groq_key_status[groq_client.masked(key)] = status


def _refresh_groq_models() -> None:
    """Callback that reloads the model list from Groq."""
    keys = _effective_groq_keys()
    if not keys:
        st.session_state.groq_models = groq_client.fallback_models()
        st.session_state.groq_models_error = "Add a key to load the live model list."
        return
    models = groq_client.GroqClient(keys).list_models()
    if models:
        st.session_state.groq_models = models
        st.session_state.groq_models_error = ""
        if st.session_state.get("groq_model") not in models:
            st.session_state.groq_model = models[0]
    else:
        st.session_state.groq_models = groq_client.fallback_models()
        st.session_state.groq_models_error = (
            "Could not load the live model list; built-in choices are shown."
        )


def _prefill_islamic_holidays() -> None:
    """Callback that fills the holiday box with moon-sighting dates."""
    text = _demo_holiday_text()
    if not text:
        text = ",\n".join(
            format_date(pd.Timestamp(2025, month, day))
            for (month, day), _ in ISLAMIC_HOLIDAY_SUGGESTIONS
        )
    st.session_state.extra_holidays_text = text


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------


def _reset_advanced() -> None:
    """Callback that restores the default weights and round threshold."""
    for column in FLAG_COLUMNS:
        st.session_state[f"weight_{column}"] = float(DEFAULT_WEIGHTS[column])
    st.session_state.round_threshold = float(DEFAULT_ROUND_THRESHOLD)


def _render_sidebar() -> None:
    """Render dataset controls, localization settings, Groq settings, and tuning."""
    with st.sidebar:
        st.markdown(
            '<div class="ag-sidebar-brand">'
            '<div class="ag-sidebar-mark">AG</div>'
            '<div><div class="ag-sidebar-logo">AuditGuard</div>'
            '<div class="ag-sidebar-tagline">AI-powered audit red-flag detection · Karachi, Pakistan</div></div>'
            "</div>",
            unsafe_allow_html=True,
        )
        st.divider()

        st.markdown("### Data source")
        uploaded = st.file_uploader(
            "Upload ledger (.xlsx or .csv)",
            type=["xlsx", "xlsm", "csv"],
            help="Required columns: "
            + ", ".join(REQUIRED_COLUMNS)
            + ". Excel files may use a Ledger sheet; otherwise the first sheet is read.",
        )
        attached_digest = (
            hashlib.sha256(uploaded.getvalue()).hexdigest()
            if uploaded is not None
            else None
        )
        if uploaded is not None:
            _handle_upload(uploaded)

        if st.button("Load Demo Data", width="stretch"):
            _load_demo(attached_digest)

        if st.session_state.raw_name:
            st.caption(f"Loaded: {st.session_state.raw_name}")

        st.markdown("### Audit settings")
        st.number_input(
            "Approval limit (Rs.)",
            min_value=1_000.0,
            max_value=10_000_000.0,
            step=1_000.0,
            key="approval_limit",
            help="Entries between 95% and 99.99% of this limit trigger the just-below-limit rule.",
        )
        st.toggle(
            "Lakh/Crore number format",
            key="use_lakh_crore",
            help="Show 12,50,000 instead of 1,250,000 in cards, tables, charts, and CSV. "
            "The Excel report keeps international grouping.",
        )
        st.selectbox(
            "Weekend days",
            [*WEEKEND_PRESETS, CUSTOM_WEEKEND_OPTION],
            key="weekend_choice",
            help="Pakistan offices commonly observe Saturday + Sunday. Choose Sunday only "
            "for a six-day working week, or Custom to pick any working-week pattern.",
        )
        if st.session_state.weekend_choice == CUSTOM_WEEKEND_OPTION:
            st.multiselect(
                "Custom weekend days",
                list(WEEKDAY_NAMES),
                key="custom_weekend_days",
                help="Pick every non-working weekday. At least one day is required; "
                "if the list is empty, Saturday + Sunday is used.",
            )
        st.selectbox(
            "Financial year",
            [*FINANCIAL_YEAR_MODES, CUSTOM_FINANCIAL_YEAR_MODE],
            key="financial_year_mode",
            help="Controls the month order in the Calendar tab. Pick Custom to start "
            "the year in any month, for example a July–June or April–March cycle.",
        )
        if st.session_state.financial_year_mode == CUSTOM_FINANCIAL_YEAR_MODE:
            st.selectbox(
                "Financial year starts in",
                list(MONTH_NAMES),
                key="fy_start_month",
                help="The financial year runs twelve months from this month.",
            )
        st.selectbox(
            "Input date format",
            list(INPUT_DATE_FORMATS),
            key="input_date_format",
            help="How text dates in your file should be read. True Excel date cells are "
            "always read directly.",
        )

        st.markdown("### Holidays")
        st.toggle(
            "Pakistan public holidays",
            key="use_pakistan_holidays",
            help="Kashmir Day 02/05, Pakistan Day 03/23, Labour Day 05/01, "
            "Youm-e-Takbeer 05/28, Independence Day 08/14, Iqbal Day 11/09, "
            "Quaid-e-Azam Day 12/25.",
        )
        st.text_area(
            "Extra holidays (moon-sighting dates)",
            key="extra_holidays_text",
            height=90,
            placeholder="03/31/2025, 06/07/2025",
            help="Comma or newline separated. Accepts MM/DD/YYYY and YYYY-MM-DD. "
            "Islamic dates depend on moon sighting — verify before relying on them.",
        )
        st.button(
            "Prefill Islamic dates from dataset",
            on_click=_prefill_islamic_holidays,
            width="stretch",
        )
        with st.expander("Where do these holiday dates come from?"):
            st.caption(
                "Fixed holidays come from AuditGuard's built-in Pakistan calendar: "
                "Kashmir Day (02/05), Pakistan Day (03/23), Labour Day (05/01), "
                "Youm-e-Takbeer (05/28), Independence Day (08/14), Iqbal Day (11/09), "
                "and Quaid-e-Azam Day (12/25). They are applied automatically for every "
                "year in the ledger."
            )
            st.caption(
                "Extra holidays are exactly the dates you type in the box above. "
                "Prefill copies the four moon-sighting dates stored in the demo "
                "workbook's Pakistan_Holidays_2025 sheet: Eid ul Fitr (03/31), "
                "Eid ul Adha (06/07), Ashura (07/06), and Eid Milad un Nabi (09/05). "
                "Confirm them against the official moon-sighting notification."
            )

        if st.button(
            "Run Audit",
            type="primary",
            width="stretch",
            disabled=st.session_state.raw_frame is None,
        ):
            _run_audit()

        st.divider()
        st.markdown("### AI explanations")
        st.toggle(
            "Use LLM explanations (Groq)",
            key="use_llm",
            help="Optional. Falls back to rule-based explanations on any error, "
            "quota limit, or invented number.",
        )
        summary = st.session_state.summary
        flagged_total = int(summary["flagged_entries"]) if summary else 0
        max_explain = max(2, flagged_total) if summary else 20
        previous_n = int(st.session_state.get("top_n", 10))
        slider_key = f"top_n_slider_{max_explain}"
        st.slider(
            "Entries to explain with AI",
            min_value=1,
            max_value=max_explain,
            value=min(max(previous_n, 1), max_explain),
            key=slider_key,
            help="Choose any number up to the flagged entries in the current audit. "
            "The range grows with the audit result.",
        )
        st.session_state.top_n = int(st.session_state[slider_key])
        st.radio(
            "Explanation language",
            LANGUAGES,
            key="ai_language",
            horizontal=True,
        )

        with st.expander("Groq API keys"):
            st.caption(
                "Keys live only in this browser session. They are never written to "
                "disk, logs, the Excel report, or error messages."
            )
            st.text_input(
                "Add Groq key",
                type="password",
                key="groq_key_input",
                placeholder="gsk_... (paste one key at a time)",
                label_visibility="collapsed",
            )
            st.button("Add key", on_click=_add_groq_keys, width="stretch")

            session_keys = list(st.session_state.groq_keys)
            if session_keys:
                for position, key in enumerate(session_keys):
                    masked = groq_client.masked(key)
                    columns = st.columns([2.2, 0.8, 0.9])
                    columns[0].caption(masked)
                    columns[1].button(
                        "Test",
                        key=f"test_key_{position}",
                        on_click=_test_groq_key,
                        args=(position,),
                        width="stretch",
                    )
                    columns[2].button(
                        "Remove",
                        key=f"remove_key_{position}",
                        on_click=_remove_groq_key,
                        args=(position,),
                        width="stretch",
                    )
                    status = st.session_state.groq_key_status.get(masked)
                    if status:
                        st.caption(GROQ_STATUS_TEXT.get(status, "Unknown status."))
                st.button("Clear all keys", on_click=_clear_groq_keys, width="stretch")
            else:
                st.caption("No session keys yet.")

            env_count = len(groq_client.env_keys())
            if env_count:
                st.caption(f"{env_count} key(s) also loaded from GROQ_API_KEYS.")

            models = st.session_state.groq_models or groq_client.fallback_models()
            if st.session_state.get("groq_model") not in models:
                st.session_state.groq_model = models[0]
            st.selectbox(
                "Groq model",
                options=models,
                key="groq_model",
                help="Default: llama-3.3-70b-versatile. Speech, TTS, guard, and "
                "embedding models are excluded.",
            )
            st.button("Refresh models", on_click=_refresh_groq_models, width="stretch")
            if st.session_state.groq_models_error:
                st.caption(st.session_state.groq_models_error)
            st.caption(
                f"Default {groq_client.DEFAULT_MODEL}. Temperature {GROQ_TEMPERATURE}, "
                f"{GROQ_MAX_TOKENS} max tokens, 20-second timeout. Responses with invented "
                "numbers are discarded."
            )

        with st.expander("Advanced settings"):
            st.number_input(
                "Round amount threshold (Rs.)",
                min_value=100.0,
                max_value=100_000.0,
                step=100.0,
                key="round_threshold",
                help="Amounts must be exact multiples of this value and at least Rs. 10,000.",
            )
            for column in FLAG_COLUMNS:
                st.number_input(
                    FLAG_LABELS[column],
                    min_value=0,
                    max_value=100,
                    step=5,
                    key=f"weight_{column}",
                    help=f"Risk points added when {FLAG_LABELS[column].lower()} fires.",
                )
            st.button(
                "Reset advanced settings",
                on_click=_reset_advanced,
                width="stretch",
            )
            st.caption("Re-run the audit after changing weights or thresholds.")

        with st.expander("About AuditGuard"):
            st.markdown(
                "AuditGuard reads a journal ledger, applies six explainable audit "
                "tests, and produces a risk-ranked review list with an Excel report. "
                "No database is used; data stays in this session."
            )
            st.markdown(
                "**Rules:** duplicates, round amounts, weekend/holiday postings, "
                "just-below-limit amounts, self-approval, and Benford’s Law "
                "(ISA 240 fraud-risk concepts)."
            )
            st.caption(
                "Currency: Pakistani Rupee (Rs.). Dates: MM/DD/YYYY. "
                "Timestamps: Asia/Karachi. Prepared in Karachi, Pakistan."
            )
            st.download_button(
                "Download labelled sample workbook",
                data=_sample_workbook_bytes(),
                file_name="auditguard_karachi_sample.xlsx",
                mime=XLSX_MIME,
                width="stretch",
                help="606 synthetic Karachi entries with a GroundTruth column and "
                "the Pakistan holidays sheet.",
            )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _text(value: object, fallback: str = "") -> str:
    """Return trimmed text or a fallback for missing values."""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return fallback
    text = str(value).strip()
    return text or fallback


def _lakh_crore() -> bool:
    """Return the current lakh/crore grouping preference."""
    return bool(st.session_state.get("use_lakh_crore", True))


def _money(value: object, lakh_crore: bool | None = None) -> str:
    """Format an amount as Pakistani rupees."""
    return format_pkr(
        value, lakh_crore=_lakh_crore() if lakh_crore is None else lakh_crore
    )


def _compact_money(value: object) -> str:
    """Format a large amount compactly for KPI cards and chart labels."""
    return format_pkr(value, short=True, lakh_crore=_lakh_crore())


def _flags_text(row: Mapping[str, object]) -> str:
    """Return a comma-separated list of triggered flag labels."""
    return ", ".join(
        FLAG_LABELS[column]
        for column in FLAG_COLUMNS
        if bool(row.get(column, False))
    )


def _risk_cell(level: object) -> str:
    """Return CSS for a risk-level table cell."""
    colors = {
        "Low": ("rgba(52,211,153,0.16)", "#34d399"),
        "Medium": ("rgba(251,191,36,0.16)", "#fbbf24"),
        "High": ("rgba(251,146,60,0.18)", "#fb923c"),
        "Critical": ("rgba(248,113,113,0.20)", "#f87171"),
    }
    background, foreground = colors.get(str(level), colors["Low"])
    return f"background-color: {background}; color: {foreground}; font-weight: 700;"


def _go_config() -> dict[str, object]:
    """Return Plotly config that keeps the charts uncluttered."""
    return {"displayModeBar": False, "responsive": True}


# ---------------------------------------------------------------------------
# Shared UI blocks
# ---------------------------------------------------------------------------


def _render_how_it_works() -> None:
    """Render the rule walkthrough used on the landing and overview screens."""
    with st.expander("How it works"):
        st.markdown(
            "1. **Validate** the schema, dates, and amounts. Invalid rows are "
            "reported and skipped only where a rule needs that field.\n"
            "2. **Run six explainable tests** on every entry.\n"
            "3. **Score** each entry from 0-100 using transparent weights.\n"
            "4. **Investigate** the risk-ranked list and export an Excel or CSV file.\n"
            "5. **Measure** accuracy when the file includes a `GroundTruth` column."
        )
        st.markdown(
            "**The six rules**\n\n"
            "- **Duplicate:** same vendor and amount within 7 days; both rows are "
            "flagged and each records its partner’s Entry ID.\n"
            "- **Round amount:** exact multiples of Rs. 1,000 at or above Rs. 10,000.\n"
            "- **Weekend:** the configured weekend days (Saturday + Sunday by default) "
            "or a Pakistani public holiday.\n"
            "- **Just below limit:** 95%-99.99% of the approval limit.\n"
            "- **Self-approval:** the poster is also the approver.\n"
            "- **Benford:** vendors with 15+ entries are tested for a first-digit "
            "chi-square deviation at p < 0.01; all entries of a deviating vendor "
            "are flagged."
        )
        st.caption(
            "Weights: self-approval 35, duplicate 30, threshold 25, Benford 20, "
            "round 15, weekend 10. Risk levels: Low 0-19, Medium 20-39, High "
            "40-69, Critical 70+. Journal-entry fraud testing follows ISA 240."
        )


def _render_mapping(raw_frame: pd.DataFrame) -> None:
    """Render a column-mapping form when uploaded headers differ from the schema."""
    missing = [column for column in REQUIRED_COLUMNS if column not in raw_frame.columns]
    if not missing:
        return

    st.error(
        "This file is missing required column(s): "
        + ", ".join(missing)
        + ". Map them below, or rename the headers and upload again."
    )
    ui.section_title(
        "Map your columns",
        "Choose the uploaded column that matches each required AuditGuard field.",
    )

    options = [MAPPING_PLACEHOLDER] + [str(column) for column in raw_frame.columns]

    def norm(value: object) -> str:
        return re.sub(r"[^a-z0-9]", "", str(value).lower())

    aliases = {
        "EntryID": ("entryid", "entry", "id", "entrynumber", "journalid", "transactionid"),
        "Date": ("date", "postingdate", "entrydate", "transactiondate", "gldate"),
        "Account": ("account", "accountname", "glaccount", "ledgeraccount", "category"),
        "Vendor": ("vendor", "vendorname", "supplier", "payee", "merchant"),
        "Description": ("description", "memo", "narration", "details", "narrative"),
        "Amount": ("amount", "amountpkr", "amountrs", "value", "total", "debit", "grossamount"),
        "PostedBy": ("postedby", "preparedby", "poster", "createdby", "employee"),
        "ApprovedBy": ("approvedby", "approver", "authorisedby", "authorizedby"),
    }
    normalized_columns = {norm(column): str(column) for column in raw_frame.columns}

    selections: dict[str, str] = {}
    columns = st.columns(2)
    for position, column in enumerate(missing):
        guess = None
        for alias in aliases.get(column, (norm(column),)):
            if alias in normalized_columns:
                guess = normalized_columns[alias]
                break
        with columns[position % 2]:
            index = options.index(guess) if guess in options else 0
            selections[column] = st.selectbox(
                f"{column} *",
                options,
                index=index,
                key=f"mapping_{column}",
            )

    if st.session_state.mapping_error:
        st.error(st.session_state.mapping_error)

    if st.button("Apply mapping and run audit", type="primary"):
        chosen = [value for value in selections.values() if value != MAPPING_PLACEHOLDER]
        if len(chosen) != len(missing):
            st.session_state.mapping_error = "Select a source column for every required field."
            st.rerun()
        if len(set(chosen)) != len(chosen):
            st.session_state.mapping_error = "Two fields point to the same source column."
            st.rerun()
        reserved = set(REQUIRED_COLUMNS) - set(missing)
        if any(source in reserved for source in chosen):
            st.session_state.mapping_error = (
                "A selected source column is already used by another required field. "
                "Choose a different column."
            )
            st.rerun()

        mapped = raw_frame.rename(
            columns={source: target for target, source in selections.items()}
        )
        st.session_state.raw_frame = mapped
        st.session_state.mapping_error = None
        st.session_state.upload_error = None
        _reset_audit()
        _run_audit()
        st.rerun()


# ---------------------------------------------------------------------------
# Overview tab
# ---------------------------------------------------------------------------


def _flags_figure(summary: Mapping[str, object]) -> go.Figure:
    """Horizontal bar chart of flag counts by rule."""
    labels = [FLAG_LABELS[column] for column in FLAG_COLUMNS]
    counts = [int(summary["flag_counts"].get(column, 0)) for column in FLAG_COLUMNS]
    colors = ["#22d3ee", "#34d399", "#fbbf24", "#fb923c", "#f87171", "#a78bfa"]
    fig = go.Figure(
        go.Bar(
            x=counts,
            y=labels,
            orientation="h",
            marker=dict(color=colors, line=dict(color="rgba(255,255,255,0.22)", width=1)),
            text=counts,
            textposition="outside",
            cliponaxis=False,
            hovertemplate="%{y}: %{x} entries<extra></extra>",
        )
    )
    if not any(counts):
        fig.add_annotation(
            text="No flags — every entry passed all six rules",
            showarrow=False,
            font=dict(color="#b9b5d9", size=13),
        )
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
    fig.update_layout(
        title="Flags by type",
        xaxis_title="Entries",
        yaxis_title="",
        showlegend=False,
    )
    ui.style_fig(fig, 330)
    fig.update_layout(margin=dict(r=34))
    fig.update_yaxes(autorange="reversed")
    return fig


def _risk_donut(summary: Mapping[str, object]) -> go.Figure:
    """Donut chart of entries by risk level."""
    counts = [int(summary["risk_counts"].get(level, 0)) for level in RISK_LEVELS]
    total = sum(counts)
    colors = ["#34d399", "#fbbf24", "#fb923c", "#f87171"]
    shares = [(count / total * 100) if total else 0.0 for count in counts]
    labels = [f"{level} · {share:.1f}%" for level, share in zip(RISK_LEVELS, shares)]
    fig = go.Figure(
        go.Pie(
            labels=labels,
            values=counts,
            hole=0.62,
            marker=dict(colors=colors, line=dict(color="rgba(15,12,41,0.65)", width=2)),
            textinfo="percent",
            textposition="inside",
            insidetextorientation="horizontal",
            textfont=dict(size=12, color="#0f0c29"),
            hovertemplate="%{label}: %{value} entries<extra></extra>",
        )
    )
    fig.update_layout(title="Risk level mix")
    ui.style_fig(fig, 330)
    fig.update_layout(
        legend=dict(orientation="h", yanchor="top", y=-0.04, x=0.5, xanchor="center"),
        margin=dict(l=10, r=10, t=44, b=56),
    )
    return fig


def _timeline_figure(checked: pd.DataFrame) -> go.Figure:
    """Timeline of flagged amounts with MM/DD/YYYY dates and Rs. amounts."""
    flagged = checked[checked["flag_count"] > 0]
    fig = go.Figure()
    if flagged.empty:
        fig.add_annotation(
            text="No flagged entries to plot",
            showarrow=False,
            font=dict(color="#b9b5d9", size=13),
        )
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
    else:
        dates = flagged["Date"].map(format_date)
        custom = np.stack(
            [
                flagged["EntryID"].astype(str).to_numpy(),
                flagged["Vendor"].astype(str).to_numpy(),
                flagged["risk_level"].astype(str).to_numpy(),
                dates.to_numpy(),
            ],
            axis=-1,
        )
        fig.add_trace(
            go.Scattergl(
                x=flagged["Date"],
                y=pd.to_numeric(flagged["Amount"], errors="coerce"),
                mode="markers",
                marker=dict(
                    color="#f87171",
                    size=9,
                    line=dict(color="rgba(255,255,255,0.55)", width=1),
                    opacity=0.9,
                ),
                customdata=custom,
                hovertemplate=(
                    "%{customdata[0]} · %{customdata[1]}<br>"
                    "%{customdata[3]}<br>Rs. %{y:,.2f}<br>%{customdata[2]} risk"
                    "<extra></extra>"
                ),
                name="Flagged",
            )
        )
        fig.update_xaxes(tickformat="%m/%d/%Y")
    fig.update_layout(
        title="Flagged entries over time",
        yaxis_title="Amount (Rs.)",
        xaxis_title="",
        showlegend=False,
    )
    ui.style_fig(fig, 320)
    return fig


def _benford_figure(checked: pd.DataFrame) -> go.Figure:
    """Grouped bars comparing observed and expected first digits."""
    report = benford_table(checked)
    table = report["table"]
    p_value = report["p_value"]
    p_text = "p = n/a" if pd.isna(p_value) else f"p = {p_value:.4f}"
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=table["Digit"].astype(str),
            y=table["Expected %"],
            name="Expected",
            marker_color="#a78bfa",
            hovertemplate="Digit %{x} expected: %{y:.2f}%<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=table["Digit"].astype(str),
            y=table["Actual %"],
            name="Actual",
            marker_color="#22d3ee",
            hovertemplate="Digit %{x} actual: %{y:.2f}%<extra></extra>",
        )
    )
    fig.update_layout(
        title=f"Benford first digits ({p_text})",
        barmode="group",
        xaxis_title="Leading digit",
        yaxis_title="% of amounts",
        legend=dict(orientation="h", y=1.12),
    )
    ui.style_fig(fig, 340)
    return fig


def _vendor_figure(summary: Mapping[str, object]) -> go.Figure:
    """Horizontal bars of the top vendors by flagged amount in rupees."""
    vendors = summary.get("top_vendors") or []
    fig = go.Figure()
    if not vendors:
        fig.add_annotation(
            text="No vendor exposure to plot",
            showarrow=False,
            font=dict(color="#b9b5d9", size=13),
        )
        fig.update_xaxes(visible=False)
        fig.update_yaxes(visible=False)
    else:
        names = [str(item["vendor"]) for item in vendors]
        amounts = [float(item["amount_at_risk"]) for item in vendors]
        fig.add_trace(
            go.Bar(
                x=amounts,
                y=names,
                orientation="h",
                marker=dict(
                    color="#fb923c",
                    line=dict(color="rgba(255,255,255,0.22)", width=1),
                ),
                text=[_compact_money(value) for value in amounts],
                textposition="outside",
                cliponaxis=False,
                hovertemplate="%{y}: Rs. %{x:,.2f}<extra></extra>",
            )
        )
    fig.update_layout(
        title="Top vendors by flagged exposure",
        xaxis_title="Amount at risk (Rs.)",
        yaxis_title="",
        showlegend=False,
    )
    fig.update_xaxes(tickprefix="Rs. ")
    ui.style_fig(fig, 340)
    fig.update_yaxes(autorange="reversed")
    return fig


def _render_overview(
    checked: pd.DataFrame | None, summary: Mapping[str, object] | None
) -> None:
    """Render KPI cards, charts, and the rule walkthrough."""
    if checked is None or summary is None:
        ui.render_empty_state(
            "Overview unlocks after the audit",
            "Upload a ledger or load the Karachi demo, then press Run Audit in the sidebar.",
            icon="01",
        )
        return

    columns = st.container(key="kpi_overview").columns(4)
    with columns[0]:
        ui.kpi_card(
            "Total entries",
            f"{int(summary['total_entries']):,}",
            "journal rows reviewed",
            ui.ACCENTS["cyan"],
            help_text="Every row loaded into the current audit.",
        )
    with columns[1]:
        flagged = int(summary["flagged_entries"])
        ui.kpi_card(
            "Flagged entries",
            f"{flagged:,} ({float(summary['flagged_pct']):.1f}%)",
            "at least one rule fired",
            ui.ACCENTS["green"] if flagged == 0 else ui.ACCENTS["amber"],
            help_text="Rows with at least one red flag; the percentage is of all entries.",
        )
    with columns[2]:
        amount = summary["amount_at_risk"]
        ui.kpi_card(
            "Amount at risk",
            _compact_money(amount),
            _money(amount),
            ui.ACCENTS["orange"],
            help_text="Absolute value of every flagged entry, in Pakistani rupees.",
        )
    with columns[3]:
        level = str(summary["overall_risk_level"])
        ui.kpi_card(
            "Overall risk score",
            f"{float(summary['overall_risk_score']):.1f} / 100",
            f"{level} portfolio risk",
            ui.risk_color(level),
            help_text="0.7 × average flagged risk + 3 × flagged percentage, capped at 100.",
        )

    high = int(summary["risk_counts"].get("High", 0))
    critical = int(summary["risk_counts"].get("Critical", 0))
    st.caption(
        f"Priority review: {high:,} High and {critical:,} Critical entries. "
        "Amounts use " + ("lakh/crore grouping." if _lakh_crore() else "international grouping.")
    )

    st.write("")
    left, right = st.columns(2)
    with left:
        st.plotly_chart(_flags_figure(summary), width="stretch", config=_go_config())
    with right:
        st.plotly_chart(_risk_donut(summary), width="stretch", config=_go_config())

    st.plotly_chart(_timeline_figure(checked), width="stretch", config=_go_config())

    left, right = st.columns(2)
    with left:
        st.plotly_chart(_benford_figure(checked), width="stretch", config=_go_config())
    with right:
        st.plotly_chart(_vendor_figure(summary), width="stretch", config=_go_config())
    st.caption(
        "Benford’s Law is tested per vendor for vendors with at least 15 entries; "
        "a p-value below 0.01 flags every entry of that vendor."
    )

    _render_how_it_works()


# ---------------------------------------------------------------------------
# Flagged Entries tab
# ---------------------------------------------------------------------------


def _detail_body(row: pd.Series) -> str:
    """Build the HTML body of an entry detail card."""
    reasons = row.get("flag_reasons") or []
    reason_html = "".join(
        f"<li>{html.escape(str(reason))}</li>" for reason in reasons
    ) or "<li>No reasons recorded.</li>"
    flags_html = "".join(
        f'<span class="ag-tag">{html.escape(FLAG_LABELS[column])}</span>'
        for column in FLAG_COLUMNS
        if bool(row.get(column, False))
    )
    fields = [
        ("Entry ID", _text(row.get("EntryID"), "—")),
        ("Date", format_date(row.get("Date"))),
        ("Account", _text(row.get("Account"), "—")),
        ("Vendor", _text(row.get("Vendor"), "—")),
        ("Amount", _money(row.get("Amount"))),
    ]
    invoice = _text(row.get("duplicate_invoice"))
    if invoice:
        fields.append(("Invoice reference", invoice))
    fields.extend(
        [
            ("Posted by", _text(row.get("PostedBy"), "—")),
            ("Approved by", _text(row.get("ApprovedBy"), "—")),
            ("Risk score", f"{int(row.get('risk_score', 0))} / 100"),
        ]
    )
    detail_html = "".join(
        f'<div class="ag-detail"><div class="k">{html.escape(label)}</div>'
        f'<div class="v">{html.escape(value)}</div></div>'
        for label, value in fields
    )
    return (
        f"<div>{ui.risk_badge(row.get('risk_level'))}"
        f"<span style='margin-left:0.4rem;'>{flags_html}</span></div>"
        f'<div class="ag-detail-grid">{detail_html}</div>'
        f"<p><strong>Why it was flagged</strong></p>"
        f'<ul class="ag-reasons">{reason_html}</ul>'
        f"<p class='ag-note'>{html.escape(_text(row.get('Description'), ''))}</p>"
    )


def _related_duplicate(checked: pd.DataFrame, row: pd.Series) -> str | None:
    """Return an HTML summary of the earlier duplicate entry, when present."""
    duplicate_of = _text(row.get("duplicate_of"))
    if not duplicate_of:
        return None
    related = checked[checked["EntryID"].astype(str) == duplicate_of]
    if related.empty and duplicate_of.startswith("ROW-"):
        try:
            position = int(duplicate_of.split("-")[1]) - 1
        except (IndexError, ValueError):
            position = -1
        if 0 <= position < len(checked):
            related = checked.iloc[[position]]
    if related.empty:
        return None
    first = related.iloc[0]
    invoice = _text(first.get("duplicate_invoice"))
    fields = [
        ("Earlier entry", _text(first.get("EntryID"), duplicate_of)),
        ("Date", format_date(first.get("Date"))),
        ("Amount", _money(first.get("Amount"))),
        ("Vendor", _text(first.get("Vendor"), "—")),
    ]
    if invoice:
        fields.append(("Invoice reference", invoice))
    return (
        '<div class="ag-detail-grid">'
        + "".join(
            f'<div class="ag-detail"><div class="k">{html.escape(label)}</div>'
            f'<div class="v">{html.escape(value)}</div></div>'
            for label, value in fields
        )
        + "</div>"
    )


def _flagged_display_table(display: pd.DataFrame) -> pd.DataFrame:
    """Apply risk styling only to tables small enough for Streamlit's Styler limit."""
    if len(display) > FLAGGED_STYLE_MAX_ROWS:
        return display
    return display.style.map(_risk_cell, subset=["Risk Level"])


def _render_flagged(checked: pd.DataFrame | None) -> None:
    """Render filters, the risk-ranked table, and the entry detail card."""
    if checked is None:
        ui.render_empty_state(
            "No flagged entries yet",
            "Run the audit to rank red-flagged journal entries by risk.",
            icon="02",
        )
        return

    flagged = checked[checked["flag_count"] > 0].copy()
    flagged = flagged.sort_values("risk_score", ascending=False, kind="stable")
    if flagged.empty:
        ui.render_empty_state(
            "Clean ledger — zero flags",
            "No entry triggered any of the six rules. Try the demo data to see "
            "the investigation view in action.",
            icon="OK",
        )
        return

    ui.section_title(
        "Investigation filters",
        "Narrow the review list by risk, rule, vendor, date, or description.",
    )
    first_row = st.columns(4)
    with first_row[0]:
        risk_choice = st.multiselect(
            "Risk level",
            options=list(RISK_LEVELS),
            default=list(RISK_LEVELS),
            key="filter_risk",
        )
    with first_row[1]:
        flag_choice = st.selectbox(
            "Flag type",
            options=["All flag types"] + list(FLAG_LABEL_OPTIONS),
            key="filter_flag",
        )
    vendor_options = ["All vendors"] + sorted(
        flagged["Vendor"].dropna().astype(str).unique()
    )
    if st.session_state.get("filter_vendor") not in vendor_options:
        st.session_state.filter_vendor = "All vendors"
    with first_row[2]:
        vendor_choice = st.selectbox(
            "Vendor",
            options=vendor_options,
            key="filter_vendor",
        )
    with first_row[3]:
        min_risk = st.slider(
            "Minimum risk score",
            min_value=0,
            max_value=100,
            value=0,
            step=5,
            key="filter_min_risk",
        )

    valid_dates = flagged["Date"].dropna()
    second_row = st.columns([1.1, 1.4, 1.1])
    start_date = end_date = None
    with second_row[0]:
        if not valid_dates.empty:
            min_date = valid_dates.min().date()
            max_date = valid_dates.max().date()
            available = (min_date, max_date)
            if st.session_state.get("filter_dates_available") != available:
                st.session_state["filter_dates_available"] = available
                st.session_state["filter_dates"] = available
            date_range = st.date_input(
                "Date range",
                min_value=min_date,
                max_value=max_date,
                key="filter_dates",
                format="MM/DD/YYYY",
            )
            start_date, end_date = _date_bounds(date_range)
        else:
            st.caption("No parseable dates available for filtering.")
    with second_row[1]:
        search = st.text_input(
            "Description search",
            placeholder="e.g. invoice, consulting, licence",
            key="filter_search",
        )
    with second_row[2]:
        st.caption(f"{len(flagged):,} flagged entries available")

    mask = flagged["risk_level"].isin(risk_choice) & (
        flagged["risk_score"] >= min_risk
    )
    if vendor_choice != "All vendors":
        mask &= flagged["Vendor"].astype(str) == vendor_choice
    if flag_choice != "All flag types":
        mask &= flagged[FLAG_LABEL_OPTIONS[flag_choice]].astype(bool)
    if search:
        mask &= flagged["Description"].astype(str).str.contains(
            search, case=False, na=False, regex=False
        )
    if start_date is not None and end_date is not None:
        mask &= flagged["Date"].dt.normalize().between(
            pd.Timestamp(start_date), pd.Timestamp(end_date)
        )

    filtered = flagged.loc[mask].sort_values("risk_score", ascending=False, kind="stable")
    ui.section_title(
        f"Showing {len(filtered):,} of {len(flagged):,} flagged entries",
        "Sorted by risk score, highest first.",
    )

    if filtered.empty:
        st.info(
            "No entries match these filters. Widen the risk level, date range, or "
            "search text."
        )
        return

    display = pd.DataFrame(
        {
            "Entry ID": filtered["EntryID"].astype(str).to_numpy(),
            "Date": filtered["Date"].map(format_date).to_numpy(),
            "Vendor": filtered["Vendor"].fillna("—").to_numpy(),
            "Account": filtered["Account"].fillna("—").to_numpy(),
            "Amount (Rs.)": filtered["Amount"].map(_money).to_numpy(),
            "Risk Score": filtered["risk_score"].astype(int).to_numpy(),
            "Risk Level": filtered["risk_level"].astype(str).to_numpy(),
            "Flags": filtered.apply(_flags_text, axis=1).to_numpy(),
            "Description": filtered["Description"].fillna("").to_numpy(),
        }
    )
    st.dataframe(
        _flagged_display_table(display),
        hide_index=True,
        width="stretch",
        height=min(620, max(120, 45 + 34 * len(display))),
    )

    ui.section_title("Inspect an entry", "Pick an Entry ID to see every field and reason.")
    options = list(range(len(filtered)))

    def label(position: int) -> str:
        row = filtered.iloc[position]
        return (
            f"{_text(row.get('EntryID'), f'ROW-{position + 1}')} · "
            f"{_text(row.get('Vendor'), 'Unknown vendor')} · "
            f"{_money(row.get('Amount'))} · risk {int(row.get('risk_score', 0))}"
        )

    selection = st.selectbox(
        "Entry",
        options=options,
        format_func=label,
        key=f"entry_pick_{len(filtered)}",
    )
    row = filtered.iloc[int(selection)]
    ui.glass_card(
        f"{_text(row.get('EntryID'), 'Entry')} · {_text(row.get('Vendor'), 'Vendor')}",
        _detail_body(row),
        icon="ID",
    )
    related_html = _related_duplicate(checked, row)
    if related_html:
        ui.glass_card("Related duplicate entry", related_html, icon="DUP")


# ---------------------------------------------------------------------------
# AI Insights tab
# ---------------------------------------------------------------------------


def _explain_cache_key(row: pd.Series, model: str, language: str) -> str:
    """Return a cache key based on row facts, model, and language only."""
    facts = groq_client.facts_from_row(row)
    payload = json.dumps(
        {"facts": facts, "model": model, "language": language},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _explain_row(
    row: pd.Series,
    use_llm: bool,
    keys: list[str],
    model: str,
    language: str,
) -> tuple[str, str, bool]:
    """Return an explanation, source label, and whether Groq failed."""
    cache_key = _explain_cache_key(row, model, language)
    cached = st.session_state.llm_cache.get(cache_key)
    if cached is not None:
        text = cached.get("text") or ai_explainer.explain_entry(row, language)
        return text, cached.get("source", "Rule-based"), bool(cached.get("failed"))

    if use_llm and keys:
        text = groq_client.explain_entry(
            row,
            keys,
            model=model,
            language=language,
            temperature=GROQ_TEMPERATURE,
            max_tokens=GROQ_MAX_TOKENS,
        )
        if text:
            source = groq_client.source_label(model)
            st.session_state.llm_cache[cache_key] = {
                "text": text,
                "source": source,
                "failed": False,
            }
            return text, source, False
        st.session_state.llm_cache[cache_key] = {
            "text": "",
            "source": "Rule-based",
            "failed": True,
        }
        return ai_explainer.explain_entry(row, language), "Rule-based", True

    return ai_explainer.explain_entry(row, language), "Rule-based", False


def _actions_html(row: pd.Series, language: str) -> str:
    """Return an HTML list of recommended audit procedures."""
    actions = ai_explainer.recommended_actions(row, language=language)
    return "".join(f"<li>{html.escape(action)}</li>" for action in actions)


def _insight_body(row: pd.Series, explanation: str, source: str, language: str) -> str:
    """Build the body of a ranked insight card."""
    flags_html = "".join(
        f'<span class="ag-tag">{html.escape(FLAG_LABELS[column])}</span>'
        for column in FLAG_COLUMNS
        if bool(row.get(column, False))
    )
    return (
        f"<div>{ui.risk_badge(row.get('risk_level'))}"
        f"<span style='margin-left:0.45rem;'>{html.escape(_money(row.get('Amount')))}</span>"
        f"<span style='margin-left:0.45rem;'>{flags_html}</span></div>"
        f"<p style='margin-top:0.6rem;'>{html.escape(explanation)}</p>"
        f"<p class='ag-note'>Explanation source: {html.escape(source)}</p>"
        f"<p style='margin-bottom:0.2rem;'><strong>Recommended procedures</strong></p>"
        f'<ul class="ag-reasons">{_actions_html(row, language)}</ul>'
    )


def _render_insights(
    checked: pd.DataFrame | None, summary: Mapping[str, object] | None
) -> None:
    """Render the executive summary, top entries, and entry explainer."""
    if checked is None or summary is None:
        ui.render_empty_state(
            "AI insights appear after the audit",
            "Run the audit to get an executive summary and plain-English "
            "explanations for each flagged entry.",
            icon="AI",
        )
        return

    use_llm = bool(st.session_state.use_llm)
    keys = _effective_groq_keys()
    model = st.session_state.groq_model
    language = st.session_state.ai_language
    top_n = int(st.session_state.top_n)

    flagged = checked[checked["flag_count"] > 0].copy()
    flagged = flagged.sort_values("risk_score", ascending=False, kind="stable")
    top_entries = flagged.head(top_n)

    if (
        st.session_state.exec_summary is None
        or st.session_state.exec_summary_language != language
    ):
        st.session_state.exec_summary = ai_explainer.generate_executive_summary(
            summary, top_entries, language=language
        )
        st.session_state.exec_summary_language = language

    ui.glass_card(
        "Executive summary",
        f"<p>{html.escape(st.session_state.exec_summary)}</p>",
        icon="AI",
    )
    if st.button("Regenerate summary", key="regen_summary"):
        st.session_state.exec_summary = None
        st.toast("Executive summary will be regenerated")
        st.rerun()

    if use_llm and not keys:
        st.info(
            "Groq explanations are switched on, but no API key is set. "
            "Rule-based explanations are being used."
        )

    if flagged.empty:
        ui.glass_card(
            "Nothing to investigate",
            "<p>No entries were flagged, so there are no explanations to generate. "
            "The executive summary above reflects a clean ledger.</p>",
            icon="OK",
        )
        return

    ui.section_title(
        f"Top {min(top_n, len(flagged))} entries to investigate first",
        "Ranked by risk score, with the strongest evidence and next steps.",
    )

    explained: list[tuple[pd.Series, str, str]] = []
    failures = 0
    with st.spinner("Preparing explanations…") if use_llm and keys else nullcontext():
        for _, row in top_entries.iterrows():
            explanation, source, failed = _explain_row(
                row, use_llm, keys, model, language
            )
            failures += int(failed)
            explained.append((row, explanation, source))

    if failures:
        st.warning(
            f"Groq returned no usable answer for {failures} of {len(explained)} "
            "entries (quota, network, or a response with invented numbers). "
            "Rule-based explanations are shown instead."
        )

    for rank, (row, explanation, source) in enumerate(explained, start=1):
        entry_id = _text(row.get("EntryID"), f"Entry {rank}")
        vendor = _text(row.get("Vendor"), "Unknown vendor")
        ui.glass_card(
            f"{rank}. {entry_id} · {vendor}",
            _insight_body(row, explanation, source, language),
            icon=f"0{rank}",
        )

    ui.section_title("Explain any flagged entry")
    options = list(range(len(flagged)))

    def label(position: int) -> str:
        row = flagged.iloc[position]
        return (
            f"{_text(row.get('EntryID'), f'ROW-{position + 1}')} · "
            f"{_text(row.get('Vendor'), 'Unknown vendor')} · risk "
            f"{int(row.get('risk_score', 0))}"
        )

    selection = st.selectbox(
        "Flagged entry",
        options=options,
        format_func=label,
        key="ai_entry_pick",
    )
    row = flagged.iloc[int(selection)]
    with st.spinner("Preparing explanation…") if use_llm and keys else nullcontext():
        explanation, source, _failed = _explain_row(
            row, use_llm, keys, model, language
        )
    ui.glass_card(
        f"{_text(row.get('EntryID'), 'Entry')} · {_text(row.get('Vendor'), 'Vendor')}",
        _insight_body(row, explanation, source, language),
        icon="AI",
    )


# ---------------------------------------------------------------------------
# Calendar tab
# ---------------------------------------------------------------------------


def _monthly_figure(
    checked: pd.DataFrame, mode: str, start_year: int
) -> go.Figure:
    """Plot flagged entries for every month of the selected financial year."""
    months = financial_year_months(start_year, mode)
    labels = [pd.Timestamp(year, month, 1).strftime("%b %Y") for year, month in months]
    counts: list[int] = []
    risk_points: list[float] = []
    for year, month in months:
        month_mask = (
            (pd.to_datetime(checked["Date"], errors="coerce").dt.year == year)
            & (pd.to_datetime(checked["Date"], errors="coerce").dt.month == month)
            & (checked["flag_count"] > 0)
        )
        subset = checked.loc[month_mask]
        counts.append(int(len(subset)))
        risk_points.append(float(pd.to_numeric(subset["risk_score"], errors="coerce").sum()))

    fig = go.Figure(
        go.Bar(
            x=labels,
            y=counts,
            customdata=risk_points,
            marker=dict(
                color="#22d3ee",
                line=dict(color="rgba(255,255,255,0.22)", width=1),
            ),
            text=counts,
            textposition="outside",
            cliponaxis=False,
            hovertemplate=(
                "%{x}<br>%{y} flagged entries<br>Risk points: %{customdata:.0f}"
                "<extra></extra>"
            ),
        )
    )
    if not any(counts):
        fig.add_annotation(
            text="No flagged entries in this financial year",
            showarrow=False,
            font=dict(color="#b9b5d9", size=13),
        )
    fig.update_layout(
        title="Flagged entries by month",
        xaxis_title="",
        yaxis_title="Flagged entries",
        showlegend=False,
    )
    ui.style_fig(fig, 320)
    return fig


def _render_calendar(checked: pd.DataFrame | None) -> None:
    """Render financial-year-aware calendar heatmaps and date-level insights."""
    if checked is None:
        ui.render_empty_state(
            "Calendar unlocks after the audit",
            "Run the audit to see flagged days, weekends, holidays, and month-end patterns.",
            icon="CAL",
        )
        return

    mode = _financial_year_mode()
    weekend_days = _weekend_days()
    holiday_names, _invalid = _holiday_map()

    fy_options = calendar_view.financial_year_options(checked, mode)
    fy_labels = [financial_year_label(start, mode) for start in fy_options]
    default_start = calendar_view.default_financial_year(checked, mode)
    default_label = financial_year_label(default_start, mode)
    if st.session_state.get("calendar_fy") not in fy_labels:
        st.session_state.calendar_fy = (
            default_label if default_label in fy_labels else fy_labels[-1]
        )

    header_left, header_right = st.columns([1.2, 2])
    with header_left:
        selected_label = st.selectbox(
            "Financial year",
            options=fy_labels,
            key="calendar_fy",
            help="Financial years follow the sidebar setting, including a custom "
            "start month.",
        )
    start_year = fy_options[fy_labels.index(selected_label)]

    month_options = calendar_view.month_options(checked, mode, start_year)
    month_labels = [
        calendar_view.month_label(year, month) for year, month in month_options
    ]
    if not month_labels:
        st.info("No months fall inside this financial year.")
        return
    if st.session_state.get("calendar_month") not in month_labels:
        st.session_state.calendar_month = month_labels[-1]
    with header_right:
        month_text = st.selectbox(
            "Month",
            options=month_labels,
            key="calendar_month",
        )
    selected_index = month_labels.index(month_text)
    year, month = month_options[selected_index]

    cells = calendar_view.build_month_cells(
        checked,
        year,
        month,
        holidays=holiday_names,
        weekend_days=weekend_days,
    )
    ui.section_title(
        f"{month_text} · {financial_year_label(start_year, mode)}",
        "Cell colour follows flagged volume; weekends are shaded, holidays carry a "
        "star, and Critical days have a red outline.",
    )
    st.plotly_chart(
        calendar_view.month_heatmap(
            cells,
            title=f"Flagged entries · {month_text}",
            weekend_days=weekend_days,
        ),
        width="stretch",
        config=_go_config(),
    )

    insights = calendar_view.calendar_insights(
        checked, holidays=holiday_names, weekend_days=weekend_days
    )
    ins = st.container(key="kpi_calendar").columns(4)
    with ins[0]:
        ui.kpi_card(
            "Weekend / holiday flags",
            f"{int(insights['weekend_holiday_count']):,}",
            "postings off the working calendar",
            ui.ACCENTS["violet"],
            help_text="Entries flagged by the weekend rule, including configured holidays.",
        )
    with ins[1]:
        busiest_day = insights["busiest_day"]
        ui.kpi_card(
            "Busiest flagged day",
            format_date(busiest_day) if busiest_day is not None else "—",
            f"{int(insights['busiest_count']):,} flagged entries"
            if busiest_day is not None
            else "no flagged entries",
            ui.ACCENTS["amber"],
            help_text="The single day with the most flagged entries.",
        )
    with ins[2]:
        ui.kpi_card(
            "Month-end share",
            f"{float(insights['month_end_share']) * 100:.0f}%",
            f"{int(insights['month_end_count']):,} of "
            f"{int(insights['total_flagged']):,} flags in the last 3 working days",
            ui.ACCENTS["orange"],
            help_text="Compares the last three working days of each month with the rest.",
        )
    with ins[3]:
        top_month = insights["top_month"]
        top_text = (
            calendar_view.month_label(int(top_month.year), int(top_month.month))
            if isinstance(top_month, pd.Timestamp)
            else "—"
        )
        ui.kpi_card(
            "Top month by risk",
            top_text,
            f"{float(insights['top_month_risk']):,.0f} risk points",
            ui.ACCENTS["red"],
            help_text="The month whose flagged entries carry the highest total risk score.",
        )

    st.write("")
    st.plotly_chart(
        _monthly_figure(checked, mode, start_year),
        width="stretch",
        config=_go_config(),
    )
    st.plotly_chart(
        calendar_view.year_heatmap(
            checked,
            year,
            title=f"Flagged entries by day · {year}",
        ),
        width="stretch",
        config=_go_config(),
    )

    ui.section_title(
        "Inspect a day",
        "Pick any date in the selected month to list its entries and explanations.",
    )
    flagged_cells = [cell for cell in cells if int(cell["flagged"]) > 0]
    default_day = (
        pd.Timestamp(
            max(flagged_cells, key=lambda cell: int(cell["flagged"]))["date"]
        )
        if flagged_cells
        else pd.Timestamp(year, month, 1)
    )
    day_key = f"calendar_day_{year}_{month}"
    if day_key not in st.session_state:
        st.session_state[day_key] = default_day.date()
    picked = st.date_input(
        "Inspect a day",
        min_value=pd.Timestamp(year, month, 1).date(),
        max_value=pd.Timestamp(year, month, 1).date().replace(
            day=pd.Timestamp(year, month, 1).days_in_month
        ),
        key=day_key,
        format="MM/DD/YYYY",
    )

    entries = calendar_view.day_entries(checked, picked)
    if entries.empty:
        st.info(f"No entries were posted on {format_date(picked)}.")
        return

    day_display = pd.DataFrame(
        {
            "Entry ID": entries["EntryID"].astype(str).to_numpy(),
            "Date": entries["Date"].map(format_date).to_numpy(),
            "Vendor": entries["Vendor"].fillna("—").to_numpy(),
            "Amount (Rs.)": entries["Amount"].map(_money).to_numpy(),
            "Risk Score": entries["risk_score"].astype(int).to_numpy(),
            "Risk Level": entries["risk_level"].astype(str).to_numpy(),
            "Flags": entries.apply(_flags_text, axis=1).to_numpy(),
        }
    )
    st.dataframe(
        day_display.style.map(_risk_cell, subset=["Risk Level"]),
        hide_index=True,
        width="stretch",
    )

    flagged_day = entries[entries["flag_count"] > 0].head(3)
    use_llm = bool(st.session_state.use_llm)
    keys = _effective_groq_keys()
    model = st.session_state.groq_model
    language = st.session_state.ai_language
    for _, row in flagged_day.iterrows():
        with st.spinner("Preparing explanation…") if use_llm and keys else nullcontext():
            explanation, source, _failed = _explain_row(
                row, use_llm, keys, model, language
            )
        ui.glass_card(
            f"{_text(row.get('EntryID'), 'Entry')} · {_text(row.get('Vendor'), 'Vendor')}",
            _insight_body(row, explanation, source, language),
            icon="DAY",
        )


# ---------------------------------------------------------------------------
# Export & Accuracy tab
# ---------------------------------------------------------------------------


def _csv_frame(flagged: pd.DataFrame) -> pd.DataFrame:
    """Return a CSV-ready flagged-entry table in rupees and MM/DD/YYYY."""
    explanations: list[str] = []
    for _, row in flagged.iterrows():
        reasons = row.get("flag_reasons") or []
        if isinstance(reasons, list):
            explanations.append("; ".join(str(reason) for reason in reasons))
        else:
            explanations.append(str(reasons))
    frame = pd.DataFrame(
        {
            "EntryID": flagged["EntryID"].astype(str).to_numpy(),
            "Date": flagged["Date"].map(format_date).to_numpy(),
            "Account": flagged["Account"].fillna("").to_numpy(),
            "Vendor": flagged["Vendor"].fillna("").to_numpy(),
            "Description": flagged["Description"].fillna("").to_numpy(),
            "Amount (Rs.)": flagged["Amount"].map(_money).to_numpy(),
            "PostedBy": flagged["PostedBy"].fillna("").to_numpy(),
            "ApprovedBy": flagged["ApprovedBy"].fillna("").to_numpy(),
            "Risk score": flagged["risk_score"].astype(int).to_numpy(),
            "Risk level": flagged["risk_level"].astype(str).to_numpy(),
            "Flags": flagged.apply(_flags_text, axis=1).to_numpy(),
            "Reasons": explanations,
        }
    )
    if GROUND_TRUTH_COLUMN in flagged.columns:
        frame["Ground truth"] = flagged[GROUND_TRUTH_COLUMN].fillna("Clean").to_numpy()
    return frame


def _issue_table(frame: pd.DataFrame) -> pd.DataFrame:
    """Return a compact display table for missed anomalies or false alarms."""
    if frame.empty:
        return frame
    working = frame.copy()
    if "flag_reasons" in working.columns:
        working["flag_reasons"] = working["flag_reasons"].map(
            lambda value: "; ".join(str(part) for part in value)
            if isinstance(value, list)
            else str(value)
        )
    display = pd.DataFrame(
        {
            "Entry ID": working["EntryID"].astype(str).to_numpy(),
            "Date": working["Date"].map(format_date).to_numpy(),
            "Ground truth": working[GROUND_TRUTH_COLUMN].fillna("Clean").to_numpy(),
            "Vendor": working["Vendor"].fillna("—").to_numpy(),
            "Amount (Rs.)": working["Amount"].map(_money).to_numpy(),
            "Risk level": working["risk_level"].astype(str).to_numpy(),
            "Reasons": working["flag_reasons"].to_numpy()
            if "flag_reasons" in working.columns
            else "",
        }
    )
    return display


def _accuracy_kpis(accuracy: Mapping[str, object]) -> None:
    """Render overall accuracy KPI cards."""
    overall = accuracy["overall"]
    cards = [
        ("True positives", f"{overall['tp']:,}", "injected anomalies caught", ui.ACCENTS["green"]),
        ("False positives", f"{overall['fp']:,}", "flagged but labelled clean", ui.ACCENTS["orange"]),
        ("False negatives", f"{overall['fn']:,}", "injected anomalies missed", ui.ACCENTS["red"]),
        ("Precision", f"{overall['precision']:.1%}", "of flags were real", ui.ACCENTS["cyan"]),
        ("Recall", f"{overall['recall']:.1%}", "of anomalies found", ui.ACCENTS["green"]),
        ("F1 score", f"{overall['f1']:.1%}", "precision/recall balance", ui.ACCENTS["violet"]),
    ]
    for start in (0, 3):
        columns = st.container(key=f"kpi_accuracy_{start}").columns(3)
        for column, (label, value, sublabel, color) in zip(
            columns, cards[start : start + 3]
        ):
            with column:
                ui.kpi_card(label, value, sublabel, color)


def _confusion_figure(accuracy: Mapping[str, object]) -> go.Figure:
    """Plot the 2x2 confusion matrix as a heatmap."""
    overall = accuracy["overall"]
    values = [
        [overall["tn"], overall["fp"]],
        [overall["fn"], overall["tp"]],
    ]
    fig = go.Figure(
        go.Heatmap(
            z=values,
            x=["Predicted clean", "Predicted flagged"],
            y=["Actually clean", "Actually flagged"],
            text=[[str(value) for value in row] for row in values],
            texttemplate="%{text}",
            colorscale=[[0, "rgba(34,211,238,0.10)"], [1, "rgba(248,113,113,0.60)"]],
            showscale=False,
            hovertemplate="%{y} · %{x}: %{z}<extra></extra>",
        )
    )
    fig.update_layout(title="Confusion matrix")
    ui.style_fig(fig, 300)
    return fig


def _render_export(
    checked: pd.DataFrame | None, summary: Mapping[str, object] | None
) -> None:
    """Render downloads, accuracy metrics, and error review tables."""
    if checked is None or summary is None:
        ui.render_empty_state(
            "Reports appear after the audit",
            "Run the audit to download a five-sheet Excel report, a CSV of "
            "flagged entries, and accuracy metrics.",
            icon="03",
        )
        return

    language = st.session_state.ai_language
    model = st.session_state.groq_model
    flagged = checked[checked["flag_count"] > 0].copy()
    flagged = flagged.sort_values("risk_score", ascending=False, kind="stable")

    explanations: dict[str, str] = {}
    for _, row in flagged.iterrows():
        entry_id = _text(row.get("EntryID"))
        if not entry_id:
            continue
        cached = st.session_state.llm_cache.get(
            _explain_cache_key(row, model, language)
        )
        text = cached.get("text") if cached else ""
        explanations[entry_id] = text or ai_explainer.explain_entry(row, language)

    report_bytes = build_audit_report(flagged, summary, explanations)
    csv_bytes = _csv_frame(flagged).to_csv(index=False).encode("utf-8-sig")
    today = now_karachi().strftime("%m-%d-%Y")

    ui.section_title(
        "Download the audit package",
        "Reports are generated from the current audit state in rupees and MM/DD/YYYY.",
    )
    left, right = st.columns(2)
    with left:
        st.download_button(
            "Download Excel report",
            data=report_bytes,
            file_name=f"auditguard_report_{today}.xlsx",
            mime=XLSX_MIME,
            width="stretch",
        )
    with right:
        st.download_button(
            "Download flagged entries (CSV)",
            data=csv_bytes,
            file_name=f"auditguard_flagged_{today}.csv",
            mime="text/csv",
            width="stretch",
        )
    st.caption(
        f"Report timestamp: {format_datetime(now_karachi())} · "
        "Prepared in Karachi, Pakistan."
    )

    st.divider()
    accuracy = compute_accuracy(checked)
    if accuracy is None:
        ui.glass_card(
            "Accuracy testing needs GroundTruth",
            "<p>Upload a workbook that includes a <code>GroundTruth</code> column "
            "to see precision, recall, F1, and the error review tables. The "
            "labelled sample workbook in the sidebar is ready for this test.</p>",
            icon="GT",
        )
        return

    high = int((checked["risk_level"] == "High").sum())
    critical = int((checked["risk_level"] == "Critical").sum())
    ui.section_title(
        "Detection accuracy",
        f"Tested on {accuracy['tested_entries']:,} synthetic entries with "
        f"{accuracy['injected']:,} injected anomalies · High {high:,} · "
        f"Critical {critical:,}.",
    )
    _accuracy_kpis(accuracy)

    st.write("")
    left, right = st.columns([1, 1.1])
    with left:
        st.plotly_chart(_confusion_figure(accuracy), width="stretch", config=_go_config())
    with right:
        per_type = pd.DataFrame(
            [
                {
                    "Anomaly type": row["type"],
                    "Support": row["support"],
                    "TP": row["tp"],
                    "FP": row["fp"],
                    "FN": row["fn"],
                    "Precision": f"{row['precision']:.0%}",
                    "Recall": f"{row['recall']:.0%}",
                    "F1": f"{row['f1']:.0%}",
                }
                for row in accuracy["per_type"]
            ]
        )
        st.dataframe(per_type, hide_index=True, width="stretch", height=300)

    st.caption(
        "Overall, any flag counts as a predicted anomaly; a MultiRule row counts as "
        "detected only when at least two flags fire. Per-type precision is one-vs-rest "
        "over the single-rule labels and excludes MultiRule rows, so their intentional "
        "extra flags are not counted as false alarms."
    )

    missed = _issue_table(accuracy["missed"])
    false_alarms = _issue_table(accuracy["false_alarms"])
    ui.section_title(
        f"Missed anomalies ({len(missed):,})",
        "Injected anomalies that no rule caught.",
    )
    if missed.empty:
        st.caption("None — every injected anomaly was flagged by at least one rule.")
    else:
        st.dataframe(missed, hide_index=True, width="stretch")

    ui.section_title(
        f"False alarms ({len(false_alarms):,})",
        "Flags on rows labelled Clean or on a different anomaly type.",
    )
    if false_alarms.empty:
        st.caption("None — every flag matched an injected anomaly.")
    else:
        st.dataframe(false_alarms, hide_index=True, width="stretch")

    benford_clean = int(
        (
            (checked[GROUND_TRUTH_COLUMN].fillna("Clean").astype(str) == "Clean")
            & checked["flag_benford"]
        ).sum()
    )
    if benford_clean:
        ui.glass_card(
            "Vendor-level Benford flags",
            f"<p>{benford_clean:,} entries labelled Clean carry the Benford flag "
            "because their vendor’s digit mix deviates from Benford’s Law. This is a "
            "vendor-level test: once a vendor fails, every entry from that vendor is "
            "flagged for review rather than treated as a row-level error.</p>",
            icon="BF",
        )


# ---------------------------------------------------------------------------
# Guide tab
# ---------------------------------------------------------------------------


def _render_guide() -> None:
    """Render a plain-English guide to every feature."""
    ui.glass_card(
        "AuditGuard in one minute",
        "<p>AuditGuard reads a journal ledger in Pakistani rupees, runs six "
        "explainable audit tests, ranks each entry from 0 to 100, and produces a "
        "review list, a calendar of risky days, and an Excel report. Everything "
        "stays in this browser session — there is no database.</p>",
        icon="?" ,
    )

    with st.expander("1. Load a ledger or the Karachi demo"):
        st.markdown(
            "Upload an `.xlsx`, `.xlsm`, or `.csv` file with these columns: "
            "`EntryID`, `Date`, `Account`, `Vendor`, `Description`, `Amount`, "
            "`PostedBy`, and `ApprovedBy`. A `GroundTruth` column is optional and "
            "only used for accuracy testing. Excel files use the `Ledger` sheet when "
            "present; otherwise the first sheet. Press **Load Demo Data** for the "
            "606-entry synthetic Karachi ledger, which includes 549 Clean rows, "
            "51 single-rule anomalies, and 6 MultiRule rows."
        )

    with st.expander("2. Currency, dates, and Karachi settings"):
        st.markdown(
            "All amounts are in Pakistani rupees and appear as `Rs. 12,50,000` when "
            "**Lakh/Crore number format** is on, or `Rs. 1,250,000` when it is off. "
            "Dates always display as `MM/DD/YYYY`, and report timestamps use "
            "Asia/Karachi. The sidebar also controls the weekend (Saturday + Sunday "
            "default, Sunday only, or a Custom pattern), the financial year (July–June, "
            "January–December, or a Custom start month), and how text dates are read. "
            "The seven fixed Pakistan public holidays are applied automatically; add "
            "moon-sighting dates in the holiday box and verify them before relying on "
            "them. The box is prefilled from the demo workbook's "
            "`Pakistan_Holidays_2025` sheet; the **Where do these holiday dates come "
            "from?** section in the sidebar explains each source. For example, "
            "`03/31/2025` and `2025-06-07` are both accepted."
        )

    with st.expander("3. The six audit tests"):
        st.markdown(
            "- **Duplicate:** the same vendor and amount within seven days. Both rows "
            "are flagged and each shows its partner. If the descriptions share an "
            "invoice reference such as `INV-2025-0142`, the reason says so — stronger "
            "evidence without changing the seven-day rule.\n"
            "- **Round amount:** exact multiples of Rs. 1,000 at or above Rs. 10,000, "
            "for example Rs. 75,000.\n"
            "- **Weekend/holiday:** posted on the configured weekend or a Pakistani "
            "public holiday.\n"
            "- **Just below limit:** 95% to 99.99% of the approval limit, for example "
            "Rs. 4,87,500 against a Rs. 5,00,000 limit.\n"
            "- **Self-approval:** the same person posted and approved the entry.\n"
            "- **Benford:** vendors with at least 15 entries are tested for a "
            "first-digit chi-square deviation at p < 0.01; every entry of a deviating "
            "vendor is flagged for review."
        )

    with st.expander("4. Risk scoring"):
        st.markdown(
            "Each rule adds points: self-approval 35, duplicate 30, just-below-limit "
            "25, Benford 20, round 15, and weekend 10. Scores are capped at 100. "
            "Risk levels are Low 0–19, Medium 20–39, High 40–69, and Critical 70+. "
            "You can tune weights and the round threshold under **Advanced settings**; "
            "re-run the audit afterwards. MultiRule demo rows deliberately trip two or "
            "three rules and land in High or Critical."
        )

    with st.expander("5. Overview and flagged entries"):
        st.markdown(
            "The Overview tab shows totals, the amount at risk, the risk mix, flags by "
            "rule, the timeline, the Benford comparison, and the top vendors by "
            "flagged exposure. The Flagged Entries tab filters by risk, rule, vendor, "
            "date, and description. Pick any Entry ID to see its date, amount, invoice "
            "reference, reasons, and — for duplicates — the related earlier entry."
        )

    with st.expander("6. AI explanations with Groq"):
        st.markdown(
            "Groq is optional and off by default. Open **Groq API keys**, paste one or "
            "more keys, and press **Add key**; keys stay in this session only and are "
            "never written to disk, logs, the Excel report, or error messages. A "
            "broken or rate-limited key is skipped automatically. Only structured "
            "facts are sent: entry ID, date in MM/DD/YYYY, vendor, account, amount in "
            "Rs., poster, approver, risk score, flags, and reasons. The model is told "
            "to use only those facts, stay under three sentences, and write clear "
            "simple English. If the reply contains a number that is not in the facts, "
            "the reply is discarded and the rule-based template is used. You can "
            "switch between English and Roman Urdu, and choose exactly how many flagged "
            "entries get AI text — the range grows with the audit result, up to every "
            "flagged entry."
        )

    with st.expander("7. Calendar"):
        st.markdown(
            "The Calendar tab follows the selected financial year. The month heatmap "
            "colours each day by flagged volume, shades weekends, marks holidays with "
            "a star, and gives Critical days a red outline. The year heatmap works "
            "like a GitHub contribution graph. Four cards summarize weekend/holiday "
            "flags, the busiest day, the share of flags in the last three working days "
            "of each month, and the top month by risk. Pick a date to list its entries "
            "with badges and explanations. Zero-flag ledgers still render an empty "
            "calendar safely."
        )

    with st.expander("8. Export and accuracy"):
        st.markdown(
            "The Excel report has five sheets: Summary, Flagged Entries, Flag "
            "Breakdown, AI Explanations, and Methodology. Money uses the `Rs.` format, "
            "dates use `mm/dd/yyyy`, and the header says **Prepared in Karachi, "
            "Pakistan**. The CSV uses `MM/DD/YYYY` dates and an `Amount (Rs.)` column. "
            "With a `GroundTruth` column you also get precision, recall, F1, a "
            "confusion matrix, and per-type metrics. A MultiRule row counts as detected "
            "only when at least two flags fire, and per-type metrics exclude MultiRule "
            "rows. Vendor-level Benford flags on Clean rows are explained in a separate "
            "card."
        )

    with st.expander("9. Demo dataset and troubleshooting"):
        st.markdown(
            "The demo has 606 entries for 2025: 549 Clean, 12 Duplicate (6 pairs), "
            "5 RoundAmount, 5 Weekend, 6 JustBelowLimit, 5 SelfApproval, 18 "
            "BenfordManip from Madina Traders, and 6 MultiRule. The audit flags 57 "
            "entries with 4 High and 2 Critical. Common fixes: if dates look wrong, "
            "switch **Input date format**; if an entry is unexpectedly flagged on a "
            "holiday, check the moon-sighting dates; if every amount looks odd, toggle "
            "the lakh/crore format; if Groq text does not appear, check the key status "
            "and the notice above the cards."
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    """Compose the sidebar, hero, onboarding, and six dashboard tabs."""
    _init_state()
    ui.inject_css()
    _render_sidebar()
    ui.render_hero(
        status=st.session_state.status, ready=st.session_state.status == "Ready"
    )
    if st.session_state.last_run is not None:
        st.caption(
            f"Last audit: {format_datetime(st.session_state.last_run)} · Asia/Karachi"
        )

    raw_frame = st.session_state.raw_frame

    if st.session_state.upload_error:
        st.error(st.session_state.upload_error)

    if raw_frame is None:
        ui.render_empty_state(
            "No ledger loaded yet",
            "Upload an .xlsx or .csv journal ledger from the sidebar, or press "
            "Load Demo Data for the 606-entry Karachi synthetic audit.",
            icon="AG",
        )
        ui.render_schema_reference(REQUIRED_COLUMNS, (GROUND_TRUTH_COLUMN,))
        _render_how_it_works()
    else:
        missing = [
            column for column in REQUIRED_COLUMNS if column not in raw_frame.columns
        ]
        if missing:
            _render_mapping(raw_frame)
        else:
            if st.session_state.audit_frame is None:
                ui.glass_card(
                    f"Loaded {len(raw_frame):,} entries",
                    f"<p><strong>{html.escape(str(st.session_state.raw_name))}</strong></p>"
                    "<p>Press <strong>Run Audit</strong> in the sidebar to score the ledger.</p>",
                    icon="CSV",
                )

    for error in st.session_state.audit_errors:
        st.error(error)
    for warning in st.session_state.audit_warnings:
        st.warning(warning)

    overview_tab, flagged_tab, insights_tab, calendar_tab, export_tab, guide_tab = (
        st.tabs(
            [
                "Overview",
                "Flagged Entries",
                "AI Insights",
                "Calendar",
                "Export & Accuracy",
                "Guide",
            ]
        )
    )
    with overview_tab:
        _render_overview(st.session_state.audit_frame, st.session_state.summary)
    with flagged_tab:
        _render_flagged(st.session_state.audit_frame)
    with insights_tab:
        _render_insights(st.session_state.audit_frame, st.session_state.summary)
    with calendar_tab:
        _render_calendar(st.session_state.audit_frame)
    with export_tab:
        _render_export(st.session_state.audit_frame, st.session_state.summary)
    with guide_tab:
        _render_guide()

    ui.render_footer()


if __name__ == "__main__":
    main()
