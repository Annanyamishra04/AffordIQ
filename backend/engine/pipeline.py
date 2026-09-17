"""Orchestrates the full per-request decision pipeline."""
from __future__ import annotations

from typing import List

from .data_loader import Dataset, Request
from .decide import build_row
from .forecast import build_forecast
from .messages import parse_event_notes, parse_rent_adjustments, parse_salary_adjustments
from .payment_plans import SpendingChange, _apply_changes_to_items, build_candidates, rank_candidates
from .timeline import build_timeline

HORIZON_DAYS = 90


class Pipeline:
    def __init__(self, ds: Dataset):
        self.ds = ds
        all_messages = [m for msgs in ds.messages_by_user.values() for m in msgs]
        self.salary_adjustments = parse_salary_adjustments(all_messages)
        self.rent_adjustments = parse_rent_adjustments(all_messages)
        self.event_notes = parse_event_notes(ds.messages_by_event)

    def build_items(self, req: Request):
        """The forward cash-flow timeline for `req.user_id` as of
        `req.request_date`, with no spending changes applied. Exposed so
        callers (e.g. the /api/what-if endpoint) can derive eligible
        flexible-spending options without duplicating timeline logic."""
        return build_timeline(
            self.ds, req.user_id, req.request_date, HORIZON_DAYS,
            self.salary_adjustments, self.rent_adjustments, self.event_notes,
        )

    def process(self, req: Request) -> dict:
        profile = self.ds.profiles[req.user_id]
        items = self.build_items(req)
        base_forecast = build_forecast(
            profile.current_available_balance, profile.minimum_balance_to_keep,
            req.request_date, HORIZON_DAYS, items,
        )
        candidates = build_candidates(self.ds, req, profile, items, base_forecast, HORIZON_DAYS)
        chosen = rank_candidates(candidates)
        return build_row(req, profile, base_forecast, chosen)

    def process_with_forced_changes(self, req: Request, forced_changes: List[SpendingChange]) -> dict:
        """Recompute the full decision as if `forced_changes` had already
        been applied -- the engine primitive behind "what if I made these
        spending changes?" scenarios. This is not a parallel decision
        algorithm: it runs the exact same `build_timeline` -> apply changes
        -> `build_forecast` -> `build_candidates` -> `rank_candidates` ->
        `build_row` path as `process()`, just with the flexible-spending
        events already adjusted before the forecast is built. Any further
        changes the ranked candidate needed on top of the forced ones (the
        automatic search still runs if a plain full payment isn't safe) are
        merged in behind the forced changes so the explanation accounts for
        everything actually applied.
        """
        profile = self.ds.profiles[req.user_id]
        items = self.build_items(req)
        modified_items = _apply_changes_to_items(items, forced_changes) if forced_changes else items
        base_forecast = build_forecast(
            profile.current_available_balance, profile.minimum_balance_to_keep,
            req.request_date, HORIZON_DAYS, modified_items,
        )
        candidates = build_candidates(self.ds, req, profile, modified_items, base_forecast, HORIZON_DAYS)
        chosen = rank_candidates(candidates)
        if chosen is not None and forced_changes:
            already = {c.event_id for c in forced_changes}
            extra = [c for c in chosen.changes if c.event_id not in already]
            chosen.changes = list(forced_changes) + extra
        return build_row(req, profile, base_forecast, chosen)

    def process_all(self, requests: List[Request]) -> List[dict]:
        return [self.process(r) for r in requests]
