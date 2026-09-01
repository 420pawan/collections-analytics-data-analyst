-- =====================================================================
-- Collections Analytics — SQL Repository
-- Golden Dataset construction + Independent Metric Definitions
-- Dialect: ANSI SQL / PostgreSQL-flavored. Adjust window/date funcs as needed.
-- =====================================================================

-- ---------------------------------------------------------------------
-- SECTION 1: GOLDEN DIMENSION — AGENTS
-- Raw: 30,000 rows / 1,000 unique agent_id / only 10 unique agent_name.
-- employee_code <-> agent_id mapping is not stable (an employee_code
-- maps to 17-33 different agent_ids). agent_id is the FK used in every
-- fact table, so we treat it as the stable entity and collapse to one
-- row per agent_id using the latest updated_at.
-- ---------------------------------------------------------------------
CREATE TABLE dim_agents_golden AS
SELECT DISTINCT ON (agent_id)
    agent_id,
    vendor_id,
    team,
    status,
    joined_at,
    updated_at
FROM agents
ORDER BY agent_id, updated_at DESC;
-- Row impact: 30,000 raw -> 1,000 golden (29,000 rows were SCD history,
-- collapsed to current state; employee_code/agent_name dropped as
-- unreliable identity fields).


-- ---------------------------------------------------------------------
-- SECTION 2: GOLDEN DIMENSION — BORROWERS
-- Raw: 30,600 rows / 11,015 unique borrower_id, with genuinely
-- conflicting (name, state) values recorded against the same
-- borrower_id over time (SCD overwrite pattern, not simple duplication).
-- ---------------------------------------------------------------------
CREATE TABLE dim_borrowers_golden AS
SELECT DISTINCT ON (borrower_id)
    borrower_id, name, phone, email, city, state, created_at, updated_at
FROM (
    SELECT DISTINCT * FROM borrowers   -- strip 600 exact duplicate rows first
) b
ORDER BY borrower_id, updated_at DESC;
-- Row impact: 30,600 raw -> 30,000 (drop 600 exact dup rows)
--             -> 11,015 golden (collapse SCD to latest updated_at).


-- ---------------------------------------------------------------------
-- SECTION 3: GOLDEN FACT — PAYMENTS
-- Findings:
--  (a) 500 EXACT duplicate rows on payment_id (identical in every
--      column) — clear ingestion/retry duplication. Dropped.
--  (b) 2,033 payment_references have >1 row with status = SUCCESS.
--      Of these, ~1,550 were exact duplicates already captured by (a).
--      The remaining ~1,782 have SUCCESS events a median of 70 days
--      apart — these are legitimate separate/installment payments
--      sharing a reference number, NOT duplicates. They are kept.
--  (c) payment_reference must NOT be used as an aggregation grain:
--      collapsing by reference and dating the sum to the latest event
--      would backdate/forward-date real money across months and
--      fabricate a trend. Grain stays at payment_id.
--  (d) REVERSED payments net out recovery — in the month the reversal
--      happens (standard accounting treatment), not restated back to
--      the original month.
-- ---------------------------------------------------------------------
CREATE TABLE fact_payments_golden AS
SELECT DISTINCT ON (payment_id)
    payment_id, account_id, borrower_id, event_at, payment_reference,
    amount, payment_status, payment_method, provider_id,
    DATE_TRUNC('month', event_at) AS recovery_month
FROM payments
ORDER BY payment_id, event_at;
-- Row impact: 25,500 raw -> 25,000 golden (drop 500 exact duplicate
-- payment_id rows). No reference-level collapsing performed.

CREATE VIEW monthly_net_recovery AS
SELECT
    recovery_month,
    SUM(CASE WHEN payment_status = 'SUCCESS'  THEN amount ELSE 0 END) AS gross_success_amt,
    SUM(CASE WHEN payment_status = 'REVERSED' THEN amount ELSE 0 END) AS reversed_amt,
    SUM(CASE WHEN payment_status = 'SUCCESS'  THEN amount ELSE 0 END)
      - SUM(CASE WHEN payment_status = 'REVERSED' THEN amount ELSE 0 END) AS net_recovered_amt
FROM fact_payments_golden
GROUP BY recovery_month
ORDER BY recovery_month;


-- ---------------------------------------------------------------------
-- SECTION 4: GOLDEN FACT — CALL DISPOSITIONS
-- Finding: "PROMISE_TO_PAY" and "PTP" co-exist as separate codes at
-- roughly equal volume across ALL schema versions (v1, v2, legacy) —
-- not a clean rename. A naive filter on 'PTP' alone misses ~50% of
-- real promises. Harmonized to a single canonical code.
-- ---------------------------------------------------------------------
CREATE TABLE fact_dispositions_golden AS
SELECT DISTINCT
    disposition_id, account_id, borrower_id, event_at, call_id, agent_id,
    disposition_code,
    CASE WHEN disposition_code = 'PROMISE_TO_PAY' THEN 'PTP' ELSE disposition_code END AS disposition_code_norm,
    disposition_version
FROM call_dispositions;


-- ---------------------------------------------------------------------
-- SECTION 5: INDEPENDENT METRIC DEFINITIONS
-- ---------------------------------------------------------------------

-- 5.1 Contact rate = share of OUTBOUND calls that connect
CREATE VIEW metric_contact_rate AS
SELECT DATE_TRUNC('month', event_at) AS month,
       100.0 * SUM(CASE WHEN call_status = 'ANSWERED' THEN 1 ELSE 0 END) / COUNT(*) AS contact_rate_pct
FROM calls
WHERE direction = 'OUTBOUND'
GROUP BY 1 ORDER BY 1;

-- 5.2 Right-Party-Contact (RPC) rate = dispositions that reflect an
-- actual conversation with the borrower (excludes NO_CONTACT/WRONG_NUMBER)
CREATE VIEW metric_rpc_rate AS
SELECT DATE_TRUNC('month', event_at) AS month,
       100.0 * SUM(CASE WHEN disposition_code_norm NOT IN ('NO_CONTACT','WRONG_NUMBER') THEN 1 ELSE 0 END) / COUNT(*) AS rpc_rate_pct
FROM fact_dispositions_golden
GROUP BY 1 ORDER BY 1;

-- 5.3 PTP rate = share of dispositions that result in a promise to pay
CREATE VIEW metric_ptp_rate AS
SELECT DATE_TRUNC('month', event_at) AS month,
       100.0 * SUM(CASE WHEN disposition_code_norm = 'PTP' THEN 1 ELSE 0 END) / COUNT(*) AS ptp_rate_pct
FROM fact_dispositions_golden
GROUP BY 1 ORDER BY 1;

-- 5.4 PTP kept rate
CREATE VIEW metric_ptp_kept_rate AS
SELECT DATE_TRUNC('month', event_at) AS month,
       100.0 * SUM(CASE WHEN status = 'KEPT' THEN 1 ELSE 0 END) / COUNT(*) AS ptp_kept_rate_pct
FROM promises_to_pay
GROUP BY 1 ORDER BY 1;

-- 5.5 Recovery rate (population-normalized, NOT naive sum-of-SUCCESS) —
-- the denominator is distinct accounts TARGETED that month, so the
-- metric can't be inflated by simply growing outreach volume.
CREATE VIEW metric_conversion_rate AS
WITH targeted AS (
    SELECT DATE_TRUNC('month', target_date) AS month, COUNT(DISTINCT account_id) AS n_targeted
    FROM daily_targeting GROUP BY 1
),
paid AS (
    SELECT recovery_month AS month, COUNT(DISTINCT account_id) AS n_paid
    FROM fact_payments_golden WHERE payment_status = 'SUCCESS' GROUP BY 1
)
SELECT t.month, 100.0 * p.n_paid / t.n_targeted AS conversion_rate_pct
FROM targeted t JOIN paid p ON t.month = p.month
ORDER BY t.month;

-- 5.6 Recovery per agent-hour
CREATE VIEW metric_recovery_per_agent_hour AS
WITH hours AS (
    SELECT DATE_TRUNC('month', login_at) AS month,
           SUM(EXTRACT(EPOCH FROM (logout_at - login_at))/3600.0) AS agent_hours
    FROM agent_sessions GROUP BY 1
)
SELECT h.month, r.net_recovered_amt / h.agent_hours AS recovery_per_agent_hour
FROM hours h JOIN monthly_net_recovery r ON h.month = r.recovery_month
ORDER BY h.month;

-- 5.7 Cost per rupee recovered (illustrative — plug in real cost inputs)
-- cost_per_channel_event assumptions must be supplied; structure shown.
CREATE VIEW metric_cost_per_rupee_recovered AS
SELECT
    recovery_month AS month,
    net_recovered_amt,
    -- :agent_cost_per_hour, :vendor_cost_per_call, :whatsapp_cost_per_msg are
    -- external cost inputs not present in this dataset — see memo assumptions.
    NULL::numeric AS total_cost_placeholder,
    NULL::numeric AS cost_per_rupee_recovered_placeholder
FROM monthly_net_recovery;


-- ---------------------------------------------------------------------
-- SECTION 6: FORENSICS QUERIES (Part 2 of the assignment)
-- ---------------------------------------------------------------------

-- 6A. Duplicate payments
SELECT payment_id, COUNT(*) c FROM payments GROUP BY payment_id HAVING COUNT(*) > 1;

-- 6B. Attribution — payments per campaign via most recent targeting record
--     before the payment event (naive "last touch" attribution — flag risk
--     that this over-credits whichever channel called most recently)
SELECT p.payment_id, p.account_id, p.event_at,
       (SELECT t.campaign_id FROM daily_targeting t
        WHERE t.account_id = p.account_id AND t.target_date <= p.event_at
        ORDER BY t.target_date DESC LIMIT 1) AS last_touch_campaign
FROM fact_payments_golden p WHERE p.payment_status = 'SUCCESS';

-- 6C. Timezone problem check — count of accounts/calls whose recorded
-- timezone differs from the vendor's own timezone (misclassification risk)
SELECT c.vendor_id, c.timezone AS call_tz, v.timezone AS vendor_tz, COUNT(*)
FROM calls c JOIN vendor_telephony v ON c.vendor_id = v.vendor_id
WHERE c.timezone <> v.timezone
GROUP BY 1,2,3;

-- 6D. Vendor disposition-code drift over time
SELECT disposition_version, DATE_TRUNC('month', event_at) AS month, COUNT(*)
FROM call_dispositions GROUP BY 1,2 ORDER BY 1,2;

-- 6E. Agent identity collisions
SELECT employee_code, COUNT(DISTINCT agent_id) AS n_agent_ids
FROM agents GROUP BY employee_code HAVING COUNT(DISTINCT agent_id) > 1;

-- 6F. Portfolio mix drift by account open month
SELECT DATE_TRUNC('month', opened_at) AS month, risk_segment, loan_type, COUNT(*)
FROM accounts GROUP BY 1,2,3 ORDER BY 1;

-- 6G. Denominator manipulation check — targeted population size vs
-- reported conversion base, month over month
SELECT DATE_TRUNC('month', target_date) AS month, COUNT(DISTINCT account_id) AS n_targeted
FROM daily_targeting GROUP BY 1 ORDER BY 1;
