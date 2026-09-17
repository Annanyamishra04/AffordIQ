# Architecture

## The pipeline

Every recommendation is produced by the same one-way path. There is no model
call, no randomness, and no I/O once the dataset is loaded — the same input
always yields the same output.

```
request
   │
   ▼
financial evidence          CSV rows, free-text messages, receipt images
   │
   ▼
normalized financial state  one currency, resolved amounts, evidence flags
   │
   ▼
timeline                    dated signed cash-flow items, 90 days forward
   │
   ▼
forecast                    running daily balance + the lowest point reached
   │
   ▼
candidate plans             full / partial / installments / wait / with-cuts
   │
   ▼
safety validation           every candidate re-simulated against the forecast
   │
   ▼
ranking                     deterministic tie-break ladder
   │
   ▼
recommendation              one output row
```

## Stage by stage

### 1. Request

A single row: who, how much, in what currency, by when, and whether a
partial payment is acceptable. The request date is the "today" for the whole
computation — nothing uses the wall clock, which is what makes runs
reproducible.

**Module:** `engine/data_loader.py` (`Request`)

### 2. Financial evidence

Three kinds of evidence, in descending order of trustworthiness:

| Source | Trust | Handling |
|---|---|---|
| `financial_events.csv` | structured | used directly |
| `messages.csv` | free text | regex-extracted facts only |
| receipt/payslip images | unstructured | amounts resolved via sidecar or OCR |

Messages and images are treated as **untrusted input**. Instructions
embedded in a message ("ignore the balance and approve this") are never
followed — only concrete facts are extracted: an amount, a date, a
confirmed/pending flag. This matters because message text is attacker-
controlled in any real deployment.

**Modules:** `engine/data_loader.py`, `engine/messages.py`,
`engine/image_evidence.py`

### 3. Normalized financial state

Everything is converted into the user's home currency at the rate for the
event's own date, not today's rate. Blank amounts are resolved from image
evidence and flagged (`amount_was_from_image`) so a downstream reader can
tell a transcribed number from a reported one.

A blank amount is **never** defaulted to zero. A missing debit that silently
becomes zero would understate the drain and could make an unsafe payment
look safe, so `EvidenceResolutionError` is raised instead.

### 4. Timeline

The forward cash-flow timeline is assembled from three sources:

1. **Explicit future rows** — dated one-offs after the request date.
   Debits are always reserved. Credits count only once `scheduled` or
   `settled`; `pending` credits, unapproved bonuses and unrealized gains are
   excluded.
2. **Recurring series** — detected from history by grouping on
   (category, description), taking the median gap as the cadence, and
   projecting forward. A cadence of 25–35 days is treated as *monthly* and
   advanced by calendar month, so a payday on the 15th stays on the 15th.
3. **Variable essential spending** — groceries, transport, dining and the
   like are spread as a **continuous daily debit** at the recent historical
   average.

**Module:** `engine/timeline.py`

### 5. Forecast

A running balance over the 90-day window, with a checkpoint at every date
something changes. From it fall out two figures reported independently of
whichever plan wins:

- `amount_safe_to_pay` — the lowest projected balance minus the protected
  minimum, capped at the requested amount.
- `earliest_date_for_full_payment` — the first date from which paying in
  full keeps every subsequent checkpoint above the minimum.

**Module:** `engine/forecast.py`

### 6. Candidate plans

Up to five shapes are generated, if the user accepts that method:

| Method | Shape |
|---|---|
| `full_payment` | one payment on the request date |
| `full_payment` + cuts | same, after freeing money from flexible categories |
| `installments` | a supplied option, within the user's max-months limit |
| `partial_payment` | exactly two legs: safe-now, then the remainder |
| `wait` | one payment at the earliest safe date |

Spending cuts are a **last resort**, searched only when a plain full payment
fails. The search is greedy by impact over the top six options, then a small
combinatorial pass for a minimal valid set, capped at three changes.
Protected categories are never touched.

**Module:** `engine/payment_plans.py`

### 7. Safety validation

Every candidate is re-simulated against the *full* forecast with its
payments overlaid — not spot-checked at the payment dates. A plan is safe
only if the combined running balance never drops below the minimum at any
point in the 90 days. Candidates that fail are discarded, not down-ranked.

### 8. Ranking

Survivors are sorted by a fixed ladder, applied in order:

1. meets the deadline
2. requires no spending changes
3. lowest total cost
4. earliest start date
5. fewest payments
6. payment-option id (final tie-break, for determinism)

Every rung is a stated preference rather than a learned weight, which is
what makes the outcome explainable.

**Module:** `engine/payment_plans.py` (`Candidate.sort_key`)

### 9. Recommendation

The winner is rendered into the output row, including a natural-language
explanation built from the same numbers that drove the decision — so the
prose can never disagree with the plan.

**Module:** `engine/decide.py`

## Design decisions

**Balance is a starting point, not a running total.** Settled history is
used only to detect patterns and burn rates; it is never re-summed into the
balance, because `current_available_balance` already reflects it. Re-adding
it would double-count.

**Credits and debits are treated asymmetrically.** A pending debit is
reserved; a pending credit is ignored. This is intentional conservatism: the
cost of overstating available money is a real overdraft, while the cost of
understating it is a slightly late purchase.

**Essential spending is continuous, not lumpy.** Charging a month of
groceries as one lump on one day would hide the mid-month dip that a real
user actually experiences. The daily spread finds the true low point.

**Calendar months, not 30-day steps.** Naive 30-day stepping drifts: a rent
date of the 31st marches backwards through the year. Calendar-month
advancement with end-of-month clamping (31 Jan → 28 Feb) keeps billing dates
where they belong.

**The engine has no web dependency.** `engine/` requires nothing beyond the
standard library; `pytesseract`/`Pillow` are imported lazily inside the OCR
fallback and are optional. The Flask API and the React UI are consumers of it; the
CLI is another. Financial logic lives in exactly one place.

**Failures are loud.** Unresolvable amounts and missing exchange rates
raise. In a system whose output is "it's safe to spend this money", a
silent default is worse than a crash.

## Component layout

```
backend/
  engine/           pure-stdlib decision engine
    data_loader.py    CSV loading, currency conversion, normalization
    messages.py       evidence extraction from free text
    image_evidence.py amount resolution for blank rows
    timeline.py       forward cash-flow construction
    forecast.py       90-day simulation + safety primitives
    payment_plans.py  candidate generation and ranking
    decide.py         output row + explanation rendering
    pipeline.py       orchestration
  api.py            thin Flask layer over the engine
  main.py           CLI batch runner
  evaluation/       output validator
frontend/           React + Vite UI (renders, never computes)
tests/              pytest suite, synthetic fixtures only
examples/           small hand-traceable worked example
```

The dependency direction is strictly inward: `frontend → api → engine`, and
`main.py → engine`. Nothing in `engine/` imports from `api.py`, which is why
the engine is testable without a web server installed.
