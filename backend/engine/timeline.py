"""
Reconstruct a user's forward cash-flow timeline from their historical and
scheduled/pending financial_events, in the user's home currency.

Design (see docs/financial-logic.md for the full rationale):

* Historical `settled` events (settlement_date <= request_date) are used only
  to (a) detect recurring series and their cadence/amount, and (b) compute a
  conservative average burn rate for variable essential spending. They are
  NOT re-summed into the balance -- `current_available_balance` on the
  profile already reflects the user's position at `request_date`.
* Explicit future rows (status `scheduled` or `pending`, settlement_date >
  request_date) are included as one-off cash-flow entries: debits always
  (pending debits are reserved), credits only when `scheduled` (a stated,
  dated commitment) -- pending credits, bonuses, commissions, refunds,
  windfalls and unrealized investment values are excluded until settled,
  per the problem statement.
* `cancelled` / `failed` rows and `non_cash` (unrealized) rows are always
  excluded.
* Recurring categories (rent, utilities, education, debt_repayment, salary,
  insurance, housing, family_support, and the flexible subscription-style
  categories) are projected forward at their detected cadence using the
  most recent historical amount, honouring any message-derived salary/rent
  adjustment from its effective date onward.
* Variable essential categories (groceries, transport, dining, healthcare,
  shopping, work_expense) are forecast conservatively as a monthly synthetic
  debit equal to the recent historical monthly average for that category.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Dict, List, Optional

from .data_loader import Dataset, Event
from .messages import SalaryAdjustment, RentAdjustment, EventNote

RECURRING_CATEGORIES = {
    "rent", "utilities", "education", "debt_repayment", "salary", "insurance",
    "housing", "family_support", "music_subscription", "delivery_membership",
    "cloud_storage", "streaming", "gym", "entertainment",
}
VARIABLE_ESSENTIAL_CATEGORIES = {
    "groceries", "transport", "dining", "healthcare", "shopping", "work_expense",
}
NEVER_PROJECT_CATEGORIES = {"investment", "windfall"}


@dataclass
class CashFlowItem:
    dt: date
    delta: float  # signed: +credit, -debit
    category: str
    description: str
    event_id: Optional[str]  # real event_id this is anchored to (for spending changes), or None
    flexibility: str
    is_projected: bool
    minimum_allowed_amount: Optional[float] = None


def _home_amount(ds: Dataset, ev: Event, home_currency: str) -> float:
    on_date = ev.settlement_date or ev.event_date
    return ds.convert(ev.amount, ev.currency, home_currency, on_date)


def _signed(ev: Event, amount_home: float) -> float:
    if ev.direction == "credit":
        return amount_home
    if ev.direction == "debit":
        return -amount_home
    return 0.0  # non_cash


def _series_key(ev: Event):
    if ev.category == "salary":
        # Salary descriptions legitimately vary across the same recurring
        # income stream (e.g. "Prorated first salary credit" ->
        # "Next confirmed salary credit" -> plain "Salary credit"), so group
        # by category alone rather than by the exact description text.
        return (ev.category,)
    return (ev.category, ev.description)


def _detect_cadence_days(dates: List[date]) -> Optional[int]:
    if len(dates) < 2:
        return None
    gaps = [(dates[i] - dates[i - 1]).days for i in range(1, len(dates))]
    gaps = [g for g in gaps if g > 0]
    if not gaps:
        return None
    m = median(gaps)
    return int(round(m))


def _add_calendar_months(d: date, n: int) -> date:
    """Advance `d` by `n` calendar months, preserving day-of-month (clamped
    to the last valid day of the target month). Used for monthly billing /
    payroll cycles (e.g. rent or salary always on the 15th) so that the
    projected date does not drift the way naive fixed day-count stepping
    would across months of different lengths."""
    month_index = d.month - 1 + n
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def build_timeline(
    ds: Dataset,
    user_id: str,
    request_date: date,
    horizon_days: int,
    salary_adjustments: List[SalaryAdjustment],
    rent_adjustments: List[RentAdjustment],
    event_notes: Dict[str, EventNote],
) -> List[CashFlowItem]:
    profile = ds.profiles[user_id]
    home_currency = profile.home_currency
    horizon_end = request_date + timedelta(days=horizon_days)
    events = ds.events_by_user.get(user_id, [])

    items: List[CashFlowItem] = []

    # ---- 1. explicit future one-off rows ------------------------------
    excluded_linked_ids = set()
    for ev in events:
        note = event_notes.get(ev.event_id)
        if note and note.is_internal_transfer:
            excluded_linked_ids.add(ev.event_id)
            if ev.linked_event_id:
                excluded_linked_ids.add(ev.linked_event_id)

    for ev in events:
        sdate = ev.settlement_date or ev.event_date
        if sdate is None or sdate <= request_date or sdate > horizon_end:
            continue
        if ev.status in ("cancelled", "failed"):
            continue
        if ev.direction == "non_cash":
            continue
        if ev.event_id in excluded_linked_ids:
            continue
        note = event_notes.get(ev.event_id)
        if note and note.is_pending_or_unsettled:
            continue
        if ev.direction == "credit" and ev.status not in ("scheduled", "settled"):
            # pending / unrealized future credits are not counted until settled
            continue
        amt_home = _home_amount(ds, ev, home_currency)
        items.append(CashFlowItem(
            dt=sdate, delta=_signed(ev, amt_home), category=ev.category,
            description=ev.description, event_id=ev.event_id,
            flexibility=ev.flexibility, is_projected=False,
            minimum_allowed_amount=ev.minimum_allowed_amount,
        ))

    # ---- 2. recurring series projected forward -------------------------
    historical = [e for e in events
                  if (e.settlement_date or e.event_date) and (e.settlement_date or e.event_date) <= request_date
                  and e.status == "settled" and e.direction in ("credit", "debit")]

    # Cadence/anchor detection also considers explicitly *scheduled* future
    # occurrences (e.g. a "Next confirmed salary credit" row) in addition to
    # settled history -- a new-job user may have only one settled salary
    # event plus one scheduled one, and salary should still be projected to
    # recur monthly after that scheduled date, not stop there. `pending`
    # future rows are excluded from series detection since they are
    # typically one-off items (an outstanding arrears balance, an
    # unconfirmed charge) rather than part of a steady cadence.
    series_basis = [e for e in events
                     if (e.settlement_date or e.event_date)
                     and (e.settlement_date or e.event_date) <= horizon_end
                     and e.status in ("settled", "scheduled")
                     and e.direction in ("credit", "debit")]

    series: Dict[tuple, List[Event]] = {}
    for ev in series_basis:
        if ev.category in NEVER_PROJECT_CATEGORIES:
            continue
        if ev.category not in RECURRING_CATEGORIES:
            continue
        series.setdefault(_series_key(ev), []).append(ev)

    salary_by_user = [a for a in salary_adjustments if a.user_id == user_id]
    rent_by_user = [a for a in rent_adjustments if a.user_id == user_id]
    salary_ended = any(a.kind == "ended" for a in salary_by_user)
    salary_overrides = sorted(
        [a for a in salary_by_user if a.kind == "override" and a.new_amount is not None],
        key=lambda a: a.effective_date or date.min)
    rent_pct = sum(a.percent_change for a in rent_by_user)

    for key, evs in series.items():
        category = key[0]
        description = key[1] if len(key) > 1 else evs[-1].description
        evs.sort(key=lambda e: e.settlement_date or e.event_date)
        dates = [e.settlement_date or e.event_date for e in evs]
        cadence = _detect_cadence_days(dates)
        last_ev = evs[-1]
        last_date = dates[-1]
        base_amount_home = _home_amount(ds, last_ev, home_currency)

        if cadence is None or cadence < 6:
            # Not enough history / not clearly periodic (e.g. a single
            # occurrence) -- do not fabricate a recurrence that isn't
            # supported by history.
            continue

        if category == "salary" and salary_ended:
            continue

        use_calendar_months = 25 <= cadence <= 35
        month_step = 0
        next_date = last_date + timedelta(days=cadence)
        if use_calendar_months:
            month_step = 1
            next_date = _add_calendar_months(last_date, month_step)

        while next_date <= horizon_end:
            amount_home = base_amount_home
            evt_ref = last_ev.event_id
            if category == "salary" and salary_overrides:
                applicable = [a for a in salary_overrides if a.effective_date and a.effective_date <= next_date]
                if applicable:
                    adj = applicable[-1]
                    amount_home = ds.convert(adj.new_amount, adj.currency or home_currency, home_currency, next_date)
            if category == "rent" and rent_pct:
                amount_home = base_amount_home * (1 + rent_pct / 100.0)
            if next_date > request_date:
                items.append(CashFlowItem(
                    dt=next_date,
                    delta=amount_home if last_ev.direction == "credit" else -amount_home,
                    category=category, description=description,
                    event_id=evt_ref, flexibility=last_ev.flexibility,
                    is_projected=True,
                    minimum_allowed_amount=last_ev.minimum_allowed_amount,
                ))
            if use_calendar_months:
                month_step += 1
                next_date = _add_calendar_months(last_date, month_step)
            else:
                next_date = next_date + timedelta(days=cadence)

    # ---- 3. variable essential spending (conservative monthly average) --
    lookback_start = request_date - timedelta(days=90)
    for category in VARIABLE_ESSENTIAL_CATEGORIES:
        cat_events = [e for e in historical if e.category == category
                      and (e.settlement_date or e.event_date) >= lookback_start]
        if not cat_events:
            cat_events = [e for e in historical if e.category == category]
        if not cat_events:
            continue
        total_home = sum(_home_amount(ds, e, home_currency) for e in cat_events)
        span_days = max(1, (request_date - min(e.settlement_date or e.event_date for e in cat_events)).days)
        daily_avg = total_home / span_days
        if daily_avg <= 0:
            continue
        # Spread the conservative average as a continuous daily debit rather
        # than one monthly lump -- a lump under-states how low the balance
        # gets mid-month, since in reality groceries/transport/etc. are paid
        # for continuously through the month.
        cursor = request_date + timedelta(days=1)
        while cursor <= horizon_end:
            items.append(CashFlowItem(
                dt=cursor, delta=-daily_avg, category=category,
                description=f"Forecast essential spending: {category}",
                event_id=None, flexibility="fixed", is_projected=True,
            ))
            cursor += timedelta(days=1)

    items.sort(key=lambda it: it.dt)
    return items
