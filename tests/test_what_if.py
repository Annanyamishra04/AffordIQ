"""Tests for the what-if scenario engine primitives that back
POST /api/what-if: `changes_for_category_actions` (translating user-facing
category choices into concrete SpendingChange objects) and
`Pipeline.process_with_forced_changes` (recomputing a decision under those
changes). These reuse the exact same candidate/ranking machinery as a plain
decision -- there is no separate "what-if" decision algorithm.
"""
import os
import sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.abspath(os.path.join(HERE, "..", "backend")))

from engine.payment_plans import changes_for_category_actions  # noqa: E402
from engine.pipeline import HORIZON_DAYS, Pipeline  # noqa: E402
from fixtures import make_event, make_minimal_dataset, make_profile, make_request  # noqa: E402


def _pipeline_for(profile, events):
    ds = make_minimal_dataset(profile, events)
    return ds, Pipeline(ds)


def test_changes_for_category_actions_maps_stop_correctly():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=500.0,
                           willing_stop=["streaming"], willing_reduce=[], protect=[])
    events = [make_event("e1", "test_user", "streaming", "debit", 50.0, date(2025, 1, 10),
                         flexibility="stoppable")]
    ds, pipeline = _pipeline_for(profile, events)
    req = make_request("test_user", 100.0, date(2025, 1, 1), date(2025, 2, 1))
    items = pipeline.build_items(req)

    changes = changes_for_category_actions(items, profile, {"streaming": "stop"})
    assert len(changes) == 1
    assert changes[0].kind == "stop"
    assert changes[0].event_id == "e1"


def test_changes_for_category_actions_maps_reduce_correctly():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=500.0,
                           willing_stop=[], willing_reduce=["dining"], protect=[])
    events = [make_event("e1", "test_user", "dining", "debit", 80.0, date(2025, 1, 10),
                         flexibility="reducible", minimum_allowed_amount=20.0)]
    ds, pipeline = _pipeline_for(profile, events)
    req = make_request("test_user", 100.0, date(2025, 1, 1), date(2025, 2, 1))
    items = pipeline.build_items(req)

    changes = changes_for_category_actions(items, profile, {"dining": "reduce"})
    assert len(changes) == 1
    assert changes[0].kind == "reduce_to"
    assert changes[0].new_amount == 20.0


def test_changes_for_category_actions_ignores_protected_category():
    """Even if the caller asks to stop a protected category, nothing is
    returned -- protection cannot be bypassed through the what-if endpoint,
    same as the automatic search."""
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=500.0,
                           willing_stop=["rent"], protect=["rent"])
    events = [make_event("e1", "test_user", "rent", "debit", 300.0, date(2025, 1, 10),
                         flexibility="stoppable")]
    ds, pipeline = _pipeline_for(profile, events)
    req = make_request("test_user", 100.0, date(2025, 1, 1), date(2025, 2, 1))
    items = pipeline.build_items(req)

    changes = changes_for_category_actions(items, profile, {"rent": "stop"})
    assert changes == []


def test_changes_for_category_actions_ignores_unrequested_categories():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=500.0,
                           willing_stop=["streaming", "gym"], protect=[])
    events = [
        make_event("e1", "test_user", "streaming", "debit", 50.0, date(2025, 1, 10), flexibility="stoppable"),
        make_event("e2", "test_user", "gym", "debit", 60.0, date(2025, 1, 10), flexibility="stoppable"),
    ]
    ds, pipeline = _pipeline_for(profile, events)
    req = make_request("test_user", 100.0, date(2025, 1, 1), date(2025, 2, 1))
    items = pipeline.build_items(req)

    changes = changes_for_category_actions(items, profile, {"streaming": "stop"})
    assert [c.event_id for c in changes] == ["e1"]


def test_changes_for_category_actions_wrong_action_yields_nothing():
    """A category the user is only willing to reduce cannot be 'stopped'
    via what-if, and vice versa."""
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=500.0,
                           willing_stop=[], willing_reduce=["dining"], protect=[])
    events = [make_event("e1", "test_user", "dining", "debit", 80.0, date(2025, 1, 10),
                         flexibility="reducible")]
    ds, pipeline = _pipeline_for(profile, events)
    req = make_request("test_user", 100.0, date(2025, 1, 1), date(2025, 2, 1))
    items = pipeline.build_items(req)

    assert changes_for_category_actions(items, profile, {"dining": "stop"}) == []


def test_changes_for_category_actions_unknown_category_yields_nothing():
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=500.0)
    ds, pipeline = _pipeline_for(profile, [])
    req = make_request("test_user", 100.0, date(2025, 1, 1), date(2025, 2, 1))
    items = pipeline.build_items(req)
    assert changes_for_category_actions(items, profile, {"nonexistent": "stop"}) == []


# ---------------------------------------------------------------------------
# process_with_forced_changes: end-to-end recalculation
# ---------------------------------------------------------------------------

def test_forced_change_makes_an_unsafe_purchase_safe():
    """The core scenario the what-if feature exists for: a purchase that
    is not_affordable as a plain decision becomes safe once the user
    deliberately selects enough flexible cuts -- specifically, more cuts
    than the automatic search behind a plain decision will ever try.

    The automatic search (`search_spending_changes_for_full_payment`) caps
    combinations at 3 changes, by design (see docs/financial-logic.md #13:
    asking someone to cancel many things at once isn't a plan they'd
    follow). What-if has no such cap, because the user is the one choosing
    the combination, not the engine guessing at it -- so a fix requiring 4
    specific cuts is reachable through what-if even though a plain decision
    can never find it on its own.
    """
    profile = make_profile(
        current_available_balance=1000.0, minimum_balance_to_keep=900.0,
        willing_stop=["streaming", "gym", "shopping", "entertainment"], willing_reduce=[], protect=[],
        payment_methods_user_will_consider=["full_payment"])
    events = [
        make_event("e1", "test_user", "streaming", "debit", 60.0, date(2025, 1, 6), flexibility="stoppable"),
        make_event("e2", "test_user", "gym", "debit", 60.0, date(2025, 1, 6), flexibility="stoppable"),
        make_event("e3", "test_user", "shopping", "debit", 60.0, date(2025, 1, 6), flexibility="stoppable"),
        make_event("e4", "test_user", "entertainment", "debit", 60.0, date(2025, 1, 6), flexibility="stoppable"),
    ]
    ds, pipeline = _pipeline_for(profile, events)
    # 950 immediately after paying 50. Any 3 of the 4 debits removed still
    # leaves one 60-unit debit (950-60=890 < 900) -- unsafe. Only removing
    # all 4 clears it (950-0=950 >= 900).
    req = make_request("test_user", 50.0, date(2025, 1, 1), date(2025, 2, 1), allows_partial_payment=False)

    baseline = pipeline.process(req)
    assert baseline["affordability_status"] == "not_affordable"

    items = pipeline.build_items(req)
    changes = changes_for_category_actions(items, profile, {
        "streaming": "stop", "gym": "stop", "shopping": "stop", "entertainment": "stop",
    })
    assert {c.event_id for c in changes} == {"e1", "e2", "e3", "e4"}

    scenario = pipeline.process_with_forced_changes(req, changes)
    assert scenario["affordability_status"] == "affordable_with_plan"
    assert scenario["recommended_payment_method"] == "full_payment"
    # decide.py's CSV-style `spending_changes_needed` string caps display at
    # 3 items (matching the automatic search's own cap) -- it is not the
    # authoritative record of what was applied. The API layer's
    # `applied_changes` field (built directly from the SpendingChange
    # objects, not this string) is what the frontend uses, and it is not
    # truncated. Here we confirm the truncation is display-only: the
    # forecast that produced `affordable_with_plan` above already had all
    # four debits removed before it was built, which is the real proof.
    displayed = scenario["spending_changes_needed"].split("|")
    assert len(displayed) == 3
    assert set(displayed) <= {"stop:e1", "stop:e2", "stop:e3", "stop:e4"}

    before = float(baseline["amount_safe_to_pay"])
    after = float(scenario["amount_safe_to_pay"])
    assert after > before


def test_user_can_choose_a_different_fix_than_the_automatic_search_would():
    """Two independent, equally-sized flexible expenses can each alone
    resolve the shortfall. The automatic search (used by a plain decision)
    picks whichever it finds first; what-if lets the user pick the *other*
    one specifically, and the engine honours that choice rather than
    silently substituting its own preference."""
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=900.0,
                           willing_stop=["streaming", "shopping"], willing_reduce=[], protect=[],
                           payment_methods_user_will_consider=["full_payment"])
    events = [
        make_event("e1", "test_user", "streaming", "debit", 40.0, date(2025, 1, 6), flexibility="stoppable"),
        make_event("e2", "test_user", "shopping", "debit", 40.0, date(2025, 1, 6), flexibility="stoppable"),
    ]
    ds, pipeline = _pipeline_for(profile, events)
    req = make_request("test_user", 50.0, date(2025, 1, 1), date(2025, 2, 1), allows_partial_payment=False)

    baseline = pipeline.process(req)
    assert baseline["affordability_status"] == "affordable_with_plan"
    assert baseline["spending_changes_needed"] == "stop:e1"  # the automatic pick

    items = pipeline.build_items(req)
    user_choice = changes_for_category_actions(items, profile, {"shopping": "stop"})
    assert [c.event_id for c in user_choice] == ["e2"]

    scenario = pipeline.process_with_forced_changes(req, user_choice)
    assert scenario["affordability_status"] == "affordable_with_plan"
    assert scenario["spending_changes_needed"] == "stop:e2"  # the user's own pick, honoured exactly


def test_forced_changes_are_merged_with_any_further_automatic_change():
    """If the user's forced changes aren't quite enough on their own, the
    same automatic search used elsewhere in the engine still runs on top of
    the already-modified items -- and the forced changes are listed first
    in the resulting plan."""
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=900.0,
                           willing_stop=["streaming", "gym"], willing_reduce=[], protect=[],
                           payment_methods_user_will_consider=["full_payment"])
    events = [
        make_event("e1", "test_user", "streaming", "debit", 20.0, date(2025, 1, 6), flexibility="stoppable"),
        make_event("e2", "test_user", "gym", "debit", 20.0, date(2025, 1, 6), flexibility="stoppable"),
        make_event("e3", "test_user", "streaming", "debit", 90.0, date(2025, 1, 6), flexibility="stoppable"),
    ]
    ds, pipeline = _pipeline_for(profile, events)
    # 950 immediately after paying 50. All three debits together (130)
    # would leave 820 < 900. Stopping only the small "e1" leaves e2+e3
    # (110), still unsafe (840 < 900) -- the automatic search must find
    # that e3 also needs to go.
    req = make_request("test_user", 50.0, date(2025, 1, 1), date(2025, 2, 1), allows_partial_payment=False)

    items = pipeline.build_items(req)
    forced = changes_for_category_actions(items, profile, {"streaming": "stop"})
    # Both streaming-category events match "streaming"; force only e1 to
    # simulate a user who wants to keep most of e3 for now (see next test
    # for choosing a specific event) -- here we test the *merge* behaviour,
    # so we deliberately pass only the smaller of the two forced changes.
    forced = [c for c in forced if c.event_id == "e1"]
    assert [c.event_id for c in forced] == ["e1"]

    scenario = pipeline.process_with_forced_changes(req, forced)
    assert scenario["affordability_status"] == "affordable_with_plan"
    changes_applied = scenario["spending_changes_needed"].split("|")
    assert changes_applied[0] == "stop:e1"  # the user's own choice, listed first
    assert "stop:e3" in changes_applied     # the automatic search's addition
    assert "stop:e2" not in changes_applied  # gym was never needed


def test_forced_changes_never_worse_than_baseline_amount_safe_to_pay():
    """Freeing money should never reduce what the base forecast says is
    safe to pay -- a basic sanity/monotonicity property of the engine."""
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=500.0,
                           willing_stop=["streaming"], willing_reduce=[], protect=[])
    events = [make_event("e1", "test_user", "streaming", "debit", 100.0, date(2025, 1, 3),
                         flexibility="stoppable")]
    ds, pipeline = _pipeline_for(profile, events)
    req = make_request("test_user", 50.0, date(2025, 1, 1), date(2025, 2, 1))

    baseline = pipeline.process(req)
    items = pipeline.build_items(req)
    changes = changes_for_category_actions(items, profile, {"streaming": "stop"})
    scenario = pipeline.process_with_forced_changes(req, changes)

    assert float(scenario["amount_safe_to_pay"]) >= float(baseline["amount_safe_to_pay"])


def test_empty_forced_changes_reproduces_the_plain_decision():
    """No changes selected must behave identically to a normal decision --
    process_with_forced_changes([]) is not a different code path."""
    profile = make_profile(current_available_balance=1000.0, minimum_balance_to_keep=500.0)
    ds, pipeline = _pipeline_for(profile, [])
    req = make_request("test_user", 100.0, date(2025, 1, 1), date(2025, 2, 1))

    assert pipeline.process(req) == pipeline.process_with_forced_changes(req, [])
