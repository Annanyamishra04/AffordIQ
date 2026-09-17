import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

# The engine itself has no web dependency. Flask is only needed for the
# optional API layer, so these tests skip rather than breaking collection
# for the whole suite when it isn't installed.
api_module = pytest.importorskip(
    "api", reason="Flask not installed; API layer tests skipped"
)


def client():
    return api_module.app.test_client()


def test_health_endpoint():
    r = client().get("/api/health")
    assert r.status_code == 200
    assert r.get_json()["status"] == "ok"


def test_list_users_returns_demo_users():
    r = client().get("/api/users")
    users = r.get_json()
    assert "demo_alex" in users
    assert "demo_sam" in users
    assert "demo_jordan" in users


def test_profile_unknown_user_returns_404():
    r = client().get("/api/profile/not_a_real_user")
    assert r.status_code == 404


def test_decision_unknown_user_returns_400():
    r = client().post("/api/decision", json={"user_id": "nope", "item": "x", "amount": 10, "currency": "USD"})
    assert r.status_code == 400


def test_decision_negative_amount_returns_400():
    r = client().post("/api/decision", json={"user_id": "demo_alex", "item": "x", "amount": -5, "currency": "USD"})
    assert r.status_code == 400


def test_decision_missing_amount_returns_400():
    r = client().post("/api/decision", json={"user_id": "demo_alex", "item": "x", "currency": "USD"})
    assert r.status_code == 400


def test_decision_defaults_currency_to_home_currency_when_omitted():
    r = client().post("/api/decision", json={"user_id": "demo_alex", "item": "Book", "amount": 20})
    assert r.status_code == 200
    body = r.get_json()
    assert body["currency"] == "USD"


def test_decision_response_has_all_required_engine_fields():
    r = client().post("/api/decision", json={"user_id": "demo_sam", "item": "Bike", "amount": 300, "currency": "USD"})
    body = r.get_json()
    for field in ("amount_safe_to_pay", "affordability_status", "recommended_payment_method",
                  "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed",
                  "decision_explanation"):
        assert field in body


def test_decision_with_cross_currency_conversion():
    r = client().post("/api/decision", json={
        "user_id": "demo_jordan", "item": "Camera", "amount": 300, "currency": "USD",
    })
    body = r.get_json()
    assert body["home_currency"] == "EUR"
    assert body["amount_in_home_currency"] != 300  # was converted from USD to EUR
    assert body["amount_in_home_currency"] > 0


def test_history_grows_after_a_decision():
    before = len(client().get("/api/history").get_json())
    client().post("/api/decision", json={"user_id": "demo_alex", "item": "Headphones", "amount": 50, "currency": "USD"})
    after = len(client().get("/api/history").get_json())
    assert after == before + 1


def test_forecast_has_points_and_respects_minimum_balance_field():
    r = client().get("/api/forecast/demo_alex")
    body = r.get_json()
    assert len(body["points"]) > 1
    assert "minimum_balance_to_keep" in body
    assert "lowest_point" in body


def test_forecast_unknown_user_returns_404():
    r = client().get("/api/forecast/not_a_real_user")
    assert r.status_code == 404


def test_decision_amount_wrong_type_returns_400():
    r = client().post("/api/decision", json={"user_id": "demo_alex", "item": "x", "amount": "ten", "currency": "USD"})
    assert r.status_code == 400


def test_decision_zero_amount_returns_400():
    r = client().post("/api/decision", json={"user_id": "demo_alex", "item": "x", "amount": 0, "currency": "USD"})
    assert r.status_code == 400


def test_decision_boolean_amount_is_rejected():
    """True/False satisfy Python's isinstance(x, (int, float)) but are not
    a real amount -- this must not silently become amount=1."""
    r = client().post("/api/decision", json={"user_id": "demo_alex", "item": "x", "amount": True, "currency": "USD"})
    assert r.status_code == 400


def test_decision_invalid_json_body_does_not_crash():
    r = client().post("/api/decision", data="not json", content_type="application/json")
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_decision_empty_body_returns_400_not_500():
    r = client().post("/api/decision", data="", content_type="application/json")
    assert r.status_code == 400


def test_decision_safe_purchase_is_affordable():
    r = client().post("/api/decision", json={
        "user_id": "demo_alex", "item": "Coffee", "amount": 5, "currency": "USD", "days_until_needed": 10,
    })
    body = r.get_json()
    assert r.status_code == 200
    assert body["affordability_status"] in ("affordable_now", "affordable_with_plan")


def test_decision_unsafe_purchase_is_not_affordable():
    r = client().post("/api/decision", json={
        "user_id": "demo_jordan", "item": "Yacht", "amount": 5_000_000, "currency": "EUR", "days_until_needed": 5,
    })
    body = r.get_json()
    assert r.status_code == 200
    assert body["affordability_status"] == "not_affordable"
    assert body["recommended_payment_method"] == "not_recommended"


def test_decision_response_includes_allows_partial_payment():
    r = client().post("/api/decision", json={
        "user_id": "demo_alex", "item": "x", "amount": 10, "currency": "USD", "allows_partial_payment": False,
    })
    assert r.get_json()["allows_partial_payment"] is False


# ---------------------------------------------------------------------------
# /api/what-if
# ---------------------------------------------------------------------------

def test_what_if_unknown_user_returns_400():
    r = client().post("/api/what-if", json={"user_id": "nope", "item": "x", "amount": 10, "currency": "USD"})
    assert r.status_code == 400


def test_what_if_invalid_amount_returns_400():
    r = client().post("/api/what-if", json={"user_id": "demo_alex", "item": "x", "amount": -1, "currency": "USD"})
    assert r.status_code == 400


def test_what_if_invalid_json_does_not_crash():
    r = client().post("/api/what-if", data="not json", content_type="application/json")
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_what_if_changes_must_be_a_list():
    r = client().post("/api/what-if", json={
        "user_id": "demo_alex", "item": "x", "amount": 10, "currency": "USD",
        "changes": "stop streaming",
    })
    assert r.status_code == 400


def test_what_if_with_no_changes_matches_a_plain_decision():
    payload = {"user_id": "demo_alex", "item": "Gadget", "amount": 200, "currency": "USD", "days_until_needed": 20}
    plain = client().post("/api/decision", json=payload).get_json()
    what_if = client().post("/api/what-if", json={**payload, "changes": []}).get_json()
    assert what_if["baseline"]["affordability_status"] == plain["affordability_status"]
    assert what_if["baseline"]["amount_safe_to_pay"] == plain["amount_safe_to_pay"]
    assert what_if["scenario"]["affordability_status"] == plain["affordability_status"]


def test_what_if_returns_baseline_scenario_and_comparison():
    r = client().post("/api/what-if", json={
        "user_id": "demo_alex", "item": "Laptop", "amount": 5000, "currency": "USD", "days_until_needed": 20,
        "changes": [{"category": "streaming", "action": "stop"}],
    })
    assert r.status_code == 200
    body = r.get_json()
    for key in ("baseline", "scenario", "comparison", "applied_changes", "request"):
        assert key in body
    comp = body["comparison"]
    for key in ("amount_safe_to_pay_before", "amount_safe_to_pay_after", "difference",
                "affordability_status_before", "affordability_status_after",
                "recommended_payment_method_before", "recommended_payment_method_after", "changed"):
        assert key in comp
    # every number in the comparison must come straight from re-derived engine output
    assert comp["difference"] == round(comp["amount_safe_to_pay_after"] - comp["amount_safe_to_pay_before"], 2)


def test_what_if_applied_changes_only_includes_real_eligible_events():
    """demo_alex's profile lists 'dining' as reducible, but no dining event
    in the timeline is anchored to a real event_id (it's synthesized daily
    essential spend) -- so requesting a dining reduction must be silently
    dropped, never fabricated."""
    r = client().post("/api/what-if", json={
        "user_id": "demo_alex", "item": "x", "amount": 100, "currency": "USD", "days_until_needed": 20,
        "changes": [{"category": "dining", "action": "reduce"}],
    })
    body = r.get_json()
    assert body["applied_changes"] == []


def test_what_if_unrecognized_category_is_silently_ignored_not_an_error():
    r = client().post("/api/what-if", json={
        "user_id": "demo_alex", "item": "x", "amount": 100, "currency": "USD", "days_until_needed": 20,
        "changes": [{"category": "totally_made_up", "action": "stop"}],
    })
    assert r.status_code == 200
    assert r.get_json()["applied_changes"] == []


def test_what_if_malformed_change_entries_are_ignored_not_fatal():
    r = client().post("/api/what-if", json={
        "user_id": "demo_alex", "item": "x", "amount": 100, "currency": "USD", "days_until_needed": 20,
        "changes": ["not a dict", {"category": "streaming"}, {"action": "stop"}, 42, None],
    })
    assert r.status_code == 200


def test_what_if_cross_currency_conversion_applies_to_both_baseline_and_scenario():
    r = client().post("/api/what-if", json={
        "user_id": "demo_jordan", "item": "Camera", "amount": 300, "currency": "USD", "days_until_needed": 20,
        "changes": [],
    })
    body = r.get_json()
    assert body["baseline"]["home_currency"] == "EUR"
    assert body["baseline"]["amount_in_home_currency"] != 300
    assert body["scenario"]["amount_in_home_currency"] == body["baseline"]["amount_in_home_currency"]


def test_what_if_stopping_a_real_flexible_expense_never_reduces_headroom():
    r = client().post("/api/what-if", json={
        "user_id": "demo_sam", "item": "Repair", "amount": 550, "currency": "USD", "days_until_needed": 30,
        "changes": [{"category": "gym", "action": "stop"}],
    })
    body = r.get_json()
    assert body["applied_changes"], "expected demo_sam's gym subscription to be a real, eligible change"
    assert body["comparison"]["amount_safe_to_pay_after"] >= body["comparison"]["amount_safe_to_pay_before"]


def test_what_if_does_not_pollute_decision_history():
    """A what-if exploration is hypothetical -- it must not appear as a
    real decision in the History view."""
    before = len(client().get("/api/history").get_json())
    client().post("/api/what-if", json={
        "user_id": "demo_alex", "item": "Speculative", "amount": 40, "currency": "USD",
        "changes": [{"category": "streaming", "action": "stop"}],
    })
    after = len(client().get("/api/history").get_json())
    assert after == before
