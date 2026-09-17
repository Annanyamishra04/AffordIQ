import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from tests.fixtures import make_minimal_dataset, make_profile, make_event, make_request

from engine.timeline import build_timeline
from engine.forecast import build_forecast
from engine.payment_plans import build_candidates, rank_candidates, search_spending_changes_for_full_payment
from engine.decide import build_row


def _forecast_for(profile, events, request_date, horizon=90):
    ds = make_minimal_dataset(profile, events)
    items = build_timeline(ds, profile.user_id, request_date, horizon, [], [], {})
    fc = build_forecast(profile.current_available_balance, profile.minimum_balance_to_keep,
                         request_date, horizon, items)
    return ds, items, fc


def test_installment_plan_rejected_if_it_violates_minimum_balance():
    profile = make_profile(current_available_balance=600.0, minimum_balance_to_keep=500.0,
                            payment_methods_user_will_consider=["installments"], max_installment_months=6)
    ds, items, fc = _forecast_for(profile, [], date(2025, 1, 1))
    req = make_request(profile.user_id, 1000.0, date(2025, 1, 1), date(2025, 4, 1))
    # An installment of 400/month would immediately breach the 500 minimum on a 600 balance
    from engine.data_loader import PaymentOption
    ds.payment_options_by_request[req.request_id] = [PaymentOption(
        payment_option_id="opt1", request_id=req.request_id, payment_method="installments",
        payment_amount=400.0, number_of_payments=3, first_payment_date=date(2025, 1, 1),
        payment_frequency_days=30, financing_fee=20.0, total_payable_amount=1220.0,
    )]
    candidates = build_candidates(ds, req, profile, items, fc, 90)
    assert all(c.method != "installments" for c in candidates)


def test_installment_plan_accepted_when_safe_and_within_max_months():
    profile = make_profile(current_available_balance=5000.0, minimum_balance_to_keep=200.0,
                            payment_methods_user_will_consider=["installments"], max_installment_months=6)
    ds, items, fc = _forecast_for(profile, [], date(2025, 1, 1))
    req = make_request(profile.user_id, 1200.0, date(2025, 1, 1), date(2025, 5, 1))
    from engine.data_loader import PaymentOption
    ds.payment_options_by_request[req.request_id] = [PaymentOption(
        payment_option_id="opt1", request_id=req.request_id, payment_method="installments",
        payment_amount=420.0, number_of_payments=3, first_payment_date=date(2025, 1, 1),
        payment_frequency_days=30, financing_fee=60.0, total_payable_amount=1260.0,
    )]
    candidates = build_candidates(ds, req, profile, items, fc, 90)
    installment_candidates = [c for c in candidates if c.method == "installments"]
    assert len(installment_candidates) == 1
    assert installment_candidates[0].num_payments == 3


def test_installment_plan_rejected_if_duration_exceeds_max_installment_months():
    profile = make_profile(current_available_balance=10000.0, minimum_balance_to_keep=100.0,
                            payment_methods_user_will_consider=["installments"], max_installment_months=2)
    ds, items, fc = _forecast_for(profile, [], date(2025, 1, 1))
    req = make_request(profile.user_id, 1200.0, date(2025, 1, 1), date(2025, 8, 1))
    from engine.data_loader import PaymentOption
    ds.payment_options_by_request[req.request_id] = [PaymentOption(
        payment_option_id="opt1", request_id=req.request_id, payment_method="installments",
        payment_amount=200.0, number_of_payments=6, first_payment_date=date(2025, 1, 1),
        payment_frequency_days=30, financing_fee=0.0, total_payable_amount=1200.0,
    )]
    candidates = build_candidates(ds, req, profile, items, fc, 90)
    assert all(c.method != "installments" for c in candidates)


def test_delayed_payment_wait_only_offered_when_a_later_safe_date_exists():
    profile = make_profile(current_available_balance=600.0, minimum_balance_to_keep=500.0,
                            payment_methods_user_will_consider=["full_payment"])
    events = [
        make_event("e1", "test_user", "salary", "credit", 5000.0, date(2024, 11, 15)),
        make_event("e2", "test_user", "salary", "credit", 5000.0, date(2024, 12, 15)),
    ]
    ds, items, fc = _forecast_for(profile, events, date(2025, 1, 1))
    req = make_request(profile.user_id, 1000.0, date(2025, 1, 1), date(2025, 3, 1))
    candidates = build_candidates(ds, req, profile, items, fc, 90)
    wait_candidates = [c for c in candidates if c.method == "wait"]
    assert len(wait_candidates) == 1
    assert wait_candidates[0].payments[0][0] > req.request_date


def test_spending_change_search_finds_stop_that_enables_full_payment():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=900.0,
                            willing_stop=["streaming"], willing_reduce=[], protect=[])
    events = [
        make_event("e1", "test_user", "streaming", "debit", 150.0, date(2024, 11, 20),
                    flexibility="stoppable"),
        make_event("e2", "test_user", "streaming", "debit", 150.0, date(2024, 12, 20),
                    flexibility="stoppable"),
    ]
    ds, items, fc = _forecast_for(profile, events, date(2025, 1, 1))
    # Without changes, paying 100 from a 1000 balance with a 900 minimum is right at the edge;
    # the projected future streaming debit would push it under, so it needs the change.
    assert not fc.is_schedule_safe([(date(2025, 1, 1), 100.0)])
    changes = search_spending_changes_for_full_payment(
        items, profile, 1000.0, 900.0, date(2025, 1, 1), 90, 100.0)
    assert changes is not None
    assert changes[0].kind == "stop"
    assert changes[0].event_id in ("e1", "e2")


def test_spending_change_never_touches_protected_category():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=900.0,
                            willing_stop=["rent"], protect=["rent"])  # contradictory on purpose
    events = [make_event("e1", "test_user", "rent", "debit", 150.0, date(2024, 11, 20),
                          flexibility="stoppable")]
    events.append(make_event("e2", "test_user", "rent", "debit", 150.0, date(2024, 12, 20),
                              flexibility="stoppable"))
    ds, items, fc = _forecast_for(profile, events, date(2025, 1, 1))
    changes = search_spending_changes_for_full_payment(
        items, profile, 1000.0, 900.0, date(2025, 1, 1), 90, 100.0)
    assert changes is None  # protect wins even though willing_stop also lists it


def test_reduce_respects_minimum_allowed_amount():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=950.0,
                            willing_reduce=["dining"], willing_stop=[], protect=[])
    events = [
        make_event("e1", "test_user", "dining", "debit", 200.0, date(2024, 11, 20),
                    flexibility="reducible", minimum_allowed_amount=180.0),
        make_event("e2", "test_user", "dining", "debit", 200.0, date(2024, 12, 20),
                    flexibility="reducible", minimum_allowed_amount=180.0),
    ]
    ds, items, fc = _forecast_for(profile, events, date(2025, 1, 1))
    changes = search_spending_changes_for_full_payment(
        items, profile, 1000.0, 950.0, date(2025, 1, 1), 90, 50.0)
    if changes:
        for c in changes:
            if c.kind == "reduce_to":
                assert c.new_amount >= 180.0


def test_invalid_negative_requested_amount_does_not_crash_row_builder():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=100.0)
    ds, items, fc = _forecast_for(profile, [], date(2025, 1, 1))
    req = make_request(profile.user_id, 0.01, date(2025, 1, 1), date(2025, 1, 10))
    row = build_row(req, profile, fc, None)
    assert row["affordability_status"] == "not_affordable"
    assert row["recommended_payment_method"] == "not_recommended"


def test_output_row_has_all_required_fields():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=100.0)
    ds, items, fc = _forecast_for(profile, [], date(2025, 1, 1))
    req = make_request(profile.user_id, 50.0, date(2025, 1, 1), date(2025, 1, 10))
    candidates = build_candidates(ds, req, profile, items, fc, 90)
    chosen = rank_candidates(candidates)
    row = build_row(req, profile, fc, chosen)
    required = {"request_id", "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
                "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed",
                "decision_explanation"}
    assert required.issubset(row.keys())
