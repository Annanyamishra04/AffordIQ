"""Edge-case tests for the timeline and forecast primitives.

Covers the parts of the financial logic most likely to break silently:
calendar-month recurrence at month boundaries, continuous essential-spend
forecasting, future scheduled income, and the earliest-safe-date search.
All fixtures are synthetic.
"""
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "backend")))

from engine.forecast import build_forecast  # noqa: E402
from engine.timeline import _add_calendar_months, build_timeline  # noqa: E402
from fixtures import make_dataset_from_demo, make_event, make_minimal_dataset, make_profile  # noqa: E402

NO_ADJ = ([], [], {})


def _timeline(ds, user_id, request_date, horizon=90):
    return build_timeline(ds, user_id, request_date, horizon, *NO_ADJ)


# ---------------------------------------------------------------------------
# calendar-month recurrence
# ---------------------------------------------------------------------------

def test_add_calendar_months_preserves_day_of_month():
    assert _add_calendar_months(date(2025, 1, 15), 1) == date(2025, 2, 15)
    assert _add_calendar_months(date(2025, 1, 15), 3) == date(2025, 4, 15)


def test_add_calendar_months_clamps_to_end_of_short_month():
    """A bill on the 31st must land on the last day of a shorter month,
    not roll over into the next one."""
    assert _add_calendar_months(date(2025, 1, 31), 1) == date(2025, 2, 28)
    assert _add_calendar_months(date(2025, 3, 31), 1) == date(2025, 4, 30)


def test_add_calendar_months_handles_leap_year():
    assert _add_calendar_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


def test_add_calendar_months_crosses_year_boundary():
    assert _add_calendar_months(date(2025, 11, 30), 2) == date(2026, 1, 30)


def test_monthly_rent_does_not_drift_across_months():
    """Naive 30-day stepping would drift a rent date earlier each month.
    Calendar alignment must keep it on the same day-of-month."""
    profile = make_profile(user_id="u", current_available_balance=20000.0,
                           minimum_balance_to_keep=0.0)
    events = [
        make_event("r1", "u", "rent", "debit", 1000.0, date(2024, 11, 5)),
        make_event("r2", "u", "rent", "debit", 1000.0, date(2024, 12, 5)),
        make_event("r3", "u", "rent", "debit", 1000.0, date(2025, 1, 5)),
    ]
    ds = make_minimal_dataset(profile, events)
    items = _timeline(ds, "u", date(2025, 1, 10), horizon=90)
    rent_days = sorted({it.dt for it in items if it.category == "rent"})
    assert rent_days, "rent should be projected forward"
    assert all(d.day == 5 for d in rent_days), rent_days


# ---------------------------------------------------------------------------
# essential spending
# ---------------------------------------------------------------------------

def test_essential_spending_is_spread_daily_not_lumped_monthly():
    """Essential spend must appear on (almost) every forecast day; a single
    monthly lump would hide mid-month dips below the minimum balance."""
    profile = make_profile(user_id="u", current_available_balance=5000.0)
    events = [
        make_event(f"g{i}", "u", "groceries", "debit", 100.0,
                   date(2024, 12, 1) + timedelta(days=i * 7))
        for i in range(6)
    ]
    ds = make_minimal_dataset(profile, events)
    request_date = date(2025, 1, 12)
    items = _timeline(ds, "u", request_date, horizon=30)
    grocery_days = {it.dt for it in items if it.category == "groceries"}
    assert len(grocery_days) >= 29, f"expected near-daily spread, got {len(grocery_days)}"
    assert all(it.delta < 0 for it in items if it.category == "groceries")


def test_essential_spending_absent_when_no_history():
    profile = make_profile(user_id="u")
    ds = make_minimal_dataset(profile, [])
    items = _timeline(ds, "u", date(2025, 1, 12), horizon=30)
    assert not [it for it in items if it.category == "groceries"]


# ---------------------------------------------------------------------------
# future scheduled income / payments
# ---------------------------------------------------------------------------

def test_future_scheduled_credit_raises_capacity():
    profile = make_profile(user_id="u", current_available_balance=1000.0,
                           minimum_balance_to_keep=500.0)
    request_date = date(2025, 1, 15)
    payday = request_date + timedelta(days=10)
    base = make_minimal_dataset(profile, [])
    with_income = make_minimal_dataset(
        profile, [make_event("s1", "u", "salary", "credit", 2000.0, payday,
                             status="scheduled", event_type="income")])

    fc_base = build_forecast(1000.0, 500.0, request_date, 90, _timeline(base, "u", request_date))
    fc_income = build_forecast(1000.0, 500.0, request_date, 90,
                               _timeline(with_income, "u", request_date))

    assert fc_base.amount_safe_to_pay(5000.0) == 500.0
    # Scheduled income does not raise what is safe to pay *today*...
    assert fc_income.amount_safe_to_pay(5000.0) == 500.0
    # ...but it does create a later date at which the full amount is safe.
    assert fc_base.earliest_full_payment_date(2000.0) is None
    assert fc_income.earliest_full_payment_date(2000.0) == payday


def test_scheduled_future_debit_reduces_safe_amount():
    profile = make_profile(user_id="u", current_available_balance=2000.0,
                           minimum_balance_to_keep=500.0)
    request_date = date(2025, 1, 15)
    ds = make_minimal_dataset(profile, [
        make_event("d1", "u", "utilities", "debit", 300.0,
                   request_date + timedelta(days=5), status="scheduled")])
    fc = build_forecast(2000.0, 500.0, request_date, 90, _timeline(ds, "u", request_date))
    assert fc.amount_safe_to_pay(5000.0) == 1200.0


def test_earliest_full_payment_date_is_request_date_when_already_safe():
    profile = make_profile(user_id="u", current_available_balance=5000.0,
                           minimum_balance_to_keep=500.0)
    request_date = date(2025, 1, 15)
    ds = make_minimal_dataset(profile, [])
    fc = build_forecast(5000.0, 500.0, request_date, 90, _timeline(ds, "u", request_date))
    assert fc.earliest_full_payment_date(1000.0) == request_date


def test_payment_outside_horizon_is_not_considered_safe():
    profile = make_profile(user_id="u", current_available_balance=5000.0,
                           minimum_balance_to_keep=0.0)
    request_date = date(2025, 1, 15)
    ds = make_minimal_dataset(profile, [])
    fc = build_forecast(5000.0, 0.0, request_date, 90, _timeline(ds, "u", request_date))
    assert fc.is_schedule_safe([(request_date + timedelta(days=200), 10.0)]) is False
    assert fc.is_schedule_safe([(request_date - timedelta(days=1), 10.0)]) is False


def test_multi_leg_schedule_accounts_for_cumulative_drain():
    """Each leg individually affordable, but together they must not breach
    the minimum balance."""
    profile = make_profile(user_id="u", current_available_balance=1000.0,
                           minimum_balance_to_keep=500.0)
    request_date = date(2025, 1, 15)
    ds = make_minimal_dataset(profile, [])
    fc = build_forecast(1000.0, 500.0, request_date, 90, _timeline(ds, "u", request_date))
    assert fc.is_schedule_safe([(request_date, 400.0)]) is True
    assert fc.is_schedule_safe([(request_date, 400.0),
                                (request_date + timedelta(days=5), 200.0)]) is False


# ---------------------------------------------------------------------------
# determinism
# ---------------------------------------------------------------------------

def test_pipeline_is_deterministic_across_runs():
    from engine.pipeline import Pipeline
    ds = make_dataset_from_demo()
    requests = ds.load_requests("requests.csv")
    first = Pipeline(ds).process_all(requests)
    second = Pipeline(make_dataset_from_demo()).process_all(requests)
    assert first == second
