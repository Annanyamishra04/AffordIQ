"""Generate and rank candidate payment plans for a single request."""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import combinations
from typing import Dict, List, Optional, Tuple

from .data_loader import Dataset, PaymentOption, Profile, Request
from .forecast import Forecast, build_forecast
from .timeline import CashFlowItem

FLEXIBLE_KINDS = ("stoppable", "reducible", "reducible_or_stoppable")


@dataclass
class SpendingChange:
    kind: str  # "stop" or "reduce_to"
    event_id: str
    new_amount: Optional[float] = None
    freed_amount: float = 0.0

    def to_str(self) -> str:
        if self.kind == "stop":
            return f"stop:{self.event_id}"
        return f"reduce_to:{self.event_id}:{_fmt_amount(self.new_amount)}"


@dataclass
class Candidate:
    method: str  # full_payment | partial_payment | installments | wait
    payments: List[Tuple[date, float]]
    changes: List[SpendingChange]
    payment_option_id: Optional[str] = None
    meets_deadline: bool = True

    @property
    def total_paid(self) -> float:
        return round(sum(a for _, a in self.payments), 2)

    @property
    def first_date(self) -> date:
        return min(d for d, _ in self.payments) if self.payments else date.max

    @property
    def num_payments(self) -> int:
        return len(self.payments)

    @property
    def has_changes(self) -> bool:
        return len(self.changes) > 0

    def sort_key(self):
        opt_id = self.payment_option_id or ""
        return (
            0 if self.meets_deadline else 1,
            1 if self.has_changes else 0,
            self.total_paid,
            self.first_date,
            self.num_payments,
            opt_id,
        )


def _fmt_amount(x: float) -> str:
    if x is None:
        return "0"
    if abs(x - round(x)) < 1e-9:
        return str(int(round(x)))
    return f"{x:.2f}".rstrip("0").rstrip(".")


def _gather_flexible_groups(items: List[CashFlowItem], profile: Profile) -> Dict[str, dict]:
    groups: Dict[str, dict] = {}
    for it in items:
        if it.delta >= 0 or it.event_id is None:
            continue
        if it.flexibility not in FLEXIBLE_KINDS:
            continue
        if it.category in profile.protect:
            continue
        can_stop = it.flexibility in ("stoppable", "reducible_or_stoppable") and it.category in profile.willing_stop
        can_reduce = it.flexibility in ("reducible", "reducible_or_stoppable") and it.category in profile.willing_reduce
        if not (can_stop or can_reduce):
            continue
        g = groups.setdefault(it.event_id, {
            "items": [], "can_stop": can_stop, "can_reduce": can_reduce,
            "min_allowed": it.minimum_allowed_amount, "category": it.category,
        })
        g["items"].append(it)
        if it.minimum_allowed_amount is not None:
            g["min_allowed"] = it.minimum_allowed_amount
    return groups


def _build_change_options(groups: Dict[str, dict]) -> List[SpendingChange]:
    options: List[SpendingChange] = []
    for event_id, g in groups.items():
        magnitude = sum(abs(it.delta) for it in g["items"])
        if g["can_stop"]:
            options.append(SpendingChange(kind="stop", event_id=event_id, freed_amount=magnitude))
        if g["can_reduce"]:
            new_amount = g["min_allowed"] if g["min_allowed"] is not None else None
            per_item_new = new_amount if new_amount is not None else None
            if per_item_new is None:
                # No explicit floor supplied: use a conservative 50% cut as the
                # reduced target rather than stopping the category entirely.
                sample_amt = abs(g["items"][0].delta)
                per_item_new = round(sample_amt * 0.5, 2)
            freed = sum(max(0.0, abs(it.delta) - per_item_new) for it in g["items"])
            if freed > 0:
                options.append(SpendingChange(kind="reduce_to", event_id=event_id,
                                               new_amount=per_item_new, freed_amount=freed))
    options.sort(key=lambda o: -o.freed_amount)
    return options


def _apply_changes_to_items(items: List[CashFlowItem], changes: List[SpendingChange]) -> List[CashFlowItem]:
    stop_ids = {c.event_id for c in changes if c.kind == "stop"}
    reduce_map = {c.event_id: c.new_amount for c in changes if c.kind == "reduce_to"}
    out = []
    for it in items:
        if it.event_id in stop_ids and it.delta < 0:
            continue
        if it.event_id in reduce_map and it.delta < 0:
            new_it = copy.copy(it)
            new_it.delta = -reduce_map[it.event_id]
            out.append(new_it)
            continue
        out.append(it)
    return out


def search_spending_changes_for_full_payment(
    items: List[CashFlowItem], profile: Profile, balance0: float, min_keep: float,
    request_date: date, horizon_days: int, requested_amount: float, max_changes: int = 3,
) -> Optional[List[SpendingChange]]:
    """Try to find up to `max_changes` flexible spending changes that make a
    full payment safe today. Greedy by impact, then a small combinatorial
    search over the top candidates for a minimal valid set."""
    groups = _gather_flexible_groups(items, profile)
    options = _build_change_options(groups)
    if not options:
        return None

    def is_safe(chs: List[SpendingChange]) -> bool:
        modified = _apply_changes_to_items(items, chs)
        fc = build_forecast(balance0, min_keep, request_date, horizon_days, modified)
        return fc.is_schedule_safe([(request_date, requested_amount)])

    top = options[:6]
    for r in range(1, max_changes + 1):
        for combo in combinations(top, r):
            combo = list(combo)
            event_ids = {c.event_id for c in combo}
            if len(event_ids) != len(combo):
                continue
            if is_safe(combo):
                return combo
    return None


def build_candidates(
    ds: Dataset, req: Request, profile: Profile, items: List[CashFlowItem],
    base_forecast: Forecast, horizon_days: int,
) -> List[Candidate]:
    candidates: List[Candidate] = []
    accepted = set(profile.payment_methods_user_will_consider)
    request_date = req.request_date
    requested_amount = req.requested_amount
    deadline = req.desired_completion_date

    # 1. full_payment today, no changes
    if "full_payment" in accepted:
        if base_forecast.is_schedule_safe([(request_date, requested_amount)]):
            candidates.append(Candidate(
                method="full_payment", payments=[(request_date, requested_amount)],
                changes=[], meets_deadline=(request_date <= deadline),
            ))
        else:
            # 2. full_payment today, WITH spending changes
            changes = search_spending_changes_for_full_payment(
                items, profile, base_forecast.balance0, base_forecast.min_keep,
                request_date, horizon_days, requested_amount,
            )
            if changes:
                candidates.append(Candidate(
                    method="full_payment", payments=[(request_date, requested_amount)],
                    changes=changes, meets_deadline=(request_date <= deadline),
                ))

    # 3. installments (per supplied payment option)
    if "installments" in accepted and profile.max_installment_months:
        for opt in ds.payment_options_by_request.get(req.request_id, []):
            if opt.payment_method != "installments":
                continue
            payments = []
            d = opt.first_payment_date
            for i in range(opt.number_of_payments):
                payments.append((d, opt.payment_amount))
                if opt.payment_frequency_days:
                    d = d + timedelta(days=opt.payment_frequency_days)
            last_date = payments[-1][0]
            duration_months = (last_date - opt.first_payment_date).days / 30.44
            if duration_months > profile.max_installment_months + 1e-6:
                continue
            if not base_forecast.is_schedule_safe(payments):
                continue
            candidates.append(Candidate(
                method="installments", payments=payments, changes=[],
                payment_option_id=opt.payment_option_id,
                meets_deadline=(last_date <= deadline),
            ))

    # 4. partial_payment (exactly two payments, per spec)
    if (req.allows_partial_payment and "partial_payment" in accepted):
        amt_safe = base_forecast.amount_safe_to_pay(requested_amount)
        earliest = base_forecast.earliest_full_payment_date(requested_amount)
        if 0 < amt_safe < requested_amount and earliest is not None and earliest <= deadline:
            remaining = round(requested_amount - amt_safe, 2)
            payments = [(request_date, amt_safe), (earliest, remaining)]
            if base_forecast.is_schedule_safe(payments):
                candidates.append(Candidate(
                    method="partial_payment", payments=payments, changes=[],
                    meets_deadline=True,
                ))

    # 5. wait (full payment later, no changes)
    if "full_payment" in accepted:
        earliest = base_forecast.earliest_full_payment_date(requested_amount)
        if earliest is not None and earliest != request_date:
            candidates.append(Candidate(
                method="wait", payments=[(earliest, requested_amount)], changes=[],
                meets_deadline=(earliest <= deadline),
            ))

    return candidates


def changes_for_category_actions(
    items: List[CashFlowItem], profile: Profile, category_actions: Dict[str, str],
) -> List[SpendingChange]:
    """Translate user-facing category choices (e.g. {"dining": "reduce",
    "streaming": "stop"}) into concrete, event-anchored SpendingChange
    objects, using the exact same eligibility rules as the automatic search
    (`_gather_flexible_groups` / `_build_change_options`): the category must
    not be protected, and the requested action must be one the user has
    actually said they're willing to take for that category.

    A category with no matching flexible items, or a requested action the
    profile doesn't allow for it, simply yields no changes for that
    category -- it is not an error, since the caller (the /api/what-if
    endpoint) cannot know in advance which categories exist in a given
    user's timeline.
    """
    groups = _gather_flexible_groups(items, profile)
    options = _build_change_options(groups)
    wanted_kind = {"stop": "stop", "reduce": "reduce_to"}
    selected: List[SpendingChange] = []
    for opt in options:
        group = groups.get(opt.event_id)
        if group is None:
            continue
        action = category_actions.get(group["category"])
        if action and wanted_kind.get(action) == opt.kind:
            selected.append(opt)
    return selected


def rank_candidates(candidates: List[Candidate]) -> Optional[Candidate]:
    if not candidates:
        return None
    candidates = sorted(candidates, key=lambda c: c.sort_key())
    return candidates[0]
