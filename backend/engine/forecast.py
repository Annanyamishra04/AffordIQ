"""90-day safety-check simulation on top of a CashFlowItem timeline."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional, Tuple

from .timeline import CashFlowItem


def _round2(x: float) -> float:
    return round(x + 1e-9, 2)


@dataclass
class Forecast:
    balance0: float
    min_keep: float
    request_date: date
    horizon_end: date
    trace: List[Tuple[date, float]]  # (date, running balance after that date's net items)

    def base_min_balance(self) -> float:
        vals = [self.balance0] + [b for _, b in self.trace]
        return min(vals)

    def amount_safe_to_pay(self, requested_amount: float) -> float:
        safe = self.base_min_balance() - self.min_keep
        return _round2(max(0.0, min(safe, requested_amount)))

    def earliest_full_payment_date(self, requested_amount: float) -> Optional[date]:
        # candidate breakpoints: request_date, and every date strictly after
        # it that appears in the trace (balance only changes at those points)
        dates = [self.request_date] + [d for d, _ in self.trace if d > self.request_date]
        dates = sorted(set(dates))
        # Full checkpoint sequence including the starting balance itself --
        # paying on `request_date` immediately exposes balance0 - payment,
        # so balance0 must be part of the "on or after D" window whenever D
        # is at or before the first trace date, not just the later trace
        # values.
        checkpoints = [(self.request_date, self.balance0)] + [(d, b) for d, b in self.trace if d > self.request_date]
        for D in dates:
            pre_vals = [b for d, b in checkpoints if d < D] or [self.balance0]
            pre_ok = min(pre_vals) >= self.min_keep
            suffix_vals = [b for d, b in checkpoints if d >= D]
            if not suffix_vals:
                suffix_vals = [self.balance0]
            suffix_min = min(suffix_vals)
            if pre_ok and (suffix_min - requested_amount) >= self.min_keep - 1e-6:
                return D
        return None

    def is_schedule_safe(self, payments: List[Tuple[date, float]]) -> bool:
        for d, _ in payments:
            if d < self.request_date or d > self.horizon_end:
                return False
        # `trace` is cumulative, so recover the per-date net delta of the
        # base timeline, then overlay the payments as extra debits and walk
        # the combined series once.
        base_delta = {}
        cum_prev = self.balance0
        for d, b in self.trace:
            base_delta[d] = b - cum_prev
            cum_prev = b

        deltas_by_date = defaultdict(float)
        for d, delta in base_delta.items():
            deltas_by_date[d] += delta
        for d, amt in payments:
            deltas_by_date[d] -= amt

        all_dates = sorted(deltas_by_date.keys())
        running = self.balance0
        min_seen = self.balance0
        for d in all_dates:
            running += deltas_by_date[d]
            min_seen = min(min_seen, running)
        return min_seen >= self.min_keep - 1e-6


def build_forecast(balance0: float, min_keep: float, request_date: date,
                    horizon_days: int, items: List[CashFlowItem]) -> Forecast:
    horizon_end = request_date + timedelta(days=horizon_days)
    by_date = defaultdict(float)
    for it in items:
        if request_date < it.dt <= horizon_end:
            by_date[it.dt] += it.delta
    dates = sorted(by_date.keys())
    trace = []
    running = balance0
    for d in dates:
        running += by_date[d]
        trace.append((d, running))
    return Forecast(balance0=balance0, min_keep=min_keep, request_date=request_date,
                     horizon_end=horizon_end, trace=trace)
