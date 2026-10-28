# AuditGuard

**AI-assisted audit red-flag detection for a general ledger, built for Karachi, Pakistan.**

AuditGuard is a Streamlit dashboard for a university FinTech Expo. An auditor
uploads a journal-entry workbook (`.xlsx`, `.xlsm`, or `.csv`), and AuditGuard
validates the data, runs six explainable audit tests, ranks every entry by
risk, explains why it was flagged, and exports a formatted Excel audit package.
When the workbook includes a `GroundTruth` column, the app also reports
precision, recall, F1, and a confusion matrix against the labelled test data.

Every amount is shown in Pakistani rupees (`Rs.`), every date as `MM/DD/YYYY`,
and every audit timestamp is generated in **Asia/Karachi**. The detection core
is rule-based and statistical, not a black box: every flag is traceable to a
field in the ledger and a documented threshold.

---

## Feature summary

- **Schema validation** for the fixed eight-column ledger, plus friendly
  warnings for partially bad dates or amounts.
- **Six audit rules**: duplicate payments, round amounts, weekend/holiday
  postings, just-below-limit amounts, self-approval, and Benford's Law.
- **Karachi localization**: Saturday + Sunday weekends (or Sunday only, or any
  custom weekday pattern), seven fixed Pakistan public holidays plus editable
  Islamic dates, July–June or a custom-start financial year, and Pakistan
  Standard Time timestamps.
- **Rupee formatting**: `Rs. 12,50,000` (lakh/crore) or `Rs. 1,250,000`
  (international), with compact `Rs. 12.5 Lac` / `Rs. 1.2 Cr` labels.
- **Transparent risk scoring** (0–100) with Low / Medium / High / Critical
  bands, per-entry reasons, and a portfolio-level risk score.
- **Six dashboard tabs**: Overview, Flagged Entries, AI Insights, Calendar,
  Export & Accuracy, and Guide.
- **Calendar heatmap** with financial-year navigation, weekend shading,
  holiday tooltips, year view, and insight cards.
- **Plain-English and Roman Urdu explanations** for every flagged entry. An
  optional Groq LLM layer receives only structured facts, rotates across
  multiple API keys, and falls back to templates on any failure.
- **Five-sheet Excel report** with live formulas, native charts, filters,
  frozen headers, risk fills, explanations, and methodology (including ISA 240).
- **Accuracy reporting** against labelled data: overall and per-rule TP/FP/FN,
  precision, recall, F1, missed anomalies, and false alarms.
- **No database.** Data and Groq keys stay in the Streamlit session; nothing is
  persisted server-side.

---

## Quick start (Windows)

Python 3.10 or newer is required. A virtual environment already lives at
`D:\AI Audit Red-Flag Dashboard\.venv`; reuse it or create a new one.

### Command Prompt

```bat
cd "D:\AI Audit Red-Flag Dashboard\auditguard"
..\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python data_generator.py
python -m streamlit run app.py
```

### PowerShell

```powershell
cd "D:\AI Audit Red-Flag Dashboard\auditguard"
..\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python data_generator.py
python -m streamlit run app.py
```

### Git Bash

```bash
cd "/d/AI Audit Red-Flag Dashboard/auditguard"
source ../.venv/Scripts/activate
python -m pip install -r requirements.txt
python data_generator.py
python -m streamlit run app.py
```

Streamlit prints a local URL, normally `http://localhost:8501`. The dark glass
theme is applied automatically from `.streamlit/config.toml` plus the custom
stylesheet in `ui.py`; no extra flags are needed.

`python data_generator.py` writes two workbooks into `data/`:

- `data/AuditGuard_Karachi_Dataset.xlsx` — 606 entries with `GroundTruth`, a
  `Pakistan_Holidays_2025` sheet, and an `About` sheet.
- `data/AuditGuard_Karachi_Dataset_blind.xlsx` — the same ledger with a
  `Ledger` sheet only, for a realistic blind upload.

The app reads the labelled workbook for **Load Demo Data**. If the file is
missing, the app regenerates it automatically.

---

## Project structure

```text
auditguard/
├── app.py                  # Streamlit entry point and six dashboard tabs
├── detection.py            # Validation, six rules, scoring, summary, Benford
├── data_generator.py       # Synthetic Karachi ledger + labelled anomaly injection
├── ai_explainer.py         # Rule-based explanations and executive summaries
├── groq_client.py          # Optional Groq wording with key rotation and grounding
├── calendar_view.py        # Calendar heatmaps, day lists, and insight cards
├── export.py               # Five-sheet Excel report + accuracy metrics
├── utils.py                # PKR, MM/DD/YYYY, Karachi time, and FY helpers
├── ui.py                   # Glassmorphism CSS and reusable UI helpers
├── requirements.txt
├── README.md
├── FEATURES.md             # Plain-English feature guide
├── DEMO_SCRIPT.md
├── .streamlit/
│   └── config.toml         # Dark base theme
├── data/
│   ├── AuditGuard_Karachi_Dataset.xlsx
│   └── AuditGuard_Karachi_Dataset_blind.xlsx
└── tests/
    ├── conftest.py
    ├── test_utils.py
    ├── test_data_generator.py
    ├── test_detection.py
    ├── test_ai_explainer.py
    ├── test_groq_client.py
    ├── test_export.py
    ├── test_calendar_view.py
    ├── test_ui.py
    └── test_app_smoke.py
```

---

## Input schema

Column names must match exactly. Order does not matter, and headers are
trimmed of surrounding whitespace.

| Column | Expected content |
| --- | --- |
| `EntryID` | Unique journal-entry identifier |
| `Date` | Posting date (Excel date or text in the selected input format) |
| `Account` | General-ledger account |
| `Vendor` | Vendor / payee name |
| `Description` | Journal-entry narrative; may contain an invoice reference |
| `Amount` | Positive numeric amount in Pakistani rupees |
| `PostedBy` | Employee who posted the entry |
| `ApprovedBy` | Employee who approved the entry |
| `GroundTruth` | **Optional.** One of the labels below, or `Clean` |

`GroundTruth` labels used by the generator and accuracy engine:

```text
Duplicate
RoundAmount
Weekend
JustBelowLimit
SelfApproval
BenfordManip
MultiRule
Clean
```

If required columns are missing, the app opens a column-mapping panel. It
suggests matches from common aliases (for example `ID`, `Posting Date`,
`Supplier`, `Value`, `Preparer`, `Approver`), blocks duplicate mappings, and
runs the audit once every required field is mapped.

CSV files may use commas, semicolons, or tabs; the reader sniffs the delimiter
and retries with Latin-1 if UTF-8 decoding fails. Excel workbooks are read from
the `Ledger` sheet when present, otherwise from the first sheet.

### Input date format

The sidebar offers **Auto-detect**, **MM/DD/YYYY** (default), and
**DD/MM/YYYY**. Text dates are parsed with the chosen format; when a value is
ambiguous in auto-detect mode, the app shows a warning with the row numbers
instead of guessing silently. Unreadable dates become warnings, not crashes.

---

## Karachi localization

| Setting | Default | Options |
| --- | --- | --- |
| Weekend days | Saturday + Sunday | Saturday + Sunday, Sunday only, or Custom weekdays |
| Pakistan public holidays | On | Kashmir Day (02/05), Pakistan Day (03/23), Labour Day (05/01), Youm-e-Takbeer (05/28), Independence Day (08/14), Iqbal Day (11/09), Quaid-e-Azam Day (12/25) |
| Extra holidays | Empty | Editable list accepting `MM/DD/YYYY` or `YYYY-MM-DD`; Islamic dates are suggestions because they depend on moon sighting. **Prefill** copies the demo workbook's `Pakistan_Holidays_2025` sheet |
| Financial year | July–June (Pakistan) | July–June, January–December, or Custom start month |
| AI explanations | 10 entries | Any count from 1 up to every flagged entry; the slider range grows with the audit |
| Input date format | MM/DD/YYYY | Auto-detect, MM/DD/YYYY, DD/MM/YYYY |
| Number format | Lakh/Crore on | `Rs. 12,50,000` vs `Rs. 1,250,000` |
| Report timestamp | Asia/Karachi | `MM/DD/YYYY HH:MM PKT` |

The Excel report header reads **“Prepared in Karachi, Pakistan”**, and the
Methodology sheet cites **ISA 240** (the auditor's responsibilities relating to
fraud).

---

## Detection rules and weights

| Rule | Logic | Default weight |
| --- | --- | --- |
| **Duplicate** | Same vendor and amount within 7 days. **Both** postings are flagged, each records the other's `EntryID`, and a shared invoice reference such as `INV-2025-0142` strengthens the reason. | 30 |
| **Round amount** | Exact multiple of `Rs. 1,000` and at least `Rs. 10,000`. | 15 |
| **Weekend/holiday posting** | A selected weekend day or a Pakistan public holiday. | 10 |
| **Just below limit** | Amount from 95% to 99.99% of the approval limit (default `Rs. 500,000`). | 25 |
| **Self-approval** | `PostedBy` equals `ApprovedBy` after trimming and case-folding. | 35 |
| **Benford deviation** | Vendors with 15 or more entries are tested with a first-digit chi-square against Benford's Law. If `p < 0.01`, every entry of that vendor is flagged. | 20 |

The approval limit, round threshold, and all six weights can be changed under
**Advanced settings** in the sidebar; re-run the audit to apply them.

### Risk scoring

- Entry risk score = sum of active rule weights, capped at **100**.
- Levels: **Low** 0–19, **Medium** 20–39, **High** 40–69, **Critical** 70+.
- Overall portfolio risk = `0.7 × average risk of flagged entries + 3 × flagged percentage`,
  capped at 100.
- `Amount at risk` is the absolute amount of every entry with at least one flag.

### Demo data contract

The generated ledger contains **606 entries** for 2025 and **57 flagged**
entries:

| Label | Rows | Notes |
| --- | --- | --- |
| `Clean` | 549 | Weekday, non-holiday, non-round, no self-approval, no vendor+amount repeat within 7 days |
| `Duplicate` | 12 | 6 pairs; both rows in each pair labelled |
| `RoundAmount` | 5 | `Rs. 25,000`, `50,000`, `75,000`, `1,20,000`, `2,00,000` |
| `Weekend` | 5 | Saturday postings, never on a fixed holiday |
| `JustBelowLimit` | 6 | 95%–99.99% of `Rs. 500,000` |
| `SelfApproval` | 5 | Poster = approver |
| `BenfordManip` | 18 | Every `Madina Traders` row, fabricated leading digits 5–9 |
| `MultiRule` | 6 | 2 Critical and 4 High overlapping-rule rows |

`Pearl Property Rentals` has 12 fixed monthly rent entries. Its amounts are not
part of the Benford test, so rent does not distort the vendor-level screen.

The six `MultiRule` rows deliberately combine rules:

- 2 × Self-Approval + Weekend + Just Below Limit → **Critical** (70)
- 2 × Self-Approval + Just Below Limit → **High** (60)
- 2 × Self-Approval + Round + Weekend → **High** (60)

Accuracy treats a `MultiRule` row as correctly detected when **at least two**
flags fire. Per-rule metrics stay one-vs-rest for the six single-rule labels.

---

## Dashboard

### Sidebar

- Upload `.xlsx`, `.xlsm`, or `.csv`.
- **Load Demo Data** for the 606-entry labelled ledger.
- Approval limit, weekend days, Pakistan holidays, extra holiday dates,
  financial year, input date format, and number format.
- **Run Audit**.
- **Use LLM explanations (Groq)** toggle (off by default) and the **Groq API
  keys** expander: add one or more keys, test, remove, or clear them.
- **Advanced settings**: round threshold and six weights, with a reset button.
- About panel and a downloadable labelled sample workbook.

### Tabs

1. **Overview** — four KPI cards, rule-hit bar chart, risk mix donut, flagged
   timeline, Benford expected-vs-actual chart with p-value, top vendor
   exposure, and a short methodology panel.
2. **Flagged Entries** — filters for risk level, flag type, vendor, minimum
   risk score, date range, and description search. The table is risk-sorted and
   colored; selecting an entry shows every field, the numeric reasons, the
   combined explanation, recommended procedures, and the related duplicate
   posting where applicable.
3. **AI Insights** — executive summary, top-N entry cards, a select-any-entry
   explainer, English/Roman Urdu toggle, and the optional Groq explanation
   source label.
4. **Calendar** — financial-year and month selectors, month heatmap with
   weekend shading, holiday tooltips, Critical-day outlines, a GitHub-style
   year view, insight cards, and a day inspector listing entries with badges
   and explanations.
5. **Export & Accuracy** — Excel audit pack, flagged-entry CSV, accuracy KPI
   cards, confusion-matrix heatmap, per-type precision/recall table, and
   missed/false-alarm review tables.
6. **Guide** — every feature explained in plain English with examples.

---

## Groq explanations and privacy

By default, explanations are deterministic templates built only from the
entry's own fields: Entry ID, amount in rupees, date in `MM/DD/YYYY`, vendor,
poster, approver, duplicate source, and Benford p-value. Each explanation names
every triggered rule.

Optional Groq mode sends **only structured facts** (flags, amounts in rupees,
dates in `MM/DD/YYYY`, vendor, approver, risk score, rule reasons). The system
prompt is:

> Use only these facts; do not invent amounts, names or dates; 3 sentences max;
> clear simple English.

Additional safeguards:

- **Keys live only in `st.session_state`.** They are never written to disk,
  logs, Excel, CSV, or error messages. Keys can also come from the optional
  `GROQ_API_KEYS` environment variable or `.env` file at startup.
- **Round-robin key rotation.** On `429`, `401`, `403`, timeout, or network
  failure, the client moves to the next key, honours `Retry-After` for short
  waits, and only then gives up.
- **Numeric grounding.** If the model returns a number that is absent from the
  row facts, the output is discarded and the template is used.
- **20-second timeout**, `temperature=0.2`, `max_tokens=220`.
- **Model discovery** via `GET /models`, excluding whisper, TTS, guard, and
  embedding models. Default: `llama-3.3-70b-versatile`, with a four-model
  fallback list.
- **Per-entry cache** keyed by the row facts, model, and language.

If every key fails, the app shows a short notice and uses templates. Flags,
scores, and accuracy never depend on the LLM.

---

## Excel audit report

**Download Excel report** produces one workbook with five sheets:

1. **Summary** — title, generated date, KPI cells in rupees, live `COUNTA`,
   `IFERROR`, `SUMIF`, and `COUNTIF` formulas, a native bar chart of rule hits,
   and a native pie chart of risk levels.
2. **Flagged Entries** — one row per flagged entry, dark header, freeze panes,
   auto-filter, wrapped descriptions, `mm/dd/yyyy` dates, `"Rs. "#,##0.00`
   amounts, and risk-level fills.
3. **Flag Breakdown** — counts and amounts by rule, plus vendor-level exposure
   and the most common flag per vendor.
4. **AI Explanations** — the explanation used in the app for every flagged
   entry.
5. **Methodology** — each rule's logic, weight, risk-level bands, scoring
   formula, amount-at-risk definition, ISA 240 reference, and Karachi report
   context.

Formula-injection protection: text cells that begin with `=`, `+`, `-`, `@`,
tab, or newline are forced to plain strings before the workbook is saved.

The CSV download contains the flagged rows only, encoded as UTF-8 with BOM so
Excel opens it cleanly, with `Amount (Rs.)` and `MM/DD/YYYY` values.

---

## Accuracy on the demo data

| Metric | Value |
| --- | --- |
| Entries tested | 606 |
| Labelled anomalies | 57 |
| Flagged entries | 57 |
| True positives | 57 |
| False positives | 0 |
| False negatives | 0 |
| Precision | 100% |
| Recall | 100% |
| F1 | 100% |

Per-rule precision and recall are 100% for duplicate, round amount, weekend,
just-below-limit, self-approval, and Benford. The per-type table is shown in
the app and in the exported workbook, including support, flagged count, TP, FP,
and FN for each rule.

Overall accuracy treats any flag as a predicted anomaly and any non-`Clean`
label as a real anomaly; a `MultiRule` row counts as detected only when at
least two flags fire. Per-type metrics use one-vs-rest over the six single-rule
labels. The vendor-level false-alarm card remains available for future labelled
data where a whole vendor is not manipulated.

---

## Tests

Run from the `auditguard` directory:

```text
python -m pytest -v
```

The suite contains **168 tests** across ten modules:

- `test_utils.py` — PKR groups (lakh/crore and international), short labels,
  `MM/DD/YYYY`, Karachi timestamps, holidays, preset and custom FY helpers,
  custom weekend weekdays, Excel formats, masking.
- `test_data_generator.py` — schema, exact counts, 25 vendors / 10 accounts /
  6 employees, clean-row invariants, rent series, Benford digits, duplicate
  pairs and invoice reference, MultiRule rows, workbook sheets.
- `test_detection.py` — validation, every rule and boundary, weekend presets,
  holidays in both date formats, duplicate invoice reasons, custom limits,
  risk levels, summaries, Benford table, zero flags.
- `test_ai_explainer.py` — every rule explained in English and Roman Urdu,
  multi-flag wording, no invented amounts, executive summaries, determinism.
- `test_groq_client.py` — key normalization/masking, structured facts,
  grounding, payload shape, 429 rotation, all-fail fallback, model filtering,
  invented-number rejection, and no key leakage in logs or exceptions.
- `test_export.py` — five sheets, formulas and dynamic column letters, charts,
  risk fills, empty report, formula-injection neutralization, accuracy.
- `test_calendar_view.py` — FY/month options, month cells and heatmaps, weekend
  shading, Critical outlines, year grid, insights, day lists, any date range.
- `test_ui.py` — glass tokens, 770px responsive rules, KPI-row wrapping,
  wrapping tab bar, orbs, badges, KPI/card escaping, schema chips, Plotly
  theming.
- `test_app_smoke.py` — AppTest runs the landing page, demo audit, every
  filter, custom weekend and financial-year settings, the dynamic AI
  explanation range, zero-flag state and empty charts, CSV/Excel/Ledger
  reading, holiday parsing, Groq key session behavior, and rupee/date output.
- `conftest.py` — shared demo ledger, holidays, and checked-frame fixtures.

Expected result: `168 passed`.

---

## Performance

`run_all_checks` is vectorized per rule except duplicate grouping and the
vendor-level chi-square test. A generated 20,000-row ledger audits in roughly
three seconds on the development laptop, including all six rules. The UI caps
the displayed table height and filters the already-scored frame.

---

## Known limitations

- **Benford false alarms** are inherent to a vendor-level screen; a real audit
  uses it to direct sampling, not to conclude fraud.
- **Duplicate matching** uses vendor + amount + a seven-day window because the
  fixed schema has no invoice column. Invoice references in descriptions are
  supporting evidence, not a matching key.
- **Round-amount and threshold rules** are deterministic and will flag
  legitimate round payments; the review workflow and reasons make that
  transparent.
- **The Groq layer is optional** and wording-only. It requires network access
  and at least one valid key.
- **Islamic holiday dates** depend on moon sighting; the app supplies
  suggestions that the user can edit.
- **Uploaded files and keys are not persisted.** Refreshing the browser or
  restarting the server clears the session.
- **Single-file scope.** Consolidation across periods or entities is future
  work.
- **No authentication or audit trail** yet; production deployment would need
  SSO, role-based access, immutable review logs, and ERP connectors.

## Future work

- Invoice-number and PO matching as first-class duplicate keys.
- Configurable rule enable/disable per engagement.
- Saved workpapers, reviewer sign-off, and an immutable audit trail.
- Multi-sheet/multi-entity consolidation and period-over-period analytics.
- PDF export and email-ready executive summaries.

---

## Documentation

- [FEATURES.md](FEATURES.md) — every feature in simple English, with examples.
- [DEMO_SCRIPT.md](DEMO_SCRIPT.md) — a timed 5–6 minute expo presentation,
  fallback plan, and judge Q&A.
