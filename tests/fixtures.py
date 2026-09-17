"""Synthetic test fixtures. None of this data is derived from the private
challenge dataset -- everything here is invented for testing."""
import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(HERE, "..", "backend"))
sys.path.insert(0, BACKEND_DIR)

from engine.data_loader import Dataset, Event, Profile, Request  # noqa: E402


def make_dataset_from_demo():
    """Loads the bundled synthetic demo dataset (backend/demo_data)."""
    demo_dir = os.path.join(BACKEND_DIR, "demo_data")
    return Dataset(demo_dir)


def make_minimal_dataset(profile: Profile, events):
    """Builds an in-memory Dataset without touching disk, for isolated
    unit tests of specific engine behaviors."""
    ds = Dataset.__new__(Dataset)
    ds.dataset_dir = None
    ds.media_dir = None
    ds.profiles = {profile.user_id: profile}
    from collections import defaultdict
    ds.events_by_user = defaultdict(list)
    ds.events_by_id = {}
    for ev in events:
        ds.events_by_user[ev.user_id].append(ev)
        ds.events_by_id[ev.event_id] = ev
    for user_id, evs in ds.events_by_user.items():
        evs.sort(key=lambda e: (e.settlement_date or e.event_date or date.min))
    ds.exchange_rates = {
        ("2025-01-15", "EUR", "USD"): 1.08,
        ("2025-01-15", "USD", "EUR"): 0.9259,
    }
    ds.requests = {}
    ds.request_order = []
    from collections import defaultdict as dd
    ds.payment_options_by_request = dd(list)
    ds.messages_by_user = dd(list)
    ds.messages_by_request = dd(list)
    ds.messages_by_event = dd(list)
    ds.images_by_event = {}
    return ds


def make_profile(**overrides):
    defaults = dict(
        user_id="test_user",
        home_currency="USD",
        current_available_balance=2000.0,
        minimum_balance_to_keep=500.0,
        financial_priorities=["debt_repayment"],
        protect=["rent", "groceries"],
        willing_reduce=["dining"],
        willing_stop=["streaming"],
        payment_methods_user_will_consider=["full_payment", "installments", "partial_payment"],
        max_installment_months=6,
    )
    defaults.update(overrides)
    return Profile(**defaults)


def make_event(event_id, user_id, category, direction, amount, d, status="settled",
                event_type="expense", description=None, currency="USD",
                flexibility="fixed", minimum_allowed_amount=None, linked_event_id=None):
    return Event(
        event_id=event_id, user_id=user_id, event_type=event_type,
        description=description or f"{category} event", category=category, direction=direction,
        amount=amount, currency=currency, event_date=d, settlement_date=d, status=status,
        linked_event_id=linked_event_id, flexibility=flexibility,
        minimum_allowed_amount=minimum_allowed_amount,
    )


def make_request(user_id, requested_amount, request_date, desired_completion_date,
                  allows_partial_payment=True, request_id="test_req"):
    return Request(
        request_id=request_id, user_id=user_id, request_date=request_date,
        request_type="purchase", requested_amount=requested_amount,
        desired_completion_date=desired_completion_date,
        allows_partial_payment=allows_partial_payment, request_text="test",
    )
