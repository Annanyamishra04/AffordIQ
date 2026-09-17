# Financial logic

A reference for every rule the engine applies, why it exists, and where it
is enforced and tested. Each rule states the conservative bias it encodes.

---

## 1. The starting balance

`current_available_balance` is the balance **as of the request date**.
Settled historical events are used only to infer patterns and burn rates —
they are never re-summed into the balance.

> Re-adding settled history would double-count money the balance already
> reflects.

**Where:** `timeline.build_timeline` · **Tested:** `test_engine_core.py`

---

## 2. Event status

| Status | Debit | Credit |
|---|---|---|
| `settled` (future-dated) | counted | counted |
| `scheduled` | counted | counted |
| `pending` | **counted** | **excluded** |
| `cancelled` / `failed` | excluded | excluded |
| `non_cash` | excluded | excluded |

The asymmetry on `pending` is the single most important conservatism in the
system: money you might owe is reserved, money you might receive is not.

> Overstating available cash causes an overdraft. Understating it causes a
> slightly delayed purchase. These costs are not symmetric.

**Where:** `timeline.build_timeline` · **Tested:**
`test_pending_debit_is_reserved_but_pending_credit_is_excluded`,
`test_cancelled_and_failed_events_are_excluded`,
`test_unrealized_investment_value_is_never_counted`

---

## 3. Recurring series detection

Events are grouped by `(category, description)`, sorted by date, and the
**median** gap between occurrences is taken as the cadence.

- Median rather than mean, so one missed or duplicated month doesn't distort
  the cadence.
- A cadence under 6 days is rejected as noise.
- A single occurrence never creates a recurrence — one grocery run is not a
  subscription.
- Detection considers `settled` **and** `scheduled` events, so a new starter
  with one paid and one confirmed salary still gets salary projected forward.
  `pending` rows are excluded, being typically one-offs.

**Salary is grouped by category alone**, not by description, because the same
income stream is legitimately described differently over time ("Prorated
first salary" → "Next confirmed salary" → "Salary credit"). Grouping on
description would fragment one stream into three non-recurring events.

**Where:** `timeline._detect_cadence_days`, `timeline._series_key`
**Tested:** `test_date_handling_no_recurrence_fabricated_from_single_occurrence`

---

## 4. Calendar-month recurrence

A cadence of **25–35 days** is treated as monthly and advanced by calendar
month, preserving day-of-month and clamping to the last valid day.

```
31 Jan  +1 month → 28 Feb   (29 Feb in a leap year)
31 Mar  +1 month → 30 Apr
30 Nov  +2 months → 30 Jan
```

> Naive 30-day stepping drifts. A rent date of the 31st would march
> backwards through the calendar and eventually land in the wrong month,
> putting the forecast's low point on the wrong day.

Stepping is always computed from the **anchor** date (`anchor + n months`)
rather than by repeatedly incrementing, so clamping never compounds: a bill
on the 31st that clamps to 28 Feb returns to 31 Mar, not 28 Mar.

**Where:** `timeline._add_calendar_months` · **Tested:**
`test_add_calendar_months_*`, `test_monthly_rent_does_not_drift_across_months`

---

## 5. Daily essential spending

Variable essentials — groceries, transport, dining, healthcare, shopping,
work expenses — are averaged over the trailing 90 days and spread as a
**continuous daily debit**.

```
daily_rate = total_in_window / days_observed
```

> A monthly lump would place a month of groceries on a single day, leaving
> the rest of the month artificially flush and hiding the mid-month dip a
> real user experiences. The low point of the forecast is the number the
> whole system depends on, so it must be realistic.

Falls back to all available history when the 90-day window is empty; emits
nothing when there is no history at all, rather than inventing a rate.

**Where:** `timeline.build_timeline` (section 3) · **Tested:**
`test_essential_spending_is_spread_daily_not_lumped_monthly`,
`test_essential_spending_absent_when_no_history`

---

## 6. Currency conversion

Amounts convert to the user's home currency at the rate for **the event's
own date**, not the request date.

Resolution order: direct rate → inverted counter-rate → nearest available
date for that pair → raise.

> A future payment converted at today's rate misstates its real cost. Using
> the event's own date keeps each line item honest.

**Where:** `data_loader.Dataset.convert` · **Tested:**
`test_currency_conversion_*`

---

## 7. Message-derived evidence

Messages are **untrusted free text**. Only concrete facts are extracted:

| Signal | Effect |
|---|---|
| new salary figure + effective date | overrides projected salary from that date |
| salary figure, no date | applies from the message's `sent_at` |
| contract/employment ended | stops salary projection entirely |
| rent change as a percentage | scales projected rent |
| "still pending" / "not credited" | excludes that event from cash flow |
| "transfer between your two accounts" | excludes both legs as net-zero |

Guards that matter:

- Only `source_type == "employer"` messages can change salary. A friend
  saying "you're getting a raise" does nothing.
- Pending language **beats** confirmation language — an unapproved bonus
  never becomes an override.
- An override requires an explicit amount. Vague optimism is ignored.
- Bilingual (English/Indonesian) keyword lists, with dates as `YYYY-MM-DD`
  and amounts as `<CUR> <NUMBER>`, so both languages parse identically.

> Instructions embedded in message text are never executed — only facts are
> read. In any real deployment this text is attacker-controlled.

**Where:** `engine/messages.py` · **Tested:** `test_messages_and_images.py`

---

## 8. Image-derived amounts

A blank `amount` means the figure exists only on a linked receipt, payslip
or invoice. Resolution order:

1. **Evidence sidecar** — a gitignored JSON file of human-verified
   transcriptions, looked up via `$BUY_OR_WAIT_IMAGE_EVIDENCE`,
   `<dataset_dir>/image_evidence.json`, then
   `local_evidence/image_evidence.json`.
2. **OCR fallback** — `pytesseract` + `Pillow`, preferring grand-total-like
   labels and taking the last match.
3. **`EvidenceResolutionError`.**

A declared currency in the sidecar is checked against the event row and a
mismatch raises, which catches transcription slips.

> A blank amount is never treated as zero. A vanished debit understates the
> drain and could make an unsafe payment look safe — precisely the failure
> this system exists to prevent.

Transcribed figures live **outside version control** so no dataset-specific
values are ever committed.

**Where:** `engine/image_evidence.py` · **Tested:**
`test_resolver_*`, `test_dataset_loader_resolves_blank_amount_via_sidecar`

---

## 9. Minimum balance

The protected floor. A plan is safe only if the running balance stays at or
above `minimum_balance_to_keep` at **every checkpoint** in the 90-day
window — not merely on the payment dates.

A tolerance of `1e-6` absorbs floating-point noise only.

**Where:** `forecast.Forecast.is_schedule_safe` · **Tested:**
`test_minimum_balance_is_never_violated_by_a_safe_payment`,
`test_multi_leg_schedule_accounts_for_cumulative_drain`

---

## 10. Amount safe to pay

```
amount_safe_to_pay = clamp(lowest_projected_balance − minimum_balance,
                           0, requested_amount)
```

Computed from the **base** forecast, before any spending changes, so it
describes raw capacity rather than capacity-after-sacrifice. Never negative,
never above the requested amount.

**Where:** `forecast.Forecast.amount_safe_to_pay` · **Tested:**
`test_amount_safe_to_pay_is_capped_at_requested_and_never_negative`

---

## 11. Earliest date for full payment

The first date `D` such that paying the full amount on `D` keeps every
checkpoint from `D` onward above the minimum, and the balance never breached
the minimum before `D` either. Returns nothing if no such date exists inside
the horizon.

The starting balance is included as a checkpoint, because paying on the
request date immediately exposes `balance0 − payment`.

**Where:** `forecast.Forecast.earliest_full_payment_date` · **Tested:**
`test_earliest_full_payment_date_is_request_date_when_already_safe`,
`test_delayed_payment_wait_only_offered_when_a_later_safe_date_exists`

---

## 12. Payment plans

Only methods in `payment_methods_user_will_consider` are generated.

**Partial payment** is exactly two legs: the safe-now amount, then the
remainder on the earliest safe date. Offered only when partial is allowed,
the safe amount is strictly between zero and the request, and the second leg
lands on or before the deadline.

**Installments** come from supplied options and must clear three gates:

1. the span must not exceed `max_installment_months`
2. the whole schedule must pass the 90-day safety check
3. the user must accept installments

Installment totals may exceed the requested amount by design — financing
fees are real costs, which is why total cost sits on the ranking ladder.

**Wait** is a single full payment at the earliest safe date, offered only
when that date differs from the request date.

**Where:** `payment_plans.build_candidates` · **Tested:**
`test_payment_plans.py`, `test_installment_plan_*`

---

## 13. Flexible spending reductions

Searched **only** when a plain full payment fails. An expense is eligible
only if all of the following hold:

- it is a future debit anchored to a real `event_id`
- its flexibility is `stoppable`, `reducible` or `reducible_or_stoppable`
- its category is **not** in `expense_categories_to_protect`
- the matching willingness list permits that specific action

Reduction targets `minimum_allowed_amount` when supplied, otherwise a
conservative 50% cut — reducing, not silently stopping.

Search: options ranked by money freed, top six considered, then combinations
of size 1, 2, 3 until one is safe. Capped at **three** changes.

> A recommendation the user won't follow is worthless. Asking someone to
> cancel six things is a plan on paper only. Cuts are a last resort, and the
> engine prefers a plan requiring none — rung 2 of the ranking ladder.

**Where:** `payment_plans.search_spending_changes_for_full_payment`
**Tested:** `test_spending_change_never_touches_protected_category`,
`test_reduce_respects_minimum_allowed_amount`

---

## 14. Ranking

Applied strictly in order:

| # | Criterion | Rationale |
|---|---|---|
| 1 | meets deadline | a plan that misses the deadline fails the goal |
| 2 | no spending changes | least disruption to the user's life |
| 3 | lowest total cost | avoid financing fees |
| 4 | earliest start | resolve sooner |
| 5 | fewest payments | less to manage |
| 6 | payment-option id | deterministic final tie-break |

**Where:** `payment_plans.Candidate.sort_key` · **Tested:**
`test_payment_plans.py`

---

## 15. Determinism

Same input, same output, always. No wall-clock reads (the request date is
"today"), no randomness, no network calls, no dict-ordering dependence —
every collection that feeds a decision is explicitly sorted, down to the
final tie-break on option id.

> A financial recommendation that changes between runs on identical data
> cannot be audited, and an unauditable recommendation cannot be trusted.

**Tested:** `test_pipeline_is_deterministic_across_runs`

---

## Known conservatism

These are deliberate choices, each biased toward under-promising:

- Pending credits ignored → understates available cash.
- Essential spend averaged from history → assumes recent habits persist.
- Recurring series projected at the **most recent** amount → a gradual
  upward drift in bills is not extrapolated.
- 90-day horizon → obligations beyond day 90 are invisible.
- No inflation, interest on savings, or tax modelling.
