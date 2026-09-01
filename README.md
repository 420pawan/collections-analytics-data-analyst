# Collections Analytics — Data Analyst Assignment

## Executive verdict

**The reported 11% month-on-month recovery improvement is not supported as a sustained trend.** The February→March movement is approximately **+10.0% on the golden, reversal-adjusted series**, but the full Jan–Jul period is **flat/slightly negative (−2.1%)**.

**Investment recommendation:** use **AI Voice Automation as a controlled pilot hypothesis**, not as an immediate ₹10 Cr commitment. Deploy approximately **₹1.5–2 Cr for a 90-day randomized pilot** and release the balance only if predefined incremental-recovery and ROI gates are met.

> **Important:** The AI Voice recovery and cost figures are illustrative hypotheses, not observed historical performance. The supplied dataset contains no existing AI-voice treatment group, so the pilot is the evidence-generating step.

## What this repository contains

| Folder | Purpose |
|---|---|
| `01_notebook/` | Reproducible analysis and reasoning |
| `02_sql/` | Golden-layer, metric, and analytical SQL |
| `03_golden/` | Reproducible golden-data pipeline |
| `04_data_quality/` | Data-quality findings, treatment, and business impact |
| `05_statistics/` | Mix/bias checks and counterfactual / DiD design |
| `06_dashboard/` | One-screen CEO-facing dashboard |
| `07_executive/` | ≤2-page executive memo (PDF + editable DOCX) |
| `08_architecture/` | Production data architecture |
| `data/raw/` | Supplied assignment dataset archive |

## Recommended review order

1. **Open `06_dashboard/executive_dashboard.html`** — one-screen decision view.
2. **Read `07_executive/executive_memo.pdf`** — maximum two pages.
3. **Read `04_data_quality/data_quality_report.md`** — issues, detection, treatment, and impact.
4. **Open `01_notebook/collections_analysis.ipynb`** — reasoning and reproducible checks.
5. **Inspect `02_sql/collections_analysis.sql` and `03_golden/golden_dataset_pipeline.py`** — implementation/audit trail.
6. **Review `05_statistics/statistical_investigation_and_counterfactual.md`** — causal limitations and experiment design.

## Assignment coverage

The assignment asks for independent reconstruction of recovery performance, data forensics, driver analysis, a test of the reported 11% improvement, a counterfactual methodology, and a ₹10 Cr investment recommendation. It also explicitly requires investigation of portfolio mix, DPD, Client, Geography, Language, Agent, Agent tenure, Campaign, Channel, Telephony vendor, Calling time, Attempt frequency, and Borrower segment.

This submission covers all dimensions that the supplied schema supports. **Client and Language are explicitly documented as unavailable schema fields rather than fabricated.** Calling time and agent tenure are treated as directional where source-data limitations prevent stronger claims.

## Key analytical decisions

- Reconstruct recovery independently; do not trust the reported KPI.
- Keep payment transaction grain at `payment_id`; do not collapse transactions by `payment_reference`.
- Remove exact duplicate payment re-ingestion rows.
- Net reversals in the month the reversal occurs rather than rewriting the original month.
- Resolve event borrower identity through `account_id → accounts.borrower_id` where needed.
- Use `agent_id` as the operational key; employee codes/names are not reliable person-level identity fields in this synthetic data.
- Harmonize `PROMISE_TO_PAY` and `PTP` into a canonical PTP disposition.
- Treat channel attribution as directional because there is no ground-truth touch→payment causal link.
- Do not fabricate Client or Language analysis: those fields are absent from the supplied schema.
- Treat August as partial and exclude it from full-month trend claims.

## Reproducibility

The supplied dataset is stored as `data/raw/collections_30k_dataset.zip` because the raw CSVs are large. **Extract the ZIP into `data/raw/` before running the notebook or pipeline.**

After extraction, `data/raw/` should contain the supplied CSVs, including `accounts.csv`, `payments.csv`, `agents.csv`, `daily_targeting.csv`, `campaigns.csv`, and the other source tables.

### Windows / VS Code

From the repository root in PowerShell:

```powershell
Expand-Archive -Path .\data\raw\collections_30k_dataset.zip -DestinationPath .\data\raw -Force
python .\03_golden\golden_dataset_pipeline.py
```

If the files are already extracted:

```powershell
python .\03_golden\golden_dataset_pipeline.py
```

The pipeline writes golden outputs and `dq_report_counts.csv` to `data/golden/` and does not modify the raw input folder.

### macOS / Linux

```bash
unzip -o data/raw/collections_30k_dataset.zip -d data/raw
python 03_golden/golden_dataset_pipeline.py
```

The notebook is path-aware and can be run from the repository root or from the `01_notebook/` directory.

Python dependencies are listed in `requirements.txt`.

## Submission integrity notes

- The dashboard, memo, notebook, SQL, and data-quality report should be read as one evidence chain.
- The 11% figure is treated as a claim to test, not as a ground-truth KPI.
- The AI Voice recommendation is deliberately **low-to-medium confidence** because the dataset contains no historical AI Voice channel.
- The recommended ₹1.5–2 Cr pilot is a staged commitment, not a claim that the full ₹10 Cr has proven ROI.

## Data handling note

The raw dataset is included only because it was supplied for this take-home assignment. It should not be redistributed outside the hiring process.
