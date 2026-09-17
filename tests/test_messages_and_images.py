import json
import os
import sys

import pytest
from datetime import date

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine.messages import parse_salary_adjustments, parse_rent_adjustments, parse_event_notes
from engine.data_loader import Dataset, Message
from engine import image_evidence  # noqa: E402
from engine.image_evidence import (  # noqa: E402
    EvidenceResolutionError,
    ImageEvidenceResolver,
    load_evidence_sidecar,
)


def _msg(user_id="u1", source_type="employer", text="", sent_at="2025-01-06T09:00:00Z",
          message_id="m1", request_id=None, related_event_id=None):
    return Message(message_id=message_id, user_id=user_id, request_id=request_id,
                    related_event_id=related_event_id, sent_at=sent_at, source_type=source_type,
                    message_text=text)


def test_salary_override_with_explicit_date_is_parsed():
    msgs = [_msg(text="Your salary is increased to USD 3200.00 effective 2025-02-01.")]
    adj = parse_salary_adjustments(msgs)
    assert len(adj) == 1
    assert adj[0].new_amount == 3200.00
    assert adj[0].currency == "USD"
    assert adj[0].effective_date == date(2025, 2, 1)
    assert adj[0].kind == "override"


def test_salary_override_without_explicit_date_falls_back_to_sent_at():
    msgs = [_msg(text="Your next salary is reduced to EUR 1422.85 due to approved unpaid leave.",
                  sent_at="2025-02-06T09:30:00Z")]
    adj = parse_salary_adjustments(msgs)
    assert len(adj) == 1
    assert adj[0].effective_date == date(2025, 2, 6)


def test_pending_bonus_is_not_treated_as_a_salary_override():
    msgs = [_msg(text="Your annual bonus of USD 1500.00 is still pending manager approval.")]
    adj = parse_salary_adjustments(msgs)
    assert adj == []


def test_contract_ended_stops_future_salary_projection():
    msgs = [_msg(text="Your seasonal contract has ended and will not be renewed.")]
    adj = parse_salary_adjustments(msgs)
    assert len(adj) == 1
    assert adj[0].kind == "ended"


def test_non_employer_messages_never_produce_salary_overrides():
    msgs = [_msg(source_type="merchant", text="Your order total is USD 3200.00, effective immediately.")]
    adj = parse_salary_adjustments(msgs)
    assert adj == []


def test_rent_increase_percentage_parsed():
    msgs = [_msg(source_type="service_provider",
                  text="Your renewed lease increases monthly rent by 12%.")]
    adj = parse_rent_adjustments(msgs)
    assert len(adj) == 1
    assert adj[0].percent_change == 12.0


def test_event_note_flags_pending_language_and_internal_transfer():
    msgs_by_event = {
        "evA": [_msg(text="This refund is still pending and has not been credited yet.",
                      related_event_id="evA")],
        "evB": [_msg(text="This matching debit and credit came from a transfer between your two accounts.",
                      related_event_id="evB")],
    }
    notes = parse_event_notes(msgs_by_event)
    assert notes["evA"].is_pending_or_unsettled is True
    assert notes["evB"].is_internal_transfer is True


def _write_sidecar(tmp_path, payload):
    path = tmp_path / "image_evidence.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return str(tmp_path)


def test_resolver_reads_amount_from_sidecar(tmp_path):
    ds_dir = _write_sidecar(tmp_path, {
        "ev_1": {"amount": 1234.56, "currency": "USD", "source_field": "Total"}
    })
    resolver = ImageEvidenceResolver(ds_dir)
    assert resolver.resolve("ev_1", "USD") == 1234.56


def test_resolver_accepts_bare_number_entries(tmp_path):
    ds_dir = _write_sidecar(tmp_path, {"ev_1": 99.5})
    assert ImageEvidenceResolver(ds_dir).resolve("ev_1", "USD") == 99.5


def test_resolver_raises_on_currency_mismatch(tmp_path):
    ds_dir = _write_sidecar(tmp_path, {"ev_1": {"amount": 10.0, "currency": "IDR"}})
    with pytest.raises(EvidenceResolutionError):
        ImageEvidenceResolver(ds_dir).resolve("ev_1", "USD")


def test_resolver_never_defaults_a_blank_amount_to_zero(tmp_path):
    """A blank amount must fail loudly: silently using 0 would understate a
    debit and could make an unsafe payment look safe."""
    ds_dir = _write_sidecar(tmp_path, {})
    with pytest.raises(EvidenceResolutionError):
        ImageEvidenceResolver(ds_dir).resolve("unknown_event", "USD")


def test_missing_sidecar_yields_empty_mapping_not_an_error(tmp_path, monkeypatch):
    """With no sidecar anywhere on the search path, loading returns an empty
    mapping rather than raising -- datasets with no blank amounts must load
    fine without any evidence file."""
    monkeypatch.delenv("BUY_OR_WAIT_IMAGE_EVIDENCE", raising=False)
    monkeypatch.setattr(image_evidence, "_project_root", lambda: str(tmp_path))
    assert load_evidence_sidecar(str(tmp_path / "nope")) == {}


def test_malformed_sidecar_entry_is_rejected(tmp_path):
    ds_dir = _write_sidecar(tmp_path, {"ev_1": {"no_amount": 1}})
    with pytest.raises(EvidenceResolutionError):
        load_evidence_sidecar(ds_dir)


def test_dataset_loader_resolves_blank_amount_via_sidecar(tmp_path):
    """End-to-end: a blank `amount` column is filled from image evidence and
    the event is flagged as image-derived."""
    ds_dir = tmp_path / "ds"
    ds_dir.mkdir()
    (ds_dir / "financial_profiles.csv").write_text(
        "user_id,home_currency,current_available_balance,minimum_balance_to_keep,"
        "financial_priorities,expense_categories_to_protect,"
        "expense_categories_user_is_willing_to_reduce,"
        "expense_categories_user_is_willing_to_stop,"
        "payment_methods_user_will_consider,max_installment_months\n"
        "u1,USD,1000,100,savings,rent,dining,streaming,full_payment,6\n", encoding="utf-8")
    (ds_dir / "exchange_rates.csv").write_text(
        "rate_date,from_currency,to_currency,rate\n", encoding="utf-8")
    (ds_dir / "financial_events.csv").write_text(
        "event_id,user_id,event_type,description,category,direction,amount,currency,"
        "event_date,settlement_date,status,linked_event_id,flexibility,minimum_allowed_amount\n"
        "e1,u1,expense,Receipt,groceries,debit,,USD,2025-01-01,2025-01-01,settled,,fixed,\n",
        encoding="utf-8")
    (ds_dir / "images.csv").write_text(
        "image_id,user_id,request_id,related_event_id\nimg1,u1,,e1\n", encoding="utf-8")
    (ds_dir / "messages.csv").write_text(
        "message_id,user_id,request_id,related_event_id,sent_at,source_type,message_text\n",
        encoding="utf-8")
    (ds_dir / "request_payment_options.csv").write_text(
        "payment_option_id,request_id,payment_method,payment_amount,number_of_payments,"
        "first_payment_date,payment_frequency_days,financing_fee,total_payable_amount\n",
        encoding="utf-8")
    (ds_dir / "image_evidence.json").write_text(
        json.dumps({"e1": {"amount": 250.0, "currency": "USD"}}), encoding="utf-8")

    ds = Dataset(str(ds_dir))
    ev = ds.events_by_id["e1"]
    assert ev.amount == 250.0
    assert ev.amount_was_from_image is True


def test_ocr_regex_prefers_grand_total_over_line_items():
    from engine.image_evidence import _OCR_AMOUNT_RE
    text = "Item A 10.00\nSubtotal 20.00\nGrand Total 1,234.50\n"
    matches = _OCR_AMOUNT_RE.findall(text)
    assert matches[-1].replace(",", "") == "1234.50"
