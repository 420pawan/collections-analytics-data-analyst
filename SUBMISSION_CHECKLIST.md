# Submission Checklist

## Assignment deliverables

- [x] Git repository
- [x] Analysis notebook with reasoning
- [x] Production-quality SQL repository
- [x] Golden dataset / reproducible pipeline
- [x] Data Quality Report: issue, detection, treatment, business impact
- [x] One-screen CEO dashboard
- [x] Executive memo ≤2 pages (PDF + editable DOCX)
- [x] Production architecture diagram

## Required analytical coverage

- [x] Independent recovery reconstruction
- [x] Reported 11% claim challenged and quantified
- [x] Portfolio mix
- [x] DPD
- [x] Client — explicitly marked unavailable in supplied schema
- [x] Geography
- [x] Language — explicitly marked unavailable in supplied schema
- [x] Agent
- [x] Agent tenure
- [x] Campaign
- [x] Channel
- [x] Telephony vendor
- [x] Calling time
- [x] Attempt frequency
- [x] Borrower segment
- [x] Mix / cohort / selection / survivorship / Simpson checks
- [x] Attribution-window limitation
- [x] Counterfactual / DiD design with treatment, control, assumptions, confounders, identification, limitations
- [x] ₹10 Cr recommendation with incremental recovery range, cost, ROI/breakeven, assumptions, downside, confidence

## Final pre-submission QA

1. Extract `data/raw/collections_30k_dataset.zip` and run the golden pipeline successfully.
2. Run the notebook from the repository root and confirm it finds `data/raw/` automatically.
3. Open `06_dashboard/executive_dashboard.html` locally in a browser.
4. Open `07_executive/executive_memo.pdf` and confirm it is no more than 2 pages.
5. Cross-check headline numbers across README, dashboard, memo, notebook, SQL, and DQ report.
6. Confirm the repository contains no passwords, API keys, `.env` files, personal documents, or unrelated screenshots.
7. Push to GitHub and open the repository in a private/incognito browser window to verify access if required by the form.
8. Only then submit the GitHub URL in the assignment form.
