"""
Thin Flask API over the existing "Buy or Wait?" engine.

No financial logic lives here -- every number in every response comes from
backend/engine/*, unchanged from the CLI (backend/main.py). This module only
adapts HTTP requests into the same Request/Profile/Dataset objects the CLI
uses, and serializes engine output back to JSON. It also keeps a small
in-memory history of decisions made through the API, seeded with the demo
batch requests, purely for the "History" screen in the frontend -- it is not
part of the financial reasoning.

Run:
    python3 backend/api.py
Serves on http://127.0.0.1:5001 by default. Free/local only -- no external
services, no API keys.
"""
from __future__ import annotations

import os
import sys
import uuid
from dataclasses import asdict
from datetime import date, timedelta

from flask import Flask, jsonify, request
from flask_cors import CORS

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from demo_data.generate_demo_data import ANCHOR  # the fixed demo "today"
from engine.data_loader import Dataset, Request as EngineRequest
from engine.pipeline import Pipeline, HORIZON_DAYS
from engine.payment_plans import changes_for_category_actions
from engine.timeline import build_timeline

DATASET_DIR = os.path.join(HERE, "demo_data")

app = Flask(__name__)
# Wildcard by default so the demo works with zero configuration (no auth,
# no cookies, no secrets are ever exchanged over this API, so a permissive
# default carries no real risk here). Set ALLOWED_ORIGINS to a comma-separated
# list of exact origins (e.g. "https://buy-or-wait.vercel.app") in production
# to restrict this to your deployed frontend instead of leaving it open.
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*")
if _allowed_origins == "*":
    CORS(app)
else:
    CORS(app, origins=[o.strip() for o in _allowed_origins.split(",") if o.strip()])

_ds = Dataset(DATASET_DIR)
_pipeline = Pipeline(_ds)
_ds.load_requests("requests.csv")  # loads the 3 seed demo requests into _ds.requests

# In-memory decision history for the demo UI only (not financial logic).
_history = []


def _seed_history():
    for rid in _ds.request_order:
        req = _ds.requests[rid]
        row = _pipeline.process(req)
        _history.append({
            "id": rid,
            "user_id": req.user_id,
            "item": req.request_text or req.request_type,
            "amount": req.requested_amount,
            "currency": _ds.profiles[req.user_id].home_currency,
            "date": req.request_date.isoformat(),
            **row,
        })


_seed_history()


def _profile_summary(user_id: str):
    profile = _ds.profiles[user_id]
    items = build_timeline(
        _ds, user_id, ANCHOR, HORIZON_DAYS,
        _pipeline.salary_adjustments, _pipeline.rent_adjustments, _pipeline.event_notes,
    )
    upcoming_income = sorted([it for it in items if it.delta > 0], key=lambda it: it.dt)[:5]
    upcoming_expenses = sorted([it for it in items if it.delta < 0], key=lambda it: it.dt)[:8]
    next_income = upcoming_income[0] if upcoming_income else None
    recurring_categories = sorted({it.category for it in items if it.delta < 0})
    return {
        "user_id": user_id,
        "home_currency": profile.home_currency,
        "current_available_balance": profile.current_available_balance,
        "minimum_balance_to_keep": profile.minimum_balance_to_keep,
        "financial_priorities": profile.financial_priorities,
        "protected_categories": profile.protect,
        "flexible_reduce_categories": profile.willing_reduce,
        "flexible_stop_categories": profile.willing_stop,
        "payment_methods_accepted": profile.payment_methods_user_will_consider,
        "max_installment_months": profile.max_installment_months,
        "next_income": None if next_income is None else {
            "date": next_income.dt.isoformat(), "amount": next_income.delta, "category": next_income.category,
        },
        "upcoming_commitments": [
            {"date": it.dt.isoformat(), "amount": -it.delta, "category": it.category,
             "description": it.description, "flexibility": it.flexibility, "event_id": it.event_id}
            for it in upcoming_expenses
        ],
        "recurring_expense_categories": recurring_categories,
        "as_of_date": ANCHOR.isoformat(),
    }


@app.get("/api/users")
def list_users():
    return jsonify(sorted(_ds.profiles.keys()))


@app.get("/api/profile/<user_id>")
def get_profile(user_id):
    if user_id not in _ds.profiles:
        return jsonify({"error": f"unknown user_id '{user_id}'"}), 404
    return jsonify(_profile_summary(user_id))


@app.get("/api/forecast/<user_id>")
def get_forecast(user_id):
    if user_id not in _ds.profiles:
        return jsonify({"error": f"unknown user_id '{user_id}'"}), 404
    items = build_timeline(
        _ds, user_id, ANCHOR, HORIZON_DAYS,
        _pipeline.salary_adjustments, _pipeline.rent_adjustments, _pipeline.event_notes,
    )
    profile = _ds.profiles[user_id]
    running = profile.current_available_balance
    points = [{"date": ANCHOR.isoformat(), "balance": running, "delta": 0, "category": "start",
               "description": "Current balance"}]
    from collections import defaultdict
    by_date = defaultdict(list)
    for it in items:
        by_date[it.dt].append(it)
    for d in sorted(by_date.keys()):
        day_items = by_date[d]
        running += sum(it.delta for it in day_items)
        points.append({
            "date": d.isoformat(), "balance": round(running, 2),
            "delta": round(sum(it.delta for it in day_items), 2),
            "category": "|".join(sorted({it.category for it in day_items})),
            "description": "; ".join(it.description for it in day_items[:3]),
        })
    lowest = min(points, key=lambda p: p["balance"])
    return jsonify({
        "user_id": user_id, "as_of_date": ANCHOR.isoformat(),
        "minimum_balance_to_keep": profile.minimum_balance_to_keep,
        "points": points, "lowest_point": lowest,
    })


@app.get("/api/history")
def get_history():
    return jsonify(_history)


def _parse_decision_payload(payload: dict):
    """Validate and normalize the fields shared by /api/decision and
    /api/what-if. Returns (engine_req, item, currency, amount, error_response).
    On validation failure, engine_req is None and error_response is a
    (body, status) tuple ready to return.
    """
    user_id = payload.get("user_id")
    item = payload.get("item", "Requested expense")
    amount = payload.get("amount")
    currency = payload.get("currency")
    description = payload.get("description", "")
    allows_partial_payment = bool(payload.get("allows_partial_payment", True))
    days_until_needed = payload.get("days_until_needed", 30)

    if user_id not in _ds.profiles:
        return None, None, None, None, ({"error": f"unknown user_id '{user_id}'. See GET /api/users."}, 400)
    if not isinstance(amount, (int, float)) or isinstance(amount, bool) or amount <= 0:
        return None, None, None, None, ({"error": "amount must be a positive number"}, 400)
    try:
        days_until_needed = int(days_until_needed)
    except (TypeError, ValueError):
        return None, None, None, None, ({"error": "days_until_needed must be an integer"}, 400)
    if not currency:
        currency = _ds.profiles[user_id].home_currency

    profile = _ds.profiles[user_id]
    request_date = ANCHOR
    desired_completion_date = request_date + timedelta(days=max(1, min(days_until_needed, HORIZON_DAYS)))

    try:
        requested_amount_home = _ds.convert(float(amount), currency, profile.home_currency, request_date)
    except ValueError as e:
        return None, None, None, None, ({"error": f"currency conversion failed: {e}"}, 400)

    rid = f"api_{uuid.uuid4().hex[:10]}"
    engine_req = EngineRequest(
        request_id=rid, user_id=user_id, request_date=request_date, request_type="purchase",
        requested_amount=round(requested_amount_home, 2), desired_completion_date=desired_completion_date,
        allows_partial_payment=allows_partial_payment,
        request_text=f"{item}: {description}".strip(": "),
    )
    _ds.requests[rid] = engine_req  # payment options lookup uses request_id; none supplied for ad-hoc requests
    return engine_req, item, currency, float(amount), None


@app.post("/api/decision")
def post_decision():
    payload = request.get_json(force=True, silent=True) or {}
    engine_req, item, currency, amount, err = _parse_decision_payload(payload)
    if err is not None:
        body, status = err
        return jsonify(body), status

    profile = _ds.profiles[engine_req.user_id]
    row = _pipeline.process(engine_req)
    record = {
        "id": engine_req.request_id, "user_id": engine_req.user_id, "item": item, "amount": amount,
        "currency": currency, "amount_in_home_currency": engine_req.requested_amount,
        "home_currency": profile.home_currency, "date": engine_req.request_date.isoformat(),
        "desired_completion_date": engine_req.desired_completion_date.isoformat(),
        "allows_partial_payment": engine_req.allows_partial_payment,
        **row,
    }
    _history.insert(0, record)
    return jsonify(record)


@app.post("/api/what-if")
def post_what_if():
    """Recompute the affordability decision under a hypothetical set of
    flexible-spending changes, using the same engine path as /api/decision
    (Pipeline.process_with_forced_changes -- no decision logic is
    duplicated here). Returns the baseline (no changes) and scenario
    (changes applied) decisions side by side, computed against the same
    request parameters so they are directly comparable, plus a numeric
    comparison so the frontend never has to compute affordability itself.

    Request body: the same fields as /api/decision, plus "changes": a list
    of {"category": "dining", "action": "reduce"} (action is "reduce" or
    "stop"). Unrecognized or ineligible category/action pairs are silently
    dropped from applied_changes rather than rejected, since the frontend
    only offers categories the user's own profile allows.
    """
    payload = request.get_json(force=True, silent=True) or {}
    engine_req, item, currency, amount, err = _parse_decision_payload(payload)
    if err is not None:
        body, status = err
        return jsonify(body), status

    raw_changes = payload.get("changes", [])
    if not isinstance(raw_changes, list):
        return jsonify({"error": "changes must be a list of {category, action} objects"}), 400
    category_actions = {}
    for entry in raw_changes:
        if not isinstance(entry, dict):
            continue
        category = entry.get("category")
        action = entry.get("action")
        if category and action in ("reduce", "stop"):
            category_actions[category] = action

    profile = _ds.profiles[engine_req.user_id]
    items = _pipeline.build_items(engine_req)
    forced_changes = changes_for_category_actions(items, profile, category_actions)

    baseline_row = _pipeline.process(engine_req)
    scenario_row = _pipeline.process_with_forced_changes(engine_req, forced_changes)

    common = {
        "id": engine_req.request_id, "user_id": engine_req.user_id, "item": item, "amount": amount,
        "currency": currency, "amount_in_home_currency": engine_req.requested_amount,
        "home_currency": profile.home_currency, "date": engine_req.request_date.isoformat(),
        "desired_completion_date": engine_req.desired_completion_date.isoformat(),
        "allows_partial_payment": engine_req.allows_partial_payment,
    }
    baseline = {**common, **baseline_row}
    scenario = {**common, **scenario_row}

    applied_changes = [
        {"category": profile_category(profile, c), "kind": c.kind, "event_id": c.event_id,
         "freed_amount": round(c.freed_amount, 2)}
        for c in forced_changes
    ]

    safe_before = float(baseline_row["amount_safe_to_pay"])
    safe_after = float(scenario_row["amount_safe_to_pay"])

    return jsonify({
        "request": common,
        "applied_changes": applied_changes,
        "baseline": baseline,
        "scenario": scenario,
        "comparison": {
            "amount_safe_to_pay_before": safe_before,
            "amount_safe_to_pay_after": safe_after,
            "difference": round(safe_after - safe_before, 2),
            "affordability_status_before": baseline_row["affordability_status"],
            "affordability_status_after": scenario_row["affordability_status"],
            "recommended_payment_method_before": baseline_row["recommended_payment_method"],
            "recommended_payment_method_after": scenario_row["recommended_payment_method"],
            "changed": baseline_row["affordability_status"] != scenario_row["affordability_status"]
                       or baseline_row["recommended_payment_method"] != scenario_row["recommended_payment_method"],
        },
    })


def profile_category(profile, spending_change) -> str:
    """The category a SpendingChange refers to, purely for display in the
    /api/what-if response (the engine's own data doesn't carry the category
    forward onto SpendingChange, only the event_id)."""
    for ev in (_ds.events_by_user.get(profile.user_id) or []):
        if ev.event_id == spending_change.event_id:
            return ev.category
    return "unknown"


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "users": len(_ds.profiles), "as_of_date": ANCHOR.isoformat()})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
