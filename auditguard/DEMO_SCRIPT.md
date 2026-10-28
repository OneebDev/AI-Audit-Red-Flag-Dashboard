# AuditGuard — FinTech Expo Demo Script

**Target length:** 5–6 minutes. **Presenter:** one speaker, one laptop.
**Audience:** judges, finance faculty, auditors, students.

AuditGuard is presented as a Karachi-built audit dashboard: rupees, `MM/DD/YYYY`
dates, Pakistan holidays, a July–June financial year, and an optional Groq
explanation layer that never sees the full ledger.

---

## Before you present (5-minute checklist)

1. Start the app:
   ```text
   cd "D:\AI Audit Red-Flag Dashboard\auditguard"
   ..\.venv\Scripts\activate
   python -m streamlit run app.py
   ```
2. Open `http://localhost:8501` in Chrome at 100% zoom.
3. Click **Load Demo Data** once to warm the cache, then reload the page so the
   demo starts from a clean landing state.
4. Keep `data\AuditGuard_Karachi_Dataset_blind.xlsx` nearby for the upload step.
5. Keep `data\AuditGuard_Karachi_Dataset.xlsx` available for the accuracy step,
   because it contains `GroundTruth`.
6. Have a screenshot of the **Flagged Entries** tab, the **Calendar** tab, and a
   downloaded Excel report ready in case the projector or Wi-Fi fails. The app
   runs locally.
7. Close other browser tabs and notifications.
8. Leave the Groq toggle **off** unless the key is tested and the venue Wi-Fi is
   reliable.

---

## 0:00–0:45 | The problem

> "Every month, finance teams receive thousands of journal entries. Auditors
> do not struggle to find data; they struggle to find the handful of entries
> worth investigating. Sampling catches some errors, but it is slow,
> inconsistent, and hard to explain to a client.
>
> AuditGuard turns a general ledger into a ranked, explainable review list in
> seconds. It applies six audit tests, shows the evidence behind every flag,
> plots risky days on a calendar, exports a workpaper-ready Excel pack, and
> proves its own precision and recall when labelled data is available.
>
> It is built for Pakistan: rupees, `MM/DD/YYYY` dates, Karachi time, and the
> Pakistani weekend and public holidays."

Show the landing page: schema chips, rupee labels, and empty states.

---

## 0:45–1:30 | Upload and run

- Point to the sidebar schema list: `EntryID`, `Date`, `Account`, `Vendor`,
  `Description`, `Amount`, `PostedBy`, `ApprovedBy`.
- Upload `AuditGuard_Karachi_Dataset_blind.xlsx` (no `GroundTruth`).
- Say: "The file is validated in the session. Amounts are in rupees, dates are
  read as `MM/DD/YYYY`, and bad rows are reported rather than silently dropped.
  There is no database and no external upload."
- Press **Run Audit**.
- Expected result: toast reports **57 flagged of 606 entries**; the hero status
  becomes **Audit complete**.

If upload misbehaves, click **Load Demo Data** and continue.

---

## 1:30–2:15 | Overview

- Four KPI cards: total entries, flagged entries and percentage, amount at risk
  in rupees, overall risk score/level.
- Rule-hit bar chart: duplicate, round, weekend, just-below-limit,
  self-approval, Benford.
- Risk donut and flagged timeline: red markers cluster on the anomaly dates.
- Benford chart: observed first digits versus the expected distribution, with a
  p-value callout.
- Say: "Every score is arithmetic, not a black box. The weights are visible and
  editable under Advanced settings, and the amounts are in lakh/crore format so
  they read naturally in Pakistan."

Expected result: **57 flagged**, **Rs. 77,29,596.13 at risk**, overall risk
**47.3 / 100 (High)**. Benford produces the most hits (18), followed by
duplicates (12) and self-approvals (11).

---

## 2:15–3:05 | Investigate a flagged entry

- Open **Flagged Entries**.
- Point out the filters: risk level, flag type, vendor, minimum score, date
  range, description search.
- Select **Self-Approval** in **Flag type**; the table narrows to 11 entries.
- Pick a top entry. Read the detail card:
  - every field with `MM/DD/YYYY` dates and `Rs.` amounts,
  - the numeric reason ("Posted and approved by the same person…"),
  - the plain-English explanation,
  - recommended audit procedures.
- Switch **Flag type** to **Duplicate**, open one entry, and show the
  **Related duplicate entry** card with the earlier `EntryID`. If the shared
  description includes `INV-2025-0142`, point out that the invoice reference is
  quoted as extra evidence.
- Say: "The auditor gets the control that failed, the amount, the people, and
  the next procedure — not just a red dot."

Expected result: **11 of 57** for Self-Approval; duplicate detail names both
postings, the day gap, and any shared invoice reference.

---

## 3:05–3:35 | Calendar

- Open **Calendar**.
- The financial year defaults to **2025–26 (Jul–Jun)** and the month selector
  opens on December 2025.
- Show the month heatmap: weekends shaded, holiday tooltips on hover, Critical
  days with a red outline.
- Point at 11/01/2025: ENT-0601 is a Critical MultiRule entry.
- Scroll to the year heatmap and the four insight cards.
- Pick a date in **Inspect a day** and show the entry badges and explanations.
- Say: "Auditors think in months and cut-offs. The calendar turns the same flags
  into a visual review plan and highlights clustering near month-end and
  weekends."

---

## 3:35–4:10 | AI Insights and Groq

- Open **AI Insights**.
- Read the executive summary: 606 entries, 57 flagged, rupee exposure, dominant
  pattern, riskiest vendor, and the top entry to start with.
- Show the top-N cards and the **Explain any flagged entry** selector.
- Say: "The default explanation is a deterministic template built only from the
  row's own fields. The optional Groq switch only rewrites the wording; it never
  changes a flag or sends the ledger. Keys stay in this session only, are rotated
  automatically if one fails, and any invented number is rejected. On any error
  we fall back to the template."

Do **not** enable Groq during the live demo unless the key is already tested and
the venue Wi-Fi is reliable.

---

## 4:10–4:50 | Export and accuracy

- Open **Export & Accuracy**.
- Download the Excel report and open it. Show:
  - **Summary** with live formulas and native charts,
  - **Flagged Entries** with filters, risk fills, `mm/dd/yyyy` dates, and
    `Rs.` amounts,
  - **AI Explanations** and **Methodology** (including ISA 240 and the Karachi
    report header).
- Say: "This is not a raw CSV dump; it is a workpaper-ready pack with the rule
  logic documented inside the file."
- Scroll to **Detection accuracy**. Show precision, recall, F1, the confusion
  matrix, and the per-type table.
- Say: "On the labelled demo: 57 of 57 anomalies caught, no false alarms, 100%
  precision and 100% recall. MultiRule rows count as detected only when at least
  two flags fire, so the perfect score is earned, not assumed."

Expected result: TP 57, FP 0, FN 0, precision 100%, recall 100%, F1 100%.

---

## 4:50–5:25 | Market and business model

Use illustrative numbers and label them as assumptions.

> "Mid-market finance teams and audit firms still rely on spreadsheet sampling.
> A typical audit-analytics seat is priced in the low millions of rupees per
> year; our wedge is a lightweight, explainable review layer that sits on top of
> the exports teams already have.
>
> Illustrative model: **Rs. 2.4 million per year per audit team**, 50 teams in
> year two gives **Rs. 120 million ARR**. Gross margin is high because
> processing is local and the core engine is deterministic. Land with a free
> single-ledger audit, expand to multi-entity and reviewer workflow, then
> integrate with ERP exports.
>
> The moat is not a proprietary model; it is the combination of audit-specific
> rules, Karachi localization, explainability, accuracy reporting, and a
> workpaper-ready export that a finance team can adopt without a data-science
> hire."

Keep this section conversational; judges care more about clarity than precise
market-size figures.

---

## 5:25–5:40 | Close

> "AuditGuard combines accounting controls, statistics, explainable rules,
> Excel reporting, and a usable dashboard, localized for Pakistan. It is
> decision support, not an audit opinion: the auditor stays in control, every
> flag is explainable, and the app reports its own mistakes. Thank you —
> questions?"

---

## Fallback plan

| Problem | Recovery |
| --- | --- |
| Upload fails or file is missing | Click **Load Demo Data**; continue from 1:30. |
| App is slow to start | Keep a screen recording of the 45-second flow; narrate over it. |
| Network is down | Everything except the optional Groq layer runs locally. Do not enable Groq. |
| Excel download blocked | Show the pre-downloaded report from the desktop. |
| A filter shows zero rows | Reset **Risk level** to all four levels and **Minimum risk score** to 0. |
| Dates look swapped | Switch **Input date format** between MM/DD/YYYY and DD/MM/YYYY. |
| Calendar opens on the wrong month | Change the financial year or month selector; it is independent of the ledger filters. |
| Projector crops the layout | Zoom the browser to 80%; columns stack below roughly 770px. |

---

## Judge Q&A (12 likely questions)

**1. Is this machine learning?**
No. The detection is deterministic rules plus a chi-square Benford test. That is
a deliberate choice: auditors need to explain and defend every finding. The
optional Groq layer only rewrites explanations and never changes a flag.

**2. What about false positives?**
The accuracy tab reports them directly. On the demo, the labels are complete, so
there are zero false alarms; the vendor-level false-alarm card remains visible
for future labelled data where a whole vendor is not manipulated. Review and
risk ranking are designed for triage, not automatic accusation.

**3. How is this different from Excel?**
Excel can hold the data, but it cannot apply six consistent tests, score and
rank entries, generate grounded explanations, enforce formula-injection safety,
and report precision/recall. AuditGuard also exports back to Excel, so it
augments the auditor's existing tool rather than replacing it.

**4. How do you make money?**
Illustratively: a per-team annual subscription (around Rs. 2.4 million), a free
single-ledger tier for land-and-expand, and later add-ons for multi-entity
consolidation, reviewer workflow, and ERP connectors. The demo does not claim
validated pricing.

**5. Can the LLM hallucinate amounts or names?**
Groq receives only structured facts and is instructed to use only those facts
in at most three sentences. If the reply contains a number that is not in the
row facts, it is discarded and the template is used. Flags, scores, and accuracy
never depend on the LLM.

**6. Where does my data go?**
Nowhere by default. Processing is local to the Streamlit session; there is no
database and no persistence. Uploads disappear when the session ends. Only if a
user explicitly enables Groq and supplies a key are structured facts sent to
Groq; keys live only in the session and are never stored or logged.

**7. Why Benford's Law?**
It is a population-level screen for fabricated or manipulated amounts. We apply
it per vendor with a minimum of 15 entries and p < 0.01, then flag the whole
vendor. It is a pointer for sampling, not proof of fraud. Rent from Pearl
Property Rentals is excluded from digit testing.

**8. Why these weights?**
They reflect control severity: self-approval breaks segregation of duties (35),
followed by duplicates (30), threshold structuring (25), Benford (20), round
amounts (15), and weekend postings (10). Every weight is editable, and the score
is a capped sum, so the math is auditable. The six MultiRule demo rows combine
two or three rules and land in High or Critical.

**9. What happens with 20,000 rows?**
The audit completes in roughly three seconds on a normal laptop. The app was
tested at that size; the table is capped and filtered client-side. Larger
deployments would move scoring to a background job and a database.

**10. How do you handle missing or messy columns?**
The app blocks only when the ledger cannot be used: missing required columns,
all dates unreadable, all amounts non-numeric, negative amounts, or fewer than
two rows. Partial issues become warnings, and the affected rules skip only the
rows they cannot evaluate. A column-mapping panel handles common header aliases.

**11. What is the biggest limitation?**
Duplicate matching uses vendor + amount + a seven-day window because the fixed
schema has no invoice field. Invoice references in descriptions are supporting
evidence, not a key. Benford also produces vendor-level false alarms by design.

**12. What is next?**
Invoice and PO matching as first-class keys, configurable rule sets per
engagement, reviewer sign-off and an immutable audit trail, multi-sheet or
multi-entity consolidation, PDF export, and ERP connectors. Production also
needs SSO, role-based access, and monitoring.

---

## One-sentence takeaway

> "AuditGuard gives auditors a fast, explainable, and measurable first pass over
> a general ledger — in rupees, on Karachi time, and with its work shown."
