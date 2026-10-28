# AuditGuard — Feature Guide

This guide explains every feature in simple English, with a short example for
each one. The same explanations are available inside the app on the **Guide**
tab.

---

## 1. What AuditGuard does

AuditGuard takes a journal ledger and turns it into a ranked review list.

1. Read the ledger and check the eight required columns.
2. Run six audit tests on every row.
3. Give each row a risk score from 0 to 100.
4. Show why each flagged row was flagged.
5. Plot risky days on a calendar.
6. Export an Excel audit pack and, when labels exist, measure accuracy.

Everything happens inside the browser session. There is no database, and
uploaded files are gone when the session ends.

**Example:** a 606-row 2025 ledger is scored in under a second and produces 57
flagged entries, Rs. 77,29,596.13 of amount at risk, and an overall High risk
score of 47.3.

---

## 2. Loading data

### Upload a file

Use the sidebar uploader for `.xlsx`, `.xlsm`, or `.csv`.

- Required columns: `EntryID`, `Date`, `Account`, `Vendor`, `Description`,
  `Amount`, `PostedBy`, `ApprovedBy`.
- Optional: `GroundTruth` — one of `Duplicate`, `RoundAmount`, `Weekend`,
  `JustBelowLimit`, `SelfApproval`, `BenfordManip`, `MultiRule`, or `Clean`.
- Excel workbooks use the `Ledger` sheet when it exists; otherwise the first
  sheet.
- CSV files may use commas, semicolons, or tabs.

**Example:** the blind demo workbook has only a `Ledger` sheet. Upload it and
press **Run Audit**; the app does not need `GroundTruth` to score the ledger.

### Column mapping

If a required column is missing, AuditGuard opens a mapping panel. Pick a
source column for each missing field, then press **Apply mapping and run
audit**. Duplicate selections are blocked.

**Example:** a file with `Supplier` instead of `Vendor` can be mapped in one
click; the app suggests `Supplier` automatically.

### Friendly problems

- Missing columns → mapping panel.
- Unreadable dates or amounts → row-level warnings, not a crash.
- Negative amounts, no usable dates, or fewer than two rows → a clear error
  explains what to fix.

---

## 3. Money and number formats

All amounts are Pakistani rupees.

| Sidebar setting | Example output |
| --- | --- |
| **Lakh/Crore number format** on (default) | `Rs. 12,50,000` |
| **Lakh/Crore number format** off | `Rs. 1,250,000` |
| Compact KPI label, lakh/crore on | `Rs. 12.5 Lac` |
| Compact KPI label, lakh/crore off | `Rs. 1.2M` |

Whole amounts have no decimals; fractional amounts keep two decimals. The same
formatter is used in the dashboard, explanations, CSV, and Excel, so the number
never changes shape between views.

**Example:** an amount of `1_250_000.50` appears as `Rs. 12,50,000.50` in the
table and as `Rs. 12.5 Lac` in a compact KPI.

---

## 4. Dates and Karachi time

Every displayed date is `MM/DD/YYYY`. Reports and audit timestamps use
**Asia/Karachi** and show `PKT`.

- **Input date format:** Auto-detect, MM/DD/YYYY (default), or DD/MM/YYYY.
- When auto-detect sees a date that could be either day-first or month-first,
  it warns and lists affected rows instead of silently guessing.
- The holiday box accepts `MM/DD/YYYY` and `YYYY-MM-DD`.
- Calendar day inspectors, Plotly hover text, CSV, and Excel all use the same
  format.

**Example:** `03/04/2025` is 4 March 2025 under MM/DD/YYYY and 3 April 2025
under DD/MM/YYYY. Choose the format that matches the source file.

---

## 5. Karachi and Pakistan settings

| Setting | Default | What it changes |
| --- | --- | --- |
| Weekend days | Saturday + Sunday | Which weekdays the weekend rule flags and which days the calendar shades. Choose Sunday only, or **Custom** and tick any weekdays |
| Pakistan public holidays | On | Adds the seven fixed holidays to the weekend rule and the calendar |
| Extra holidays | Empty | Adds Islamic or company dates; moon-sighting dates are suggestions only. **Prefill** copies the demo workbook's `Pakistan_Holidays_2025` sheet |
| Financial year | July–June (Pakistan) | Calendar year selection and monthly summaries. Choose January–December, or **Custom start month** for any twelve-month cycle |
| AI explanations | 10 entries | Slider range grows with the audit, from 1 up to every flagged entry |

The sidebar's **Where do these holiday dates come from?** section spells out
each source: the seven fixed dates come from AuditGuard's built-in Pakistan
calendar; the extra dates are whatever you type in the box (or the four
moon-sighting dates stored in the demo workbook).

Fixed holidays:

- 02/05 Kashmir Day
- 03/23 Pakistan Day
- 05/01 Labour Day
- 05/28 Youm-e-Takbeer
- 08/14 Independence Day
- 11/09 Iqbal Day
- 12/25 Quaid-e-Azam Day

**Example:** a posting on Saturday 03/29/2025 is flagged under the default
weekend. Switching to **Sunday only** stops that flag, but a posting on
08/14/2025 stays flagged because it is Independence Day. Pick **Custom**
weekend days to mirror a six-day week, a Friday–Saturday weekend, or any
other office calendar.

---

## 6. The six audit tests

### Duplicate

Same vendor and amount within seven days.

- **Both** postings are flagged.
- Each row records the other row's `EntryID` and the day gap.
- If both descriptions share an invoice reference such as `INV-2025-0142`, the
  reason mentions it as stronger evidence.
- The seven-day rule and the ledger schema do not change.

**Example:** `Indus Air Services` at `Rs. 3,918.37` on 03/12/2025 and again on
03/17/2025 → both rows flagged as Duplicate.

### Round amount

Exact multiples of `Rs. 1,000` at or above `Rs. 10,000`.

**Example:** `Rs. 75,000` is flagged; `Rs. 75,250` is not.

### Weekend or holiday

A posting on a configured weekend day or a Pakistan public holiday.

**Example:** Saturday 11/01/2025 → Weekend Posting. Friday 10/31/2025 → no
weekend flag.

### Just below limit

An amount from 95% to 99.99% of the approval limit.

**Example:** with the default `Rs. 5,00,000` limit, `Rs. 4,87,500` (97.5%) is
flagged; `Rs. 3,00,000` is not.

### Self-approval

The same person posted and approved the entry, compared after trimming spaces
and ignoring upper/lower case.

**Example:** `PostedBy = Hamza Sheikh` and `ApprovedBy = hamza sheikh` →
Self-Approval.

### Benford deviation

Vendors with at least 15 entries are tested with a first-digit chi-square
against Benford's Law. If `p < 0.01`, every entry from that vendor is flagged
for review.

**Example:** `Madina Traders` has 18 fabricated entries whose leading digits are
5–9; the vendor-level test flags all 18.

Benford is a sampling pointer, not proof of fraud. Rent entries from
`Pearl Property Rentals` are excluded from digit testing so fixed monthly rent
does not distort the result.

---

## 7. Risk scoring

Points add up and are capped at 100.

| Rule | Points |
| --- | --- |
| Self-approval | 35 |
| Duplicate | 30 |
| Just below limit | 25 |
| Benford | 20 |
| Round amount | 15 |
| Weekend/holiday | 10 |

| Level | Score |
| --- | --- |
| Low | 0–19 |
| Medium | 20–39 |
| High | 40–69 |
| Critical | 70+ |

The portfolio score is `0.7 × average flagged score + 3 × flagged percentage`,
capped at 100. **Amount at risk** is the total absolute value of flagged
entries.

**Example:** Self-Approval + Weekend + Just Below Limit = 35 + 10 + 25 = 70 →
Critical.

The weights and the round threshold can be changed under **Advanced settings**.
Re-run the audit after changing them.

---

## 8. Overview tab

- Four KPI cards: total entries, flagged entries and percentage, amount at
  risk, and overall risk score/level.
- Rule-hit bar chart and risk-mix donut.
- Flagged timeline.
- Benford expected-vs-actual chart with the p-value.
- Top vendors by flagged exposure.
- A short methodology panel with the current thresholds.

**Example:** on the demo the Benford rule produces the most hits (18), followed
by duplicates (12) and self-approvals (11).

---

## 9. Flagged Entries tab

Filters:

- risk level,
- flag type,
- vendor,
- minimum risk score,
- date range,
- description search.

The table is sorted by risk score. Select any Entry ID to see every field,
the reasons, the full explanation, recommended audit procedures, and the
related duplicate row where applicable.

**Example:** choose **Self-Approval** → 11 of 57 entries. Add **Critical** under
risk level → 2 entries remain.

Dates in the inspector and table use `MM/DD/YYYY`; amounts use `Rs.`.

---

## 10. AI Insights tab

- Executive summary built from the audit numbers.
- Top-N entry cards with explanations and procedures.
- A selector to explain any flagged entry.
- **English / Roman Urdu** toggle.
- Optional Groq wording per entry.

By default, explanations are deterministic templates built only from the row's
own fields. Every template names each triggered rule and uses the row's real
amount, date, vendor, and people.

**Example:** "ENT-0126 shows 1 red flag: Self-Approval. Hamza Sheikh both posted
and approved the Rs. 4,34,442.46 payment. …"

---

## 11. Groq explanations (optional)

Groq is **off by default**.

1. Open **Groq API keys** in the sidebar.
2. Paste one or more keys (one per line) and press **Add key**.
3. Press **Test** beside a key to check it, **Remove** to delete one, or
   **Clear all keys**.
4. Choose a model and press **Refresh models** to reload the list.
5. Turn on **Use LLM explanations (Groq)**.

Safety rules:

- Keys live **only** in `st.session_state`. They are never written to disk,
  logs, Excel, CSV, or error messages. The UI shows masked keys such as
  `gsk_...abcd`.
- Only structured facts are sent: flags, amounts in rupees, dates in
  `MM/DD/YYYY`, vendor, poster, approver, risk score, and reasons.
- The system prompt says: *Use only these facts; do not invent amounts, names
  or dates; 3 sentences max; clear simple English.*
- If the reply contains a number that is not in the row facts, the reply is
  discarded and the template is used.
- On `429`, `401`, `403`, timeout, or network failure, the client moves to the
  next key. If every key fails, the app shows a notice and uses templates.
- Requests time out after 20 seconds; `temperature=0.2`, `max_tokens=220`.
- Replies are cached per entry, model, and language.
- Keys may also come from the optional `GROQ_API_KEYS` environment variable or
  `.env` file; they are loaded into the session and still never written
  anywhere.

**Example:** with two keys and the first one rate-limited, the first request
automatically uses the second key and the UI shows the model that produced the
text: `Explanation source: Groq (llama-3.3-70b-versatile)`.

---

## 12. Calendar tab

The Calendar tab follows the selected financial year (July–June by default).

- **Month heatmap:** each day is coloured by flagged volume; weekends are
  shaded; holidays show a starred hover tooltip; Critical days get a red
  outline.
- **Year heatmap:** a GitHub-style grid for the whole year.
- **Insight cards:** weekend/holiday flags, busiest day, the share of flags in
  the last three working days of each month versus the rest, and the top month
  by risk.
- **Day inspector:** pick a date to list its entries with risk badges and
  explanations.

**Example:** in the demo, Saturday 11/01/2025 contains ENT-0601, a Critical
MultiRule entry. Selecting that date shows its badges and explanation.

A zero-flag ledger still renders an empty calendar safely.

---

## 13. Export & Accuracy tab

### Excel report

Five sheets:

1. **Summary** — KPIs, live formulas, rule-hit bar chart, risk-mix pie chart.
2. **Flagged Entries** — filters, risk fills, `mm/dd/yyyy` dates,
   `"Rs. "#,##0.00` amounts.
3. **Flag Breakdown** — counts and amounts by rule and vendor.
4. **AI Explanations** — one explanation per flagged entry.
5. **Methodology** — rule logic, weights, scoring, ISA 240, and Karachi
   context.

The header reads **“AuditGuard Audit Report — Karachi”** and includes
**“Prepared in Karachi, Pakistan”**.

### CSV

The CSV contains flagged rows with `Amount (Rs.)`, `MM/DD/YYYY` dates, risk
level, flags, and reasons. It opens cleanly in Excel because it is UTF-8 with
BOM.

### Accuracy

With a `GroundTruth` column:

- overall TP, FP, FN, TN, precision, recall, F1, and accuracy,
- a confusion-matrix heatmap,
- per-rule precision/recall/support,
- missed-anomaly and false-alarm tables.

A `MultiRule` row counts as detected only when at least two flags fire.
Per-rule metrics use one-vs-rest over the six single-rule labels.

**Example:** the demo scores 57 TP, 0 FP, 0 FN, 549 TN → 100% precision, recall,
and F1.

---

## 14. Privacy and safety

- No database and no server-side persistence.
- Uploaded files and Groq keys disappear when the session ends.
- Excel text that starts with `=`, `+`, `-`, `@`, tab, or newline is forced to
  plain text to prevent formula injection.
- The LLM never changes a flag, score, or accuracy number.
- An ungrounded LLM reply is rejected automatically.

---

## 15. Troubleshooting

| Symptom | Fix |
| --- | --- |
| Dates look swapped | Change **Input date format** to match the source |
| An entry is unexpectedly a holiday | Check the extra holiday list for a mistyped date |
| Every amount looks unusual | Toggle **Lakh/Crore number format** |
| Groq text does not appear | Check the key status and the notice above the cards |
| A filter shows zero rows | Reset risk levels to all four and minimum score to 0 |
| Upload shows missing columns | Use the mapping panel or rename headers to the fixed schema |

---

## 16. Demo data at a glance

| Label | Rows |
| --- | --- |
| Clean | 549 |
| Duplicate | 12 |
| RoundAmount | 5 |
| Weekend | 5 |
| JustBelowLimit | 6 |
| SelfApproval | 5 |
| BenfordManip | 18 |
| MultiRule | 6 |
| **Total** | **606** |

The audit flags **57** entries: 41 Medium, 4 High, 2 Critical, and 10 Low.
The demo includes 25 Karachi vendors, 10 accounts, and 6 staff members.
