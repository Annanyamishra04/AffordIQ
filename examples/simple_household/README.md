# Worked example — `simple_household`

A deliberately tiny, fully synthetic dataset (one user, 15 events) that you
can trace by hand. Nothing here comes from any private dataset.

## Run it

```bash
python3 backend/main.py \
  --dataset-dir examples/simple_household \
  --requests examples/simple_household/requests.csv \
  --out /tmp/example_output.csv

python3 backend/evaluation/main.py \
  --dataset-dir examples/simple_household \
  --output /tmp/example_output.csv
```

The committed `expected_output.csv` is what the engine produces today.

## The profile

Priya banks in INR, holds **48,000** available, and never wants to drop
below **15,000**. She'll consider full, partial and installment payments,
protects rent and groceries, and is willing to stop streaming.

## The events

| What | Cadence | Amount |
|---|---|---|
| Salary | monthly, 28th | 62,000 credit |
| Rent | monthly, 5th | 22,000 debit |
| Streaming | monthly, 12th | 650 debit (stoppable) |
| Groceries | weekly-ish | ~3,250 debit |
| Health insurance | one-off, 22 Jan | 4,800 debit (scheduled) |
| Marketplace refund | one-off, 20 Jan | 5,500 credit (**pending**) |

## The request

A **25,000** refrigerator on **2025-01-15**, partial payment allowed,
wanted by 2025-02-28.

## The answer

```
amount_safe_to_pay              21960
affordability_status            affordable_with_plan
recommended_payment_method      partial_payment
payment_plan                    2025-01-15:21960|2025-01-28:3040
earliest_date_for_full_payment  2025-01-28
```

## Why this example is worth reading

Four behaviours show up in this one row:

1. **The balance alone would say yes.** 48,000 is far more than 25,000. The
   engine says *not in full today* — because rent on the 5th, insurance on
   the 22nd and continuous grocery spend all land inside the window.

2. **The pending refund is ignored.** That 5,500 credit is `pending`, and a
   linked message confirms it hasn't been credited. Counting it would have
   raised `amount_safe_to_pay`. Credits count only once confirmed; debits
   are reserved as soon as they're known. The asymmetry is deliberate.

3. **The second leg lands on payday.** `2025-01-28` isn't a round number of
   days out — it's the first date the forecast shows enough headroom, which
   happens to be when salary arrives. The date is derived, not chosen.

4. **No spending changes were needed.** Streaming is stoppable and Priya is
   willing to stop it, but a safe plan exists without it, so the engine
   doesn't ask her to give anything up. Cuts are a last resort, not a
   default.

## Try changing something

- Set `ev_ref_1` status to `settled` (and drop the "still pending" message)
  → the refund now counts and the answer flips all the way to
  `affordable_now / full_payment / 2025-01-15:25000`. One evidence flag
  changes the entire recommendation.
- Raise `minimum_balance_to_keep` to 40,000 → watch it fall back to `wait`
  or `not_affordable`.
- Set `allows_partial_payment` to `false` → partial disappears and the
  engine must find a different route.
