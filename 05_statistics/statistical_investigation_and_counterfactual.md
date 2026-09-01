# Part 3 — Statistical Investigation & Part 4 — Counterfactual Design

## Part 3: Statistical Investigation

For each effect, we tested directly against the golden dataset rather than assuming it applies.

### Mix effects (portfolio composition)
**Test:** `risk_segment` and `loan_type` share of the *targeted* population, by month.
**Finding:** Stable within ±2pp all year (e.g. HIGH risk 24.5–25.5%, LOW 24.9–25.7%). **Fact:** the flat aggregate recovery trend is not a mix-effect artifact — the underlying population being worked hasn't shifted.

### Cohort effects
**Test:** Account `opened_at` month vs. `risk_segment`/`loan_type` distribution (does the book being *acquired* change over time, which would only show up with a lag as those accounts age into collections?).
**Finding:** Stable, no drift. **Fact**, within the observation window — cannot rule out a cohort effect that would only mature beyond the 8 months of data available.

### Simpson's paradox
**Test:** Conversion rate (paid/targeted) computed *within* each `risk_segment` and each `loan_type` separately, by month — checking whether opposing subgroup trends could be cancelling out in the flat aggregate.
**Finding:** No subgroup shows a directional trend either — every segment (HIGH/LOW/MEDIUM/NPA risk; AUTO/BNPL/CONSUMER/CREDIT_CARD/PERSONAL) oscillates in the same 37–46% noisy band with no trend. **Fact:** this rules out Simpson's paradox as an explanation — the aggregate isn't hiding real subgroup movement, because there isn't any.

### Selection bias
**Risk:** if the population being targeted each month is systematically different (e.g. campaigns increasingly select easier-to-collect accounts), naive conversion rate would rise even with no operational improvement.
**Test:** Average DPD of targeted accounts by month (56.6 → 56.3, essentially flat) and target_definition mix by month (DPD>=30/DPD>=60/HIGH_RISK/NPA/PROMISE_BROKEN shares all stable ±2pp).
**Finding:** No evidence of selection drift. **Fact.**

### Survivorship bias
**Risk:** accounts that fail to convert could be dropped from later targeting rounds (`WRITEOFF`/`CLOSED`), inflating the apparent conversion rate of the surviving population over time.
**Test:** `daily_targeting` population size per month is stable (5,160–5,800 distinct accounts, excluding partial August) — it is not shrinking toward only "easy" accounts, and `account_status_history` shows status transitions distributed evenly across the period rather than concentrated early.
**Finding:** No evidence of survivorship-driven denominator shrinkage. **Fact.**

### Attribution-window bias
**Risk:** a payment could be credited to whichever campaign/channel most recently touched the account, regardless of which contact actually caused the payment — inflating whichever channel calls most frequently.
**Test:** qualitative — the raw schema has no ground-truth causal link between a contact event and a resulting payment; any attribution (including the last-touch logic used in `sql_repository.sql` §6B) is an assumption, not measured fact.
**Finding:** **Hypothesis / unresolved** — this is a genuine blind spot in the data as given, not something we can rule in or out. Any channel-level ROI claim (including our own ₹10 Cr recommendation reasoning) inherits this uncertainty and should be treated as directional, not precise.

### Time-series effects (seasonality, day-of-week, autocorrelation)
**Test:** Visual + numeric inspection of the 7-month naive and golden series (see notebook) for autocorrelation or a recurring monthly pattern.
**Finding:** The series is consistent with noise around a flat mean — no detectable seasonal or autocorrelated structure at monthly granularity, though 7 data points is too short to rule out a longer seasonal cycle (e.g. annual) with any confidence. **Hypothesis** (insufficient data to confirm or rule out longer-cycle seasonality).

---

## Part 4: Counterfactual — "What would recovery have looked like without the targeting change?"

**Important honesty note:** we tested for an actual targeting-strategy break in the data (campaign `strategy_version` mix, `target_definition` mix, and targeted-population DPD/risk mix over time) and found **no detectable shift** — all are flat throughout the 8-month window. The assignment instructs us to *assume* a change happened; since the data doesn't show one, this section documents the *methodology* we would apply if leadership can point to an actual change date (e.g. from a change log, not inferable from this dataset alone), rather than fabricating a break point that isn't supported by evidence.

### Design (Difference-in-Differences)
- **Treatment group:** accounts targeted under the new campaign definitions/strategy after the change date.
- **Control group:** accounts that continued to be targeted under the *prior* strategy's logic in the same period — if the change was rolled out gradually or A/B tested, this is directly observable; if it was a hard cutover for the whole book, the control instead has to be a synthetic counterfactual (e.g. a matched pre-period trend projected forward) rather than a true concurrent control.
- **Identification strategy:** compare the *change* in conversion rate (paid/targeted) for treatment vs. control, before vs. after the change date — the DiD estimate is `(treatment_after − treatment_before) − (control_after − control_before)`. This nets out any economy-wide or seasonal drift common to both groups, isolating the strategy's effect specifically.
- **Assumption (parallel trends):** treatment and control groups would have moved in parallel absent the change. This should be checked explicitly on pre-period data (plot both groups' conversion rate trend before the cutover; if they already diverge, DiD is invalid and matching/regression-adjustment is needed instead).
- **Confounders to control for:** DPD mix, risk_segment mix, loan_type mix, agent assignment, and channel mix between the two groups — if the new strategy also changed *who* gets targeted (not just how), a simple DiD will conflate the targeting-population change with the strategy's effect. Propensity-score matching on these covariates before running DiD would isolate the strategy effect more cleanly.
- **Limitations:** (1) no observed change date in this dataset to anchor the analysis on; (2) if the rollout was a simultaneous full-book cutover with no held-back control, we lose the concurrent-control comparison and must fall back to a weaker before/after or synthetic-control design, which is more vulnerable to any other contemporaneous change; (3) 8 months of data limits the pre-period available to validate the parallel-trends assumption.

### What we'd need from leadership to actually run this
The exact date(s) any campaign definitions, target rules, or channel mix were deliberately changed (a change log, not something we can reliably back out from the data), and whether the rollout was staged/A-B'd or a full cutover.
