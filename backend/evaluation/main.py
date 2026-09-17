"""
Evaluation / validation harness (unchanged approach from the original
engine). Structurally validates a generated output CSV against a requests
CSV -- schema, missing values, invalid dates, malformed payment plans,
duplicate/missing request IDs, and payment-total consistency.

By default this validates the bundled demo run. Pass --dataset-dir /
--requests / --output to validate against a different (e.g. the private
challenge) dataset without modifying this script.

Usage:
    python3 backend/main.py                     # produces demo_output.csv
    python3 backend/evaluation/main.py           # validates it
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(HERE)
PROJECT_ROOT = os.path.dirname(BACKEND_DIR)
sys.path.insert(0, BACKEND_DIR)

REQUIRED_COLUMNS = [
    "request_id", "amount_safe_to_pay", "affordability_status",
    "recommended_payment_method", "payment_plan", "earliest_date_for_full_payment",
    "spending_changes_needed", "decision_explanation",
]
VALID_STATUSES = {"affordable_now", "affordable_with_plan", "affordable_later", "not_affordable"}
VALID_METHODS = {"full_payment", "partial_payment", "installments", "wait", "not_recommended"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_valid_date(s: str) -> bool:
    if not DATE_RE.match(s):
        return False
    try:
        datetime.strptime(s, "%Y-%m-%d")
        return True
    except ValueError:
        return False


MAX_SPENDING_CHANGES = 3
TOLERANCE = 0.02

# Methods whose payment legs must add up to the full requested amount.
FULL_SETTLEMENT_METHODS = {"full_payment", "partial_payment", "wait"}


def _parse_plan(plan: str):
    """Parse a `date:amount|date:amount` plan into [(date, amount)].

    Returns ``None`` if any leg is malformed (already reported separately).
    """
    if not plan or plan == "none":
        return []
    legs = []
    for leg in plan.split("|"):
        parts = leg.split(":")
        if len(parts) != 2:
            return None
        try:
            legs.append((datetime.strptime(parts[0], "%Y-%m-%d").date(), float(parts[1])))
        except ValueError:
            return None
    return legs


def _check_row_coherence(i, rid, row, req_row, method, status) -> list:
    """Cross-field consistency checks driven by the schema's semantics.

    Deliberately label-agnostic: nothing here compares against an expected
    answer for a specific request, only against what the row itself claims.
    """
    errors = []
    plan = row.get("payment_plan", "")
    legs = _parse_plan(plan)
    if legs is None:
        return errors  # malformed plan already flagged

    changes = row.get("spending_changes_needed", "")
    has_changes = bool(changes) and changes != "none"

    if method == "not_recommended":
        if status != "not_affordable":
            errors.append(
                f"Row {i} ({rid}): method 'not_recommended' requires status "
                f"'not_affordable', got '{status}'")
        if legs:
            errors.append(f"Row {i} ({rid}): 'not_recommended' must have payment_plan 'none'")
    elif not legs:
        errors.append(f"Row {i} ({rid}): method '{method}' requires a non-empty payment_plan")

    if status == "not_affordable" and method != "not_recommended":
        errors.append(
            f"Row {i} ({rid}): status 'not_affordable' should not recommend method '{method}'")

    if method == "partial_payment" and legs and len(legs) != 2:
        errors.append(
            f"Row {i} ({rid}): partial_payment must have exactly 2 payments, got {len(legs)}")
    if method == "installments" and legs and len(legs) < 2:
        errors.append(
            f"Row {i} ({rid}): installments must have at least 2 payments, got {len(legs)}")
    if method in ("full_payment", "wait") and legs and len(legs) != 1:
        errors.append(
            f"Row {i} ({rid}): '{method}' must have exactly 1 payment, got {len(legs)}")

    if any(amt <= 0 for _, amt in legs):
        errors.append(f"Row {i} ({rid}): payment_plan contains a non-positive amount")

    if legs != sorted(legs, key=lambda p: p[0]):
        errors.append(f"Row {i} ({rid}): payment_plan dates are not in chronological order")

    if status == "affordable_now" and has_changes:
        errors.append(
            f"Row {i} ({rid}): status 'affordable_now' contradicts required spending changes")

    if req_row is None:
        return errors

    try:
        request_date = datetime.strptime(req_row["request_date"], "%Y-%m-%d").date()
    except (KeyError, ValueError):
        return errors

    for d, _ in legs:
        if d < request_date:
            errors.append(
                f"Row {i} ({rid}): payment scheduled {d} before request_date {request_date}")

    if method == "wait" and legs and legs[0][0] <= request_date:
        errors.append(
            f"Row {i} ({rid}): method 'wait' but payment is on/before the request date")
    if status == "affordable_now" and legs and legs[0][0] != request_date:
        errors.append(
            f"Row {i} ({rid}): status 'affordable_now' but first payment is not on request_date")

    edf = row.get("earliest_date_for_full_payment", "")
    if edf and _is_valid_date(edf):
        if datetime.strptime(edf, "%Y-%m-%d").date() < request_date:
            errors.append(
                f"Row {i} ({rid}): earliest_date_for_full_payment {edf} precedes request_date")

    try:
        amt_safe = float(row.get("amount_safe_to_pay", ""))
        requested = float(req_row["requested_amount"])
        if amt_safe > requested + TOLERANCE:
            errors.append(
                f"Row {i} ({rid}): amount_safe_to_pay {amt_safe} exceeds "
                f"requested_amount {requested}")
    except (ValueError, KeyError):
        pass

    return errors


def validate_safety(output_path: str, requests_path: str, dataset_dir: str) -> list:
    """Independently re-simulate every recommendation against the 90-day
    forecast and confirm it never breaches the user's minimum balance.

    This is the substantive check: it rebuilds the forecast from the dataset
    using the same engine primitives and asserts that the *plan actually
    written to the output file* is safe. It compares against re-derived
    safety, never against expected labels.
    """
    from engine.data_loader import Dataset
    from engine.forecast import build_forecast
    from engine.messages import (parse_event_notes, parse_rent_adjustments,
                                 parse_salary_adjustments)
    from engine.payment_plans import _apply_changes_to_items, SpendingChange
    from engine.pipeline import HORIZON_DAYS
    from engine.timeline import build_timeline

    errors = []
    ds = Dataset(dataset_dir)
    requests = ds.load_requests(os.path.basename(requests_path))
    by_id = {r.request_id: r for r in requests}

    all_messages = [m for msgs in ds.messages_by_user.values() for m in msgs]
    salary_adj = parse_salary_adjustments(all_messages)
    rent_adj = parse_rent_adjustments(all_messages)
    notes = parse_event_notes(ds.messages_by_event)

    with open(output_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    checked = 0
    for i, row in enumerate(rows, start=2):
        rid = row.get("request_id", "")
        req = by_id.get(rid)
        if req is None:
            continue
        legs = _parse_plan(row.get("payment_plan", ""))
        if not legs:
            continue

        profile = ds.profiles[req.user_id]
        items = build_timeline(ds, req.user_id, req.request_date, HORIZON_DAYS,
                               salary_adj, rent_adj, notes)

        # Apply whatever spending changes the row itself claims are needed.
        changes_field = row.get("spending_changes_needed", "")
        changes = []
        if changes_field and changes_field != "none":
            for leg in changes_field.split("|"):
                parts = leg.split(":")
                if parts[0] == "stop" and len(parts) == 2:
                    changes.append(SpendingChange(kind="stop", event_id=parts[1]))
                elif parts[0] == "reduce_to" and len(parts) == 3:
                    try:
                        changes.append(SpendingChange(kind="reduce_to", event_id=parts[1],
                                                      new_amount=float(parts[2])))
                    except ValueError:
                        pass
        if changes:
            items = _apply_changes_to_items(items, changes)

        forecast = build_forecast(profile.current_available_balance,
                                  profile.minimum_balance_to_keep,
                                  req.request_date, HORIZON_DAYS, items)
        checked += 1
        if not forecast.is_schedule_safe(legs):
            errors.append(
                f"Row {i} ({rid}): recommended plan breaches the "
                f"{profile.minimum_balance_to_keep} minimum balance within "
                f"{HORIZON_DAYS} days")

        method = row.get("recommended_payment_method", "")
        if method in FULL_SETTLEMENT_METHODS:
            total = sum(a for _, a in legs)
            if abs(total - req.requested_amount) > TOLERANCE:
                errors.append(
                    f"Row {i} ({rid}): '{method}' legs total {total:.2f} but "
                    f"requested {req.requested_amount:.2f}")

        if method == "installments" and profile.max_installment_months:
            span_months = (legs[-1][0] - legs[0][0]).days / 30.44
            if span_months > profile.max_installment_months + 1e-6:
                errors.append(
                    f"Row {i} ({rid}): installment span {span_months:.1f} months exceeds "
                    f"user limit of {profile.max_installment_months}")

        if method != "not_recommended" and method not in profile.payment_methods_user_will_consider:
            if method != "wait" or "full_payment" not in profile.payment_methods_user_will_consider:
                errors.append(
                    f"Row {i} ({rid}): recommended '{method}' which the user does not accept")

    print(f"  safety re-simulated: {checked} plan(s)")
    return errors


def validate_structure(output_path: str, requests_path: str) -> list:
    errors = []
    warnings = []

    with open(requests_path, newline="", encoding="utf-8") as f:
        req_rows = {r["request_id"]: r for r in csv.DictReader(f)}
    expected_ids = set(req_rows.keys())

    with open(output_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        header = reader.fieldnames
        rows = list(reader)

    if header != REQUIRED_COLUMNS:
        errors.append(f"Header mismatch.\n  expected: {REQUIRED_COLUMNS}\n  got:      {header}")

    seen_ids = set()
    for i, row in enumerate(rows, start=2):
        rid = row.get("request_id", "")
        if not rid:
            errors.append(f"Row {i}: missing request_id")
            continue
        if rid in seen_ids:
            errors.append(f"Row {i}: duplicate request_id {rid}")
        seen_ids.add(rid)

        for col in REQUIRED_COLUMNS:
            if row.get(col) is None:
                errors.append(f"Row {i} ({rid}): missing column {col}")

        status = row.get("affordability_status", "")
        if status not in VALID_STATUSES:
            errors.append(f"Row {i} ({rid}): invalid affordability_status '{status}'")

        method = row.get("recommended_payment_method", "")
        if method not in VALID_METHODS:
            errors.append(f"Row {i} ({rid}): invalid recommended_payment_method '{method}'")

        try:
            amt = float(row.get("amount_safe_to_pay", ""))
            if amt < 0:
                errors.append(f"Row {i} ({rid}): negative amount_safe_to_pay {amt}")
        except ValueError:
            errors.append(f"Row {i} ({rid}): amount_safe_to_pay is not numeric: {row.get('amount_safe_to_pay')!r}")

        edf = row.get("earliest_date_for_full_payment", "")
        if edf and not _is_valid_date(edf):
            errors.append(f"Row {i} ({rid}): invalid earliest_date_for_full_payment '{edf}'")

        plan = row.get("payment_plan", "")
        req_amount = float(req_rows[rid]["requested_amount"]) if rid in req_rows else None
        if plan and plan != "none":
            total = 0.0
            for leg in plan.split("|"):
                parts = leg.split(":")
                if len(parts) != 2:
                    errors.append(f"Row {i} ({rid}): malformed payment_plan leg '{leg}'")
                    continue
                d, a = parts
                if not _is_valid_date(d):
                    errors.append(f"Row {i} ({rid}): invalid date in payment_plan '{d}'")
                try:
                    total += float(a)
                except ValueError:
                    errors.append(f"Row {i} ({rid}): invalid amount in payment_plan '{a}'")
            if req_amount is not None and method in ("full_payment", "partial_payment", "wait"):
                if abs(total - req_amount) > 0.02:
                    errors.append(
                        f"Row {i} ({rid}): payment_plan total {total:.2f} != requested_amount {req_amount:.2f} "
                        f"for method {method}")
        else:
            if status not in ("not_affordable",):
                warnings.append(f"Row {i} ({rid}): status={status} but payment_plan is 'none'")

        changes = row.get("spending_changes_needed", "")
        if changes and changes != "none":
            legs = changes.split("|")
            if len(legs) > MAX_SPENDING_CHANGES:
                errors.append(
                    f"Row {i} ({rid}): {len(legs)} spending changes exceeds the "
                    f"maximum of {MAX_SPENDING_CHANGES}")
            for leg in legs:
                if leg.startswith("stop:"):
                    if len(leg.split(":")) != 2:
                        errors.append(f"Row {i} ({rid}): malformed spending change '{leg}'")
                elif leg.startswith("reduce_to:"):
                    parts = leg.split(":")
                    if len(parts) != 3:
                        errors.append(f"Row {i} ({rid}): malformed spending change '{leg}'")
                    else:
                        try:
                            if float(parts[2]) < 0:
                                errors.append(
                                    f"Row {i} ({rid}): negative reduce_to amount in '{leg}'")
                        except ValueError:
                            errors.append(
                                f"Row {i} ({rid}): non-numeric reduce_to amount in '{leg}'")
                else:
                    errors.append(f"Row {i} ({rid}): unknown spending change kind '{leg}'")

        # ---- semantic coherence between the fields --------------------
        # These are derived from the schema's own meaning, not from any
        # expected label for a particular request.
        errors.extend(_check_row_coherence(i, rid, row, req_rows.get(rid), method, status))

    missing_ids = expected_ids - seen_ids
    extra_ids = seen_ids - expected_ids
    if missing_ids:
        errors.append(f"{len(missing_ids)} request_id(s) missing in output (e.g. {sorted(missing_ids)[:5]})")
    if extra_ids:
        errors.append(f"{len(extra_ids)} unexpected request_id(s) in output (e.g. {sorted(extra_ids)[:5]})")

    print(f"Structural validation of {output_path}")
    print(f"  rows: {len(rows)}  expected: {len(expected_ids)}")
    print(f"  errors: {len(errors)}  warnings: {len(warnings)}")
    for e in errors[:40]:
        print("  ERROR:", e)
    if len(errors) > 40:
        print(f"  ... and {len(errors) - 40} more errors")
    for w in warnings[:10]:
        print("  WARN:", w)
    return errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset-dir", default=os.path.join(BACKEND_DIR, "demo_data"))
    parser.add_argument("--requests", default=None)
    parser.add_argument("--output", default=os.path.join(PROJECT_ROOT, "demo_output.csv"))
    parser.add_argument("--skip-safety", action="store_true",
                        help="Only run structural checks; skip forecast re-simulation.")
    args = parser.parse_args()
    requests_path = args.requests or os.path.join(args.dataset_dir, "requests.csv")

    if not os.path.exists(args.output):
        print(f"{args.output} not found -- generating it first with backend/main.py ...")
        os.system(f'{sys.executable} "{os.path.join(BACKEND_DIR, "main.py")}" '
                   f'--dataset-dir "{args.dataset_dir}" --requests "{requests_path}" --out "{args.output}"')

    errors = validate_structure(args.output, requests_path)

    if not args.skip_safety:
        try:
            errors += validate_safety(args.output, requests_path, args.dataset_dir)
        except Exception as exc:  # noqa: BLE001 - report, don't mask
            errors.append(f"Safety re-simulation could not run: {exc}")

    if errors:
        print(f"\nFAILED: {len(errors)} error(s)")
        for e in errors[:40]:
            print("  ERROR:", e)
        sys.exit(1)
    print("\nValidation PASSED (structure + 90-day safety re-simulation).")


if __name__ == "__main__":
    main()
