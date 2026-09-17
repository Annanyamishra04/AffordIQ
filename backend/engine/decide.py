"""Turn a ranked Candidate (or its absence) into the exact output.csv row."""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from .data_loader import Profile, Request
from .forecast import Forecast
from .payment_plans import Candidate, SpendingChange, _fmt_amount


def _fmt_date(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _fmt_plan(payments) -> str:
    if not payments:
        return "none"
    return "|".join(f"{_fmt_date(d)}:{_fmt_amount(a)}" for d, a in payments)


def _fmt_changes(changes: List[SpendingChange]) -> str:
    if not changes:
        return "none"
    return "|".join(c.to_str() for c in changes[:3])


def build_row(req: Request, profile: Profile, base_forecast: Forecast,
              chosen: Optional[Candidate]) -> dict:
    requested_amount = req.requested_amount
    amount_safe_to_pay = base_forecast.amount_safe_to_pay(requested_amount)
    earliest_full = base_forecast.earliest_full_payment_date(requested_amount)
    currency = profile.home_currency
    min_keep = profile.minimum_balance_to_keep

    if chosen is None:
        return {
            "request_id": req.request_id,
            "amount_safe_to_pay": _fmt_amount(amount_safe_to_pay),
            "affordability_status": "not_affordable",
            "recommended_payment_method": "not_recommended",
            "payment_plan": "none",
            "earliest_date_for_full_payment": _fmt_date(earliest_full) if earliest_full else "",
            "spending_changes_needed": "none",
            "decision_explanation": (
                f"Do not proceed with the {currency} {_fmt_amount(requested_amount)} request. "
                f"None of the available, accepted payment options keeps the {currency} "
                f"{_fmt_amount(min_keep)} minimum balance protected within the 90-day forecast."
            ),
        }

    method = chosen.method
    if method == "full_payment" and not chosen.has_changes and chosen.payments[0][0] == req.request_date:
        status = "affordable_now"
    elif method == "wait":
        status = "affordable_later"
    else:
        status = "affordable_with_plan"

    explanation = _explain(req, profile, chosen, min_keep, currency)

    return {
        "request_id": req.request_id,
        "amount_safe_to_pay": _fmt_amount(amount_safe_to_pay),
        "affordability_status": status,
        "recommended_payment_method": method,
        "payment_plan": _fmt_plan(chosen.payments),
        "earliest_date_for_full_payment": _fmt_date(earliest_full) if earliest_full else "",
        "spending_changes_needed": _fmt_changes(chosen.changes),
        "decision_explanation": explanation,
    }


def _explain(req: Request, profile: Profile, c: Candidate, min_keep: float, currency: str) -> str:
    amt_str = lambda a: f"{currency} {_fmt_amount(a)}"
    if c.method == "full_payment":
        base = f"Pay {amt_str(c.payments[0][1])} on {_fmt_date(c.payments[0][0])}."
        if c.has_changes:
            change_txt = " and ".join(_describe_change(ch) for ch in c.changes)
            base = f"{change_txt.capitalize()}, then pay {amt_str(c.payments[0][1])} on {_fmt_date(c.payments[0][0])}."
        return f"{base} This leaves at least {amt_str(min_keep)} available over the next 90 days."
    if c.method == "wait":
        return (f"Pay {amt_str(c.payments[0][1])} in full on {_fmt_date(c.payments[0][0])}. "
                f"Paying earlier would take the balance below the {amt_str(min_keep)} minimum.")
    if c.method == "partial_payment":
        first, second = c.payments
        return (f"Pay {amt_str(first[1])} on {_fmt_date(first[0])} and the remaining {amt_str(second[1])} "
                f"on {_fmt_date(second[0])}. This completes the full request and keeps the "
                f"{amt_str(min_keep)} minimum protected.")
    if c.method == "installments":
        n = len(c.payments)
        amt = c.payments[0][1]
        start = _fmt_date(c.payments[0][0])
        return (f"Use {n} installments of {amt_str(amt)}, starting {start}. "
                f"This leaves at least {amt_str(min_keep)} available.")
    return "See payment plan."


def _describe_change(ch: SpendingChange) -> str:
    if ch.kind == "stop":
        return f"stop the flexible expense {ch.event_id}"
    return f"reduce {ch.event_id} to {_fmt_amount(ch.new_amount)}"
