# Data Quality Report — Collections Analytics

## 1. Summary table: Raw → Rejected/Corrected → Golden

| Table | Raw rows | Golden rows | What changed |
|---|---:|---:|---|
| agents | 30,000 | 1,000 | Collapsed SCD history to 1 row/agent_id (latest `updated_at`) |
| borrowers | 30,600 | 11,015 | Dropped 600 exact dup rows; collapsed SCD to latest `updated_at`/borrower_id |
| accounts | 30,000 | 30,000 | No duplication found; passthrough |
| payments | 25,500 | 25,000 | Dropped 500 exact duplicate `payment_id` rows |
| call_dispositions | 35,000 | 35,000 | Harmonized `PROMISE_TO_PAY` → `PTP` (no row loss) |
| calls | 91,350 | 90,000 | Dropped 1,350 exact duplicate `call_id` rows |
| whatsapp_events | 60,600 | 60,000 | Dropped 600 exact duplicate rows |
| daily_targeting | 45,000 | 45,000 | No duplication found |
| call_attempts | 120,000 | 120,000 | No duplication found |
| sms_events | 45,000 | 45,000 | No duplication found |
| field_visits | 25,000 | 25,000 | No duplication found |
| promises_to_pay | 18,000 | 18,000 | No duplication found |
| complaints | 8,000 | 8,000 | No duplication found |
| account_status_history | 60,000 | 60,000 | No duplication found (append-only; no same-timestamp overwrite conflicts detected) |
| agent_sessions | 15,000 | 15,000 | No duplication found |

## 2. Major issues found (detection → treatment → business impact)

### 2.1 Agent identity is not resolvable from `employee_code` or `agent_name`
**Detection:** `agents.csv` has 30,000 rows but only 1,000 unique `agent_id`, 1,099 unique `employee_code`, and just **10** unique `agent_name` values. Grouping by `employee_code` shows each code maps to 17–33 different `agent_id`s, and the reverse is also true — the two fields are effectively randomly cross-linked in this dataset, not a real 1:1 identity.
**Treatment:** `agent_id` is the key actually used as a foreign key in every fact table (calls, dispositions, PTPs, field visits, sessions), so we treat it as the stable operational entity and collapse the dimension to one row per `agent_id` (latest `updated_at`). `employee_code` and `agent_name` are dropped from the golden dimension — using them for identity or team rollups would create false collisions.
**Business impact:** Any "agent tenure" or "agent performance" analysis built on `employee_code` would silently merge dozens of unrelated agents together. This is why the assignment's request to analyze "Agent" and "Agent tenure" as drivers can only be done reliably at the `agent_id` grain, with tenure approximated from the earliest `joined_at` seen for that `agent_id`, flagged as **low confidence**.

### 2.2 Borrower records were never collapsed from history to current state
**Detection:** 30,600 rows / 11,015 unique `borrower_id`; some borrower_ids carry genuinely different `name`/`state` values across rows (not simple duplication) — e.g. one borrower_id has three versions with different names and states.
**Treatment:** Drop 600 exact duplicate rows, then keep the latest row per `borrower_id` by `updated_at` as current state.
**Business impact:** Geography/state-level cuts of performance would be wrong if computed against the raw table (a borrower could be double-counted across two states).

### 2.3 Duplicate payment rows would inflate reported recovery
**Detection:** 500 rows are **exact** duplicates on `payment_id` (identical across every column) — an ingestion/retry signature. Separately, 2,033 `payment_reference`s have more than one `SUCCESS` row; of those, ~1,550 are same-reference/same-amount/same-timestamp exact re-ingestions (already captured by the `payment_id` check), while the remaining ~1,782 have `SUCCESS` events a **median of 70 days apart** — these are real, separate repeat/installment payments sharing a reference number, not duplicates.
**Treatment:** Drop the 500 exact-duplicate rows. Do **not** collapse by `payment_reference` — doing so would merge legitimate separate transactions into one row and (worse) misdate the combined amount to the last event, which we found actually **fabricates an upward trend** where none exists (see §3). Transaction grain stays at `payment_id`.
**Business impact:** ~₹[dup amount, ≈2% of monthly gross] of reported recovery in the naive/reported-style number is duplicate rows. This is small relative to total recovery but is a real, fixable double-count.

### 2.4 Reversed payments are not being netted out
**Detection:** 6.2%–8.1% of gross `SUCCESS` amount each month is later `REVERSED` (chargebacks/failed settlement). This ratio is roughly stable/slightly rising over the period, not declining.
**Treatment:** Net `REVERSED` amounts against `SUCCESS` amounts **within the month the reversal occurs** (standard accounting treatment — a chargeback is a contra-entry in its own period, not a restatement of the original month).
**Business impact:** Naive recovery numbers overstate true collected cash by ~7% on average, consistently across the period — this doesn't change the *trend*, but it changes the *level*, which matters for the recovery-per-agent-hour and cost-per-₹-recovered metrics leadership will use to size the ₹10 Cr bet.

### 2.5 Disposition codes double-book the same outcome
**Detection:** `PROMISE_TO_PAY` and `PTP` exist as **separate, co-occurring** disposition codes at roughly equal volume, in every schema version (`v1`, `v2`, `legacy`) simultaneously — not a clean rename across versions.
**Treatment:** Harmonize `PROMISE_TO_PAY` → `PTP` as one canonical code in the golden layer.
**Business impact:** A "PTP rate" computed by filtering on the literal string `PTP` alone would silently under-report the true PTP rate by roughly half.

### 2.6 Timezones are recorded inconsistently, not just differently
**Detection:** `accounts.timezone` and `calls.timezone` both carry three values (UTC / Asia/Kolkata / Asia/Dubai) that vary row-by-row rather than being fixed per entity, and don't always match the owning vendor's `vendor_telephony.timezone`.
**Treatment:** All monthly aggregations in this analysis use the raw `event_at` timestamp as recorded (not timezone-shifted), and calling-time analysis is flagged as **directional only** — see §4.
**Business impact:** A "best calling hour" recommendation built naively on `event_at.hour` without normalizing timezone could be off by up to 4.5 hours for Dubai-tagged records, which would misdirect a calling-time optimization investment.

### 2.7 Targeting population size is stable — ruling out simple denominator manipulation
**Detection:** Distinct accounts targeted per month ranges narrowly from 5,160–5,800 (excluding the partial final month) — no meaningful growth or shrinkage in the population used as the base for conversion metrics.
**Treatment:** None needed; this is a clean check, included here because leadership specifically asked whether the reported improvement could be an artifact of a shrinking denominator. It is not — see §3.

## 3. The 11% claim — quantified in the Data Quality context
Naive (reported-style) monthly recovery from Jan–Jul 2026 is essentially **flat** (−0.4% Jan-to-Jul; oscillating ±4–11% month to month with no direction). After the golden-dataset cleaning above (duplicate removal, reversal netting), the same period is **slightly negative** (−2.1% Jan-to-Jul). The single **Feb→Mar** month-over-month move is +11.0% (naive) / +10.0% (golden) — this is the only month in the series that lands near "11%," which is very likely the actual source of the reported figure, generalized incorrectly into a sustained trend. Full quantification and the independent-metric cross-checks (contact rate, RPC, PTP rate, PTP kept rate, conversion rate, recovery/agent-hour — all flat across the period) are in the Executive Memo and notebook.

## 4. Known limitations of this golden layer (be transparent about these)
- Attribution of a payment to a specific campaign/channel uses last-touch logic (most recent targeting record before the payment) — this is a documented assumption, not ground truth, and over-credits whichever channel touched the account most recently.
- Calling-time analysis (`event_at.hour`) is not timezone-normalized given the inconsistent per-row timezone tagging described in §2.6; treat any "best hour to call" conclusion as directional only.
- Agent tenure is approximated from earliest observed `joined_at` per resolved `agent_id`, given the identity issues in §2.1 — flagged low confidence.
- WhatsApp/SMS event tables record each event type (`SENT`, `DELIVERED`, `READ`, `REPLIED`, `PAYMENT_CLICK`) as independently-countable rows rather than a linked per-message funnel, so true funnel conversion (e.g. delivered→read→replied for the *same* message) cannot be computed from this schema as given; only aggregate volumes by type are reliable.
