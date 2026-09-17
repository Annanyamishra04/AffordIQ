"""Tests for the output validator in backend/evaluation/main.py.

The validator is the project's safety net, so it is tested the same way the
engine is: with deliberately broken outputs that it must reject. Nothing
here asserts a specific expected recommendation -- only that malformed or
unsafe output is caught.
"""
import csv
import importlib.util
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.abspath(os.path.join(HERE, "..", "backend"))
sys.path.insert(0, BACKEND_DIR)

_spec = importlib.util.spec_from_file_location(
    "evaluation_main", os.path.join(BACKEND_DIR, "evaluation", "main.py"))
evaluation = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(evaluation)

COLUMNS = evaluation.REQUIRED_COLUMNS

GOOD_ROW = {
    "request_id": "r1",
    "amount_safe_to_pay": "500",
    "affordability_status": "affordable_now",
    "recommended_payment_method": "full_payment",
    "payment_plan": "2025-01-15:500",
    "earliest_date_for_full_payment": "2025-01-15",
    "spending_changes_needed": "none",
    "decision_explanation": "Pay USD 500 today.",
}

REQUEST_ROW = {
    "request_id": "r1",
    "user_id": "u1",
    "request_date": "2025-01-15",
    "request_type": "purchase",
    "requested_amount": "500",
    "desired_completion_date": "2025-02-15",
    "allows_partial_payment": "true",
    "request_text": "t",
}


def _write(tmp_path, out_rows, req_rows=(REQUEST_ROW,)):
    out = tmp_path / "output.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)
    req = tmp_path / "requests.csv"
    with open(req, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(req_rows[0].keys()))
        w.writeheader()
        for r in req_rows:
            w.writerow(r)
    return str(out), str(req)


def _errors(tmp_path, row_overrides=None, req_rows=(REQUEST_ROW,)):
    row = dict(GOOD_ROW)
    if row_overrides:
        row.update(row_overrides)
    out, req = _write(tmp_path, [row], req_rows)
    return evaluation.validate_structure(out, req)


def test_well_formed_row_passes(tmp_path):
    assert _errors(tmp_path) == []


def test_duplicate_request_ids_are_rejected(tmp_path):
    out, req = _write(tmp_path, [GOOD_ROW, GOOD_ROW])
    errors = evaluation.validate_structure(out, req)
    assert any("duplicate" in e for e in errors)


def test_missing_request_id_is_reported(tmp_path):
    out, req = _write(tmp_path, [])
    errors = evaluation.validate_structure(out, req)
    assert any("missing in output" in e for e in errors)


def test_unexpected_request_id_is_reported(tmp_path):
    errors = _errors(tmp_path, {"request_id": "ghost"})
    assert any("unexpected" in e for e in errors)


def test_invalid_status_is_rejected(tmp_path):
    errors = _errors(tmp_path, {"affordability_status": "maybe"})
    assert any("invalid affordability_status" in e for e in errors)


def test_invalid_method_is_rejected(tmp_path):
    errors = _errors(tmp_path, {"recommended_payment_method": "vibes"})
    assert any("invalid recommended_payment_method" in e for e in errors)


def test_invalid_date_is_rejected(tmp_path):
    errors = _errors(tmp_path, {"earliest_date_for_full_payment": "15-01-2025"})
    assert any("invalid earliest_date_for_full_payment" in e for e in errors)


def test_impossible_calendar_date_is_rejected(tmp_path):
    errors = _errors(tmp_path, {"earliest_date_for_full_payment": "2025-02-30"})
    assert any("invalid earliest_date_for_full_payment" in e for e in errors)


def test_malformed_payment_plan_leg_is_rejected(tmp_path):
    errors = _errors(tmp_path, {"payment_plan": "2025-01-15"})
    assert any("malformed payment_plan" in e for e in errors)


def test_payment_total_mismatch_is_rejected(tmp_path):
    errors = _errors(tmp_path, {"payment_plan": "2025-01-15:300"})
    assert any("!= requested_amount" in e for e in errors)


def test_negative_amount_safe_to_pay_is_rejected(tmp_path):
    errors = _errors(tmp_path, {"amount_safe_to_pay": "-10"})
    assert any("negative amount_safe_to_pay" in e for e in errors)


def test_amount_safe_to_pay_above_requested_is_rejected(tmp_path):
    errors = _errors(tmp_path, {"amount_safe_to_pay": "900"})
    assert any("exceeds" in e for e in errors)


def test_not_recommended_must_be_not_affordable(tmp_path):
    errors = _errors(tmp_path, {
        "recommended_payment_method": "not_recommended",
        "payment_plan": "none",
        "affordability_status": "affordable_now",
    })
    assert any("requires status" in e for e in errors)


def test_not_recommended_must_not_carry_a_plan(tmp_path):
    errors = _errors(tmp_path, {
        "recommended_payment_method": "not_recommended",
        "affordability_status": "not_affordable",
    })
    assert any("must have payment_plan 'none'" in e for e in errors)


def test_partial_payment_requires_exactly_two_legs(tmp_path):
    errors = _errors(tmp_path, {
        "recommended_payment_method": "partial_payment",
        "affordability_status": "affordable_with_plan",
        "payment_plan": "2025-01-15:500",
    })
    assert any("exactly 2 payments" in e for e in errors)


def test_installments_require_at_least_two_legs(tmp_path):
    errors = _errors(tmp_path, {
        "recommended_payment_method": "installments",
        "affordability_status": "affordable_with_plan",
        "payment_plan": "2025-01-15:500",
    })
    assert any("at least 2 payments" in e for e in errors)


def test_payment_before_request_date_is_rejected(tmp_path):
    errors = _errors(tmp_path, {"payment_plan": "2025-01-01:500",
                                "affordability_status": "affordable_with_plan",
                                "recommended_payment_method": "wait"})
    assert any("before request_date" in e for e in errors)


def test_wait_must_be_after_request_date(tmp_path):
    errors = _errors(tmp_path, {"recommended_payment_method": "wait",
                                "affordability_status": "affordable_later"})
    assert any("on/before the request date" in e for e in errors)


def test_out_of_order_plan_dates_are_rejected(tmp_path):
    errors = _errors(tmp_path, {
        "recommended_payment_method": "partial_payment",
        "affordability_status": "affordable_with_plan",
        "payment_plan": "2025-02-10:250|2025-01-20:250",
    })
    assert any("chronological" in e for e in errors)


def test_non_positive_payment_amount_is_rejected(tmp_path):
    errors = _errors(tmp_path, {
        "recommended_payment_method": "partial_payment",
        "affordability_status": "affordable_with_plan",
        "payment_plan": "2025-01-15:500|2025-01-20:0",
    })
    assert any("non-positive" in e for e in errors)


def test_affordable_now_cannot_require_spending_changes(tmp_path):
    errors = _errors(tmp_path, {"spending_changes_needed": "stop:e1"})
    assert any("contradicts required spending changes" in e for e in errors)


def test_too_many_spending_changes_rejected(tmp_path):
    errors = _errors(tmp_path, {
        "affordability_status": "affordable_with_plan",
        "spending_changes_needed": "stop:e1|stop:e2|stop:e3|stop:e4",
    })
    assert any("exceeds the maximum" in e for e in errors)


def test_unknown_spending_change_kind_rejected(tmp_path):
    errors = _errors(tmp_path, {
        "affordability_status": "affordable_with_plan",
        "spending_changes_needed": "delete:e1",
    })
    assert any("unknown spending change kind" in e for e in errors)


def test_malformed_reduce_to_change_rejected(tmp_path):
    errors = _errors(tmp_path, {
        "affordability_status": "affordable_with_plan",
        "spending_changes_needed": "reduce_to:e1:abc",
    })
    assert any("non-numeric" in e for e in errors)


def test_header_mismatch_is_detected(tmp_path):
    out = tmp_path / "output.csv"
    out.write_text("request_id,wrong\nr1,x\n", encoding="utf-8")
    req = tmp_path / "requests.csv"
    with open(req, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(REQUEST_ROW.keys()))
        w.writeheader()
        w.writerow(REQUEST_ROW)
    errors = evaluation.validate_structure(str(out), str(req))
    assert any("Header mismatch" in e for e in errors)


def test_plan_parser_returns_none_on_bad_leg():
    assert evaluation._parse_plan("2025-01-15:abc") is None
    assert evaluation._parse_plan("none") == []
    assert evaluation._parse_plan("2025-01-15:10|2025-02-15:20") == [
        (__import__("datetime").date(2025, 1, 15), 10.0),
        (__import__("datetime").date(2025, 2, 15), 20.0),
    ]


def test_safety_validation_flags_an_unsafe_plan(tmp_path):
    """End-to-end: an output claiming a payment that breaches the minimum
    balance must be rejected by the forecast re-simulation."""
    demo_dir = os.path.join(BACKEND_DIR, "demo_data")
    requests_path = os.path.join(demo_dir, "requests.csv")
    with open(requests_path, newline="", encoding="utf-8") as f:
        reqs = list(csv.DictReader(f))

    # Build an output that pays every request in full on the request date.
    rows = []
    for r in reqs:
        rows.append({
            "request_id": r["request_id"],
            "amount_safe_to_pay": r["requested_amount"],
            "affordability_status": "affordable_now",
            "recommended_payment_method": "full_payment",
            "payment_plan": f"{r['request_date']}:{r['requested_amount']}",
            "earliest_date_for_full_payment": r["request_date"],
            "spending_changes_needed": "none",
            "decision_explanation": "forced",
        })
    out = tmp_path / "forced.csv"
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)

    errors = evaluation.validate_safety(str(out), requests_path, demo_dir)
    assert any("minimum balance" in e for e in errors), \
        "paying every demo request in full today should breach at least one minimum balance"
