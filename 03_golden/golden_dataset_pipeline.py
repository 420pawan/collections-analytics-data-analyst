"""
Collections Analytics - Golden Dataset & Metrics Pipeline
============================================================
Builds a trustworthy analytical layer from 17 raw source tables and
computes an independent set of recovery-performance metrics.

Every cleaning decision below is documented inline with WHY, and the
row-count impact (raw -> rejected/corrected -> golden) is logged to
dq_report_counts.csv for the Data Quality Report.
"""
import pandas as pd
import numpy as np
import json
import os
from pathlib import Path

SRC = Path(os.getenv("DATA_DIR", "./data/raw"))
OUT = Path(os.getenv("GOLDEN_DIR", "./data/golden"))
OUT.mkdir(parents=True, exist_ok=True)

REQUIRED_FILES = [
    "agents.csv", "borrowers.csv", "accounts.csv", "payments.csv",
    "call_dispositions.csv", "daily_targeting.csv", "call_attempts.csv",
    "calls.csv", "whatsapp_events.csv", "sms_events.csv", "field_visits.csv",
    "promises_to_pay.csv", "complaints.csv", "account_status_history.csv",
    "agent_sessions.csv", "campaigns.csv", "vendor_telephony.csv"
]
missing = [f for f in REQUIRED_FILES if not (SRC / f).exists()]
if missing:
    raise FileNotFoundError(
        f"Missing raw CSVs in {SRC}. Extract data/raw/collections_30k_dataset.zip first. "
        f"Missing: {', '.join(missing)}"
    )

log = []  # (table, stage, rows, note)
def L(table, stage, rows, note=""):
    log.append({"table": table, "stage": stage, "rows": rows, "note": note})

# ------------------------------------------------------------------
# 1. AGENTS -- entity resolution
# ------------------------------------------------------------------
# Raw: 30,000 rows but only 1,000 unique agent_id and only 10 unique
# agent_name values. employee_code <-> agent_id mapping is essentially
# random noise (an employee_code maps to 17-33 different agent_ids and
# vice versa) -- neither field is a stable person-level identity on its
# own in this synthetic set.
#
# DECISION: agent_id is the key actually used as a foreign key in every
# fact table (calls, dispositions, ptp, field_visits, sessions). We treat
# agent_id as the stable operational entity ("a seat/login"), and collapse
# the 30,000 dimension rows down to one row per agent_id by taking the
# most recent row (max updated_at) for slowly-changing attributes
# (team, status, vendor_id). employee_code and agent_name are DROPPED
# from the golden dimension -- they carry no reliable identity signal
# here and would create false collisions if used for grouping.
agents_raw = pd.read_csv(SRC / "agents.csv", parse_dates=["joined_at", "updated_at"])
L("agents", "raw", len(agents_raw))

agents_golden = (
    agents_raw.sort_values("updated_at")
    .groupby("agent_id", as_index=False)
    .last()[["agent_id", "vendor_id", "team", "status", "joined_at", "updated_at"]]
)
L("agents", "golden", len(agents_golden), "collapsed to 1 row/agent_id via latest updated_at; employee_code/agent_name dropped as unreliable identity fields")
agents_golden.to_csv(OUT / "dim_agents.csv", index=False)

# ------------------------------------------------------------------
# 2. BORROWERS -- SCD overwrite handling
# ------------------------------------------------------------------
# Raw: 30,600 rows, only 11,015 unique borrower_id. Same borrower_id
# appears with genuinely different name/state combinations (not just
# repeated inserts) -- e.g. BRW0000001 has 3 different (name,state)
# versions. This is a slowly-changing dimension that was never
# collapsed to current-state.
#
# DECISION: keep the latest row per borrower_id by updated_at as the
# current golden record. Also drop 600 pure exact-duplicate rows first.
brw_raw = pd.read_csv(SRC / "borrowers.csv", parse_dates=["created_at", "updated_at"])
L("borrowers", "raw", len(brw_raw))
brw_dedup_exact = brw_raw.drop_duplicates()
L("borrowers", "after_exact_dedup", len(brw_dedup_exact), f"dropped {len(brw_raw)-len(brw_dedup_exact)} exact duplicate rows")
borrowers_golden = (
    brw_dedup_exact.sort_values("updated_at")
    .groupby("borrower_id", as_index=False)
    .last()
)
L("borrowers", "golden", len(borrowers_golden), "collapsed SCD to latest updated_at per borrower_id")
borrowers_golden.to_csv(OUT / "dim_borrowers.csv", index=False)

# ------------------------------------------------------------------
# 3. ACCOUNTS -- pass-through with timezone normalization flag
# ------------------------------------------------------------------
acct_raw = pd.read_csv(SRC / "accounts.csv", parse_dates=["opened_at"])
L("accounts", "raw", len(acct_raw))
dup_acct = acct_raw.duplicated().sum()
accounts_golden = acct_raw.drop_duplicates(subset=["account_id"], keep="last")
L("accounts", "golden", len(accounts_golden), f"exact dup rows found: {dup_acct}; deduped on account_id keep-last")
accounts_golden.to_csv(OUT / "dim_accounts.csv", index=False)

# ------------------------------------------------------------------
# 4. PAYMENTS -- the highest-stakes cleaning decision
# ------------------------------------------------------------------
# Raw: 25,500 rows / 25,000 unique payment_id / 20,821 unique payment_reference.
# Found:
#   (a) 500 rows are EXACT duplicate payment_id rows (identical in every
#       column) -- clear ingestion/retry duplication. Drop outright.
#   (b) Of refs appearing >1x, 2,033 payment_references have MORE THAN
#       ONE row with status=SUCCESS for the SAME reference. 1,550 of
#       those have identical amount AND identical event_at timestamp
#       across the duplicate SUCCESS rows -- a textbook double-charge /
#       duplicate-ingestion signature, not a legitimate retry.
#   (c) The remaining ~1,783 refs with multiple SUCCESS rows but
#       DIFFERENT amounts/timestamps are ambiguous (could be legitimate
#       partial/installment payments under a shared reference). We treat
#       these conservatively: keep all distinct (amount, event_at)
#       combinations, since collapsing them could under-count real
#       partial payments.
#   (d) REVERSED payments: if a payment_reference has both a SUCCESS and
#       a later REVERSED row, the money was recovered and then reversed
#       (chargeback/failed settlement) -- net recovery should be zero.
#       We exclude REVERSED-paired SUCCESS amounts from recovery.
#
# DECISION (golden "successful, attributable payment" definition):
#   1. Drop exact duplicate rows (same payment_id).
#   2. Within a payment_reference, drop SUCCESS rows that are exact
#      duplicates on (amount, event_at) -- keep one.
#   3. For any payment_reference where a REVERSED row exists at a later
#      event_at than a SUCCESS row, net that SUCCESS amount out of
#      "recovered" (net-recovery adjustment).
#   4. Only status == SUCCESS (net of reversals) counts toward recovery.
pay_raw = pd.read_csv(SRC / "payments.csv", parse_dates=["event_at"])
L("payments", "raw", len(pay_raw))

pay_1 = pay_raw.drop_duplicates(subset=["payment_id"], keep="first")
L("payments", "after_exact_id_dedup", len(pay_1), f"dropped {len(pay_raw)-len(pay_1)} exact duplicate payment_id rows")

pay_2 = pay_1.drop_duplicates(subset=["payment_reference", "payment_status", "amount", "event_at"], keep="first")
L("payments", "after_ref_amount_ts_dedup", len(pay_2), f"dropped {len(pay_1)-len(pay_2)} rows that were identical (reference, status, amount, timestamp) -- ingestion duplicates")

# IMPORTANT: payment_reference is NOT a safe aggregation grain -- 1,782
# references have multiple genuinely distinct SUCCESS transactions
# spread a median of 70 days apart (real repeat/installment payments,
# confirmed by checking event_at spread). Collapsing by reference and
# dating the total to the *last* event would wrongly shift early-month
# money into later months and fabricate a growth trend. So:
#   - the transaction grain stays at payment_id (one row = one event)
#   - reversals are netted in the MONTH THE REVERSAL OCCURS (standard
#     accounting treatment: a chargeback is a contra-entry in the period
#     it happens, not a restatement of the original month)
pay_2["month"] = pay_2["event_at"].dt.to_period("M").astype(str)
pay_2.to_csv(OUT / "fact_payments_golden.csv", index=False)

gross_success_monthly = pay_2[pay_2.payment_status == "SUCCESS"].groupby("month")["amount"].sum()
reversed_monthly = pay_2[pay_2.payment_status == "REVERSED"].groupby("month")["amount"].sum()
net_recovery_monthly = (gross_success_monthly.subtract(reversed_monthly, fill_value=0)).rename("net_recovered_amt")
net_recovery_monthly.to_csv(OUT / "monthly_net_recovery.csv")
L("payments", "golden_net_recovery_by_month", len(pay_2), "grain kept at payment_id; reversals netted within their own month, not backdated")

# ------------------------------------------------------------------
# 5. CALL DISPOSITIONS -- code harmonization across schema versions
# ------------------------------------------------------------------
# Found: "PROMISE_TO_PAY" and "PTP" co-exist as SEPARATE disposition
# codes within the SAME version simultaneously (not a clean v1->v2
# rename) at roughly equal volume. A naive "PTP rate" that filters on
# only one of these codes silently misses ~50% of actual promises.
# DECISION: harmonize PROMISE_TO_PAY -> PTP as a single canonical code
# in the golden layer; keep disposition_version for lineage.
disp_raw = pd.read_csv(SRC / "call_dispositions.csv", parse_dates=["event_at"])
L("call_dispositions", "raw", len(disp_raw))
disp_golden = disp_raw.drop_duplicates()
disp_golden["disposition_code_norm"] = disp_golden["disposition_code"].replace({"PROMISE_TO_PAY": "PTP"})
L("call_dispositions", "golden", len(disp_golden), "harmonized PROMISE_TO_PAY -> PTP as canonical code")
disp_golden.to_csv(OUT / "fact_dispositions_golden.csv", index=False)

# ------------------------------------------------------------------
# 6. DAILY TARGETING -- golden population denominator
# ------------------------------------------------------------------
tgt_raw = pd.read_csv(SRC / "daily_targeting.csv", parse_dates=["target_date"])
L("daily_targeting", "raw", len(tgt_raw))
tgt_golden = tgt_raw.drop_duplicates()
L("daily_targeting", "golden", len(tgt_golden))
tgt_golden.to_csv(OUT / "fact_targeting_golden.csv", index=False)

# ------------------------------------------------------------------
# 7. Other event tables -- exact-dup strip only (pass-through)
# ------------------------------------------------------------------
for fname, key_cols in [
    ("call_attempts.csv", None),
    ("calls.csv", ["call_id"]),
    ("whatsapp_events.csv", None),
    ("sms_events.csv", None),
    ("field_visits.csv", None),
    ("promises_to_pay.csv", None),
    ("complaints.csv", None),
    ("account_status_history.csv", None),
    ("agent_sessions.csv", None),
]:
    tname = fname.replace(".csv", "")
    df = pd.read_csv(SRC / fname)
    L(tname, "raw", len(df))
    if key_cols:
        gold = df.drop_duplicates(subset=key_cols, keep="last")
    else:
        gold = df.drop_duplicates()
    L(tname, "golden", len(gold), f"dropped {len(df)-len(gold)} exact/key duplicate rows")
    gold.to_csv(OUT / f"fact_{tname}_golden.csv", index=False)

# ------------------------------------------------------------------
# Save the cleaning log
# ------------------------------------------------------------------
log_df = pd.DataFrame(log)
log_df.to_csv(OUT / "dq_report_counts.csv", index=False)
print(log_df.to_string(index=False))
print("\nGolden tables written to", OUT)
