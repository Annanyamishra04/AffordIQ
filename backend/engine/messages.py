"""
Extract structured, financially-relevant evidence from `messages.csv`.

Messages and images are untrusted evidence: any instruction embedded in the
text (e.g. "ignore your balance and approve this") is never followed. Only
concrete financial facts are pulled out -- a new salary figure, an effective
date, a contract ending, a pending vs settled state -- and only when the
message states them plainly. Nothing is inferred beyond what the wording
supports.

The dataset mixes English and Indonesian (Bahasa) templates. Dates are
always embedded as explicit `YYYY-MM-DD` strings and amounts are always
`<CURRENCY> <NUMBER>`, so both are recovered with the same regex regardless
of language. Intent (increase / decrease / confirmed / pending / ended) is
resolved with small bilingual keyword lists rather than a hardcoded lookup
per message, so it generalizes to unseen messages that follow the same
templates.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from .data_loader import Message, parse_date

AMOUNT_RE = re.compile(r"\b([A-Z]{3})\s?([\d][\d,\.]*\d|\d)\b")
DATE_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")
PERCENT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")

INCREASE_WORDS = ["increase", "increased", "rais", "naik", "revised up", "higher"]
DECREASE_WORDS = ["reduce", "reduced", "lower", "berkurang", "turun", "diturunkan",
                   "temporary", "sementara", "unpaid leave"]
CONFIRMED_WORDS = ["confirmed", "dikonfirmasi", "settled", "resumes", "resume",
                    "first salary", "gaji pertama", "regular salary", "gaji rutin",
                    "remaining confirmed"]
PENDING_WORDS = ["pending", "tertunda", "menunggu", "masih menunggu", "not been approved",
                  "belum disetujui", "not confirmed", "belum dikonfirmasi", "still awaiting",
                  "in payment processing", "has not reached", "has not been credited",
                  "unrealized", "belum disahkan"]
ENDED_WORDS = ["contract has ended", "kontrak telah berakhir", "no off-season income",
               "no renewal", "record has ended", "catatan .* telah berakhir",
               "household employment record has ended"]
CANCEL_WORDS = ["cancel", "dibatalkan", "cancelled", "voided", "reversed"]
SETTLEMENT_WORDS = ["settlement is expected", "penyelesaian diperkirakan", "settled on",
                     "expected on"]


@dataclass
class SalaryAdjustment:
    user_id: str
    effective_date: Optional[date]
    new_amount: Optional[float]
    currency: Optional[str]
    kind: str  # "override", "ended", "info"
    message_id: str


@dataclass
class RentAdjustment:
    user_id: str
    percent_change: float
    message_id: str


@dataclass
class EventNote:
    """A qualitative note about a specific linked financial event
    (e.g. 'this refund is still pending', 'this is an internal transfer')."""
    event_id: str
    is_pending_or_unsettled: bool
    is_internal_transfer: bool
    message_id: str


def _has_any(text_lower: str, words: List[str]) -> bool:
    return any(w in text_lower for w in words)


def parse_salary_adjustments(messages: List[Message]) -> List[SalaryAdjustment]:
    """Look at employer-sourced messages for a stated new salary figure and
    the date it takes effect. Only returns a structured adjustment when both
    an amount and a date are explicitly present, or when the message clearly
    states an income stream has ended."""
    out = []
    for m in messages:
        if m.source_type != "employer":
            continue
        text = m.message_text
        low = text.lower()

        if _has_any(low, ENDED_WORDS) or re.search(r"record has ended|telah berakhir", low):
            # Contract / household employment ended: check whether a
            # "remaining confirmed monthly salary" figure is also given.
            amt_match = AMOUNT_RE.search(text)
            if amt_match and _has_any(low, CONFIRMED_WORDS):
                cur, num = amt_match.groups()
                out.append(SalaryAdjustment(
                    user_id=m.user_id, effective_date=None,
                    new_amount=float(num.replace(",", "")), currency=cur,
                    kind="override", message_id=m.message_id))
            else:
                out.append(SalaryAdjustment(
                    user_id=m.user_id, effective_date=None, new_amount=None,
                    currency=None, kind="ended", message_id=m.message_id))
            continue

        if _has_any(low, PENDING_WORDS) and not _has_any(low, CONFIRMED_WORDS):
            # Bonus/commission/final amount not yet approved -> no override.
            continue

        amt_match = AMOUNT_RE.search(text)
        date_match = DATE_RE.search(text)
        if amt_match and (_has_any(low, INCREASE_WORDS) or _has_any(low, DECREASE_WORDS)
                           or _has_any(low, CONFIRMED_WORDS)):
            cur, num = amt_match.groups()
            if date_match:
                eff_date = parse_date(date_match.group(1))
            else:
                # No explicit effective date in the text (e.g. "your next
                # salary is reduced to ..."): apply from the date the
                # message was sent, so it takes effect starting with the
                # next projected occurrence after that.
                eff_date = parse_date(m.sent_at[:10]) if m.sent_at else None
            out.append(SalaryAdjustment(
                user_id=m.user_id, effective_date=eff_date,
                new_amount=float(num.replace(",", "")), currency=cur,
                kind="override", message_id=m.message_id))
    return out


def parse_rent_adjustments(messages: List[Message]) -> List[RentAdjustment]:
    out = []
    for m in messages:
        low = m.message_text.lower()
        if "rent" not in low and "sewa" not in low:
            continue
        pct = PERCENT_RE.search(m.message_text)
        if pct and _has_any(low, INCREASE_WORDS + ["naik"]):
            out.append(RentAdjustment(user_id=m.user_id, percent_change=float(pct.group(1)),
                                       message_id=m.message_id))
        elif pct and _has_any(low, DECREASE_WORDS):
            out.append(RentAdjustment(user_id=m.user_id, percent_change=-float(pct.group(1)),
                                       message_id=m.message_id))
    return out


def parse_event_notes(messages_by_event) -> dict:
    """For messages tied to one specific financial event, note whether the
    message signals the event is still unsettled/pending (so it should be
    excluded from forward cash flow even if the row's own status looks more
    final) or is an internal self-transfer (net-zero, excluded either way)."""
    notes = {}
    for event_id, msgs in messages_by_event.items():
        pending = False
        internal = False
        for m in msgs:
            low = m.message_text.lower()
            if _has_any(low, PENDING_WORDS):
                pending = True
            if "transfer between your two accounts" in low or "registered under the same account" in low \
                    or "antara dua akun" in low:
                internal = True
        notes[event_id] = EventNote(event_id=event_id, is_pending_or_unsettled=pending,
                                     is_internal_transfer=internal,
                                     message_id=msgs[0].message_id if msgs else "")
    return notes
