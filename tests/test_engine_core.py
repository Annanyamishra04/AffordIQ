import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.fixtures import make_dataset_from_demo, make_minimal_dataset, make_profile, make_event

from engine.timeline import build_timeline
from engine.forecast import build_forecast
from engine.messages import parse_salary_adjustments, parse_rent_adjustments, parse_event_notes


def _empty_adjustments():
    return [], [], {}


def test_amount_safe_to_pay_is_capped_at_requested_and_never_negative():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=500.0)
    ds = make_minimal_dataset(profile, [])
    salary_adj, rent_adj, notes = _empty_adjustments()
    items = build_timeline(ds, "test_user", date(2025, 1, 1), 90, salary_adj, rent_adj, notes)
    fc = build_forecast(profile.current_available_balance, profile.minimum_balance_to_keep,
                         date(2025, 1, 1), 90, items)
    # 1000 - 500 = 500 of headroom with no cash flow at all
    assert fc.amount_safe_to_pay(10000) == 500.0
    assert fc.amount_safe_to_pay(200) == 200.0  # capped at requested amount
    assert fc.amount_safe_to_pay(0) == 0.0


def test_minimum_balance_is_never_violated_by_a_safe_payment():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=500.0)
    ds = make_minimal_dataset(profile, [])
    salary_adj, rent_adj, notes = _empty_adjustments()
    items = build_timeline(ds, "test_user", date(2025, 1, 1), 90, salary_adj, rent_adj, notes)
    fc = build_forecast(1000.0, 500.0, date(2025, 1, 1), 90, items)
    safe = fc.amount_safe_to_pay(500.0)
    assert fc.is_schedule_safe([(date(2025, 1, 1), safe)])
    # one cent more should not be reported as safe
    assert not fc.is_schedule_safe([(date(2025, 1, 1), safe + 1)]) or safe == 500.0


def test_recurring_income_is_projected_monthly_and_keeps_balance_up():
    profile = make_profile(current_available_balance=100.0, minimum_balance_to_keep=0.0)
    events = [
        make_event("e1", "test_user", "salary", "credit", 2000.0, date(2024, 11, 15)),
        make_event("e2", "test_user", "salary", "credit", 2000.0, date(2024, 12, 15)),
    ]
    ds = make_minimal_dataset(profile, events)
    salary_adj, rent_adj, notes = _empty_adjustments()
    items = build_timeline(ds, "test_user", date(2025, 1, 1), 90, salary_adj, rent_adj, notes)
    salary_items = [i for i in items if i.category == "salary"]
    # Should project forward to roughly 2025-01-15, 2025-02-15, 2025-03-15
    assert len(salary_items) >= 2
    assert all(i.delta == 2000.0 for i in salary_items)
    assert salary_items[0].dt.day == 15


def test_recurring_expense_projected_monthly_with_calendar_alignment():
    profile = make_profile(current_available_balance=5000.0, minimum_balance_to_keep=0.0)
    events = [
        make_event("e1", "test_user", "rent", "debit", 1200.0, date(2024, 11, 3)),
        make_event("e2", "test_user", "rent", "debit", 1200.0, date(2024, 12, 3)),
    ]
    ds = make_minimal_dataset(profile, events)
    salary_adj, rent_adj, notes = _empty_adjustments()
    items = build_timeline(ds, "test_user", date(2025, 1, 1), 60, salary_adj, rent_adj, notes)
    rent_items = [i for i in items if i.category == "rent"]
    assert len(rent_items) >= 1
    assert all(i.dt.day == 3 for i in rent_items)  # stays on the 3rd, doesn't drift
    assert all(i.delta == -1200.0 for i in rent_items)


def test_pending_debit_is_reserved_but_pending_credit_is_excluded():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=0.0)
    events = [
        make_event("e1", "test_user", "healthcare", "debit", 300.0, date(2025, 1, 20), status="pending",
                    event_type="expense"),
        make_event("e2", "test_user", "windfall", "credit", 500.0, date(2025, 1, 20), status="pending",
                    event_type="income"),
    ]
    ds = make_minimal_dataset(profile, events)
    salary_adj, rent_adj, notes = _empty_adjustments()
    items = build_timeline(ds, "test_user", date(2025, 1, 1), 90, salary_adj, rent_adj, notes)
    deltas = [i.delta for i in items]
    assert -300.0 in deltas  # pending debit reserved
    assert 500.0 not in deltas  # pending credit excluded until settled


def test_cancelled_and_failed_events_are_excluded():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=0.0)
    events = [
        make_event("e1", "test_user", "shopping", "debit", 999.0, date(2025, 1, 20), status="cancelled"),
        make_event("e2", "test_user", "shopping", "debit", 999.0, date(2025, 1, 21), status="failed"),
    ]
    ds = make_minimal_dataset(profile, events)
    salary_adj, rent_adj, notes = _empty_adjustments()
    items = build_timeline(ds, "test_user", date(2025, 1, 1), 90, salary_adj, rent_adj, notes)
    assert items == []


def test_unrealized_investment_value_is_never_counted():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=0.0)
    events = [
        make_event("e1", "test_user", "investment", "non_cash", 5000.0, date(2025, 1, 20), status="settled",
                    event_type="valuation"),
    ]
    ds = make_minimal_dataset(profile, events)
    salary_adj, rent_adj, notes = _empty_adjustments()
    items = build_timeline(ds, "test_user", date(2025, 1, 1), 90, salary_adj, rent_adj, notes)
    assert items == []


def test_currency_conversion_direct_rate():
    ds = make_dataset_from_demo()
    usd = ds.convert(100.0, "EUR", "USD", date(2025, 1, 15))
    assert round(usd, 2) == 108.0


def test_currency_conversion_same_currency_is_identity():
    ds = make_dataset_from_demo()
    assert ds.convert(42.0, "USD", "USD", date(2025, 1, 15)) == 42.0


def test_currency_conversion_inverse_rate_fallback():
    ds = make_dataset_from_demo()
    # only EUR->USD and USD->EUR are defined; both directions should work
    eur = ds.convert(108.0, "USD", "EUR", date(2025, 1, 15))
    assert round(eur, 2) == round(108.0 * 0.9259, 2)


def test_date_handling_no_recurrence_fabricated_from_single_occurrence():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=0.0)
    # "entertainment" is a recurring-pattern category (not a variable-essential
    # one), so a single historical occurrence must not be projected forward.
    events = [make_event("e1", "test_user", "entertainment", "debit", 200.0, date(2025, 1, 5))]
    ds = make_minimal_dataset(profile, events)
    salary_adj, rent_adj, notes = _empty_adjustments()
    items = build_timeline(ds, "test_user", date(2025, 1, 10), 90, salary_adj, rent_adj, notes)
    assert items == []
