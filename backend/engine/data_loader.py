"""Load and lightly normalize every dataset/*.csv file."""
from __future__ import annotations

import csv
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional

from .image_evidence import ImageEvidenceResolver


def parse_date(s: str) -> Optional[date]:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    return datetime.strptime(s[:10], "%Y-%m-%d").date()


def parse_float(s: str) -> Optional[float]:
    if s is None:
        return None
    s = s.strip()
    if s == "":
        return None
    return float(s)


def parse_bool(s: str) -> bool:
    return str(s).strip().lower() in ("true", "1", "yes")


@dataclass
class Profile:
    user_id: str
    home_currency: str
    current_available_balance: float
    minimum_balance_to_keep: float
    financial_priorities: List[str]
    protect: List[str]
    willing_reduce: List[str]
    willing_stop: List[str]
    payment_methods_user_will_consider: List[str]
    max_installment_months: Optional[float]


@dataclass
class Event:
    event_id: str
    user_id: str
    event_type: str
    description: str
    category: str
    direction: str
    amount: float
    currency: str
    event_date: Optional[date]
    settlement_date: Optional[date]
    status: str
    linked_event_id: Optional[str]
    flexibility: str
    minimum_allowed_amount: Optional[float]
    amount_was_from_image: bool = False


@dataclass
class Request:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: float
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str
    # ground-truth columns present only in sample_requests.csv
    gt: Optional[Dict] = None


@dataclass
class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str
    payment_amount: float
    number_of_payments: int
    first_payment_date: Optional[date]
    payment_frequency_days: Optional[int]
    financing_fee: float
    total_payable_amount: float


@dataclass
class Message:
    message_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]
    sent_at: str
    source_type: str
    message_text: str


@dataclass
class ImageRecord:
    image_id: str
    user_id: str
    request_id: Optional[str]
    related_event_id: Optional[str]


class Dataset:
    def __init__(self, dataset_dir: str):
        self.dataset_dir = dataset_dir
        self.media_dir = os.path.join(dataset_dir, "media", "images")

        self.profiles: Dict[str, Profile] = {}
        self.events_by_user: Dict[str, List[Event]] = defaultdict(list)
        self.events_by_id: Dict[str, Event] = {}
        self.exchange_rates: Dict = {}
        self.requests: Dict[str, Request] = {}
        self.request_order: List[str] = []
        self.payment_options_by_request: Dict[str, List[PaymentOption]] = defaultdict(list)
        self.messages_by_user: Dict[str, List[Message]] = defaultdict(list)
        self.messages_by_request: Dict[str, List[Message]] = defaultdict(list)
        self.messages_by_event: Dict[str, List[Message]] = defaultdict(list)
        self.images_by_event: Dict[str, ImageRecord] = {}

        self.evidence = ImageEvidenceResolver(dataset_dir, self.media_dir)

        self._load_profiles()
        self._load_exchange_rates()
        self._load_images()  # must precede events: supplies image_id for blank amounts
        self._load_events()
        self._load_messages()
        self._load_payment_options()

    # ---- profiles -----------------------------------------------------
    def _load_profiles(self):
        path = os.path.join(self.dataset_dir, "financial_profiles.csv")
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pipe = lambda s: [x for x in s.split("|") if x] if s else []
                self.profiles[row["user_id"]] = Profile(
                    user_id=row["user_id"],
                    home_currency=row["home_currency"],
                    current_available_balance=parse_float(row["current_available_balance"]) or 0.0,
                    minimum_balance_to_keep=parse_float(row["minimum_balance_to_keep"]) or 0.0,
                    financial_priorities=pipe(row["financial_priorities"]),
                    protect=pipe(row["expense_categories_to_protect"]),
                    willing_reduce=pipe(row["expense_categories_user_is_willing_to_reduce"]),
                    willing_stop=pipe(row["expense_categories_user_is_willing_to_stop"]),
                    payment_methods_user_will_consider=pipe(row["payment_methods_user_will_consider"]),
                    max_installment_months=parse_float(row["max_installment_months"]),
                )

    # ---- exchange rates -------------------------------------------------
    def _load_exchange_rates(self):
        path = os.path.join(self.dataset_dir, "exchange_rates.csv")
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                key = (row["rate_date"], row["from_currency"], row["to_currency"])
                self.exchange_rates[key] = float(row["rate"])

    def convert(self, amount: float, from_currency: str, to_currency: str, on_date: date) -> float:
        if from_currency == to_currency:
            return amount
        ds = on_date.strftime("%Y-%m-%d")
        key = (ds, from_currency, to_currency)
        if key in self.exchange_rates:
            return amount * self.exchange_rates[key]
        inv_key = (ds, to_currency, from_currency)
        if inv_key in self.exchange_rates:
            return amount / self.exchange_rates[inv_key]
        # Fall back to nearest available date for that currency pair
        # (defensive only -- the shipped dataset always has an exact match).
        candidates = [
            (d, r) for (d, f, t), r in self.exchange_rates.items()
            if f == from_currency and t == to_currency
        ]
        if candidates:
            candidates.sort(key=lambda dr: abs((datetime.strptime(dr[0], "%Y-%m-%d").date() - on_date).days))
            return amount * candidates[0][1]
        raise ValueError(f"No exchange rate found for {from_currency}->{to_currency} near {on_date}")

    # ---- financial events -----------------------------------------------
    def _load_events(self):
        path = os.path.join(self.dataset_dir, "financial_events.csv")
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                amt_raw = row["amount"]
                from_image = False
                if amt_raw.strip() == "":
                    # Blank amount: the figure exists only on a linked image.
                    # resolve() raises rather than defaulting to zero.
                    img = self.images_by_event.get(row["event_id"])
                    amount = self.evidence.resolve(
                        row["event_id"], row["currency"],
                        image_id=img.image_id if img else None,
                    )
                    from_image = True
                else:
                    amount = float(amt_raw)
                ev = Event(
                    event_id=row["event_id"],
                    user_id=row["user_id"],
                    event_type=row["event_type"],
                    description=row["description"],
                    category=row["category"],
                    direction=row["direction"],
                    amount=amount,
                    currency=row["currency"],
                    event_date=parse_date(row["event_date"]),
                    settlement_date=parse_date(row["settlement_date"]),
                    status=row["status"],
                    linked_event_id=row["linked_event_id"] or None,
                    flexibility=row["flexibility"],
                    minimum_allowed_amount=parse_float(row["minimum_allowed_amount"]),
                    amount_was_from_image=from_image,
                )
                self.events_by_user[ev.user_id].append(ev)
                self.events_by_id[ev.event_id] = ev
        for user_id, evs in self.events_by_user.items():
            evs.sort(key=lambda e: (e.settlement_date or e.event_date or date.min))

    # ---- images -----------------------------------------------------------
    def _load_images(self):
        path = os.path.join(self.dataset_dir, "images.csv")
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rec = ImageRecord(
                    image_id=row["image_id"],
                    user_id=row["user_id"],
                    request_id=row["request_id"] or None,
                    related_event_id=row["related_event_id"] or None,
                )
                if rec.related_event_id:
                    self.images_by_event[rec.related_event_id] = rec

    # ---- messages -----------------------------------------------------------
    def _load_messages(self):
        path = os.path.join(self.dataset_dir, "messages.csv")
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                msg = Message(
                    message_id=row["message_id"],
                    user_id=row["user_id"],
                    request_id=row["request_id"] or None,
                    related_event_id=row["related_event_id"] or None,
                    sent_at=row["sent_at"],
                    source_type=row["source_type"],
                    message_text=row["message_text"],
                )
                self.messages_by_user[msg.user_id].append(msg)
                if msg.request_id:
                    self.messages_by_request[msg.request_id].append(msg)
                if msg.related_event_id:
                    self.messages_by_event[msg.related_event_id].append(msg)

    # ---- payment options -----------------------------------------------------------
    def _load_payment_options(self):
        path = os.path.join(self.dataset_dir, "request_payment_options.csv")
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                opt = PaymentOption(
                    payment_option_id=row["payment_option_id"],
                    request_id=row["request_id"],
                    payment_method=row["payment_method"],
                    payment_amount=float(row["payment_amount"]),
                    number_of_payments=int(float(row["number_of_payments"])),
                    first_payment_date=parse_date(row["first_payment_date"]),
                    payment_frequency_days=int(float(row["payment_frequency_days"])) if row["payment_frequency_days"] else None,
                    financing_fee=parse_float(row["financing_fee"]) or 0.0,
                    total_payable_amount=parse_float(row["total_payable_amount"]) or 0.0,
                )
                self.payment_options_by_request[opt.request_id].append(opt)
        for rid in self.payment_options_by_request:
            self.payment_options_by_request[rid].sort(key=lambda o: o.payment_option_id)

    # ---- requests -----------------------------------------------------------
    def load_requests(self, filename: str, is_sample: bool = False):
        path = os.path.join(self.dataset_dir, filename)
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                gt = None
                if is_sample:
                    gt = {k: row[k] for k in (
                        "amount_safe_to_pay", "affordability_status", "recommended_payment_method",
                        "payment_plan", "earliest_date_for_full_payment", "spending_changes_needed",
                        "decision_explanation")}
                req = Request(
                    request_id=row["request_id"],
                    user_id=row["user_id"],
                    request_date=parse_date(row["request_date"]),
                    request_type=row["request_type"],
                    requested_amount=float(row["requested_amount"]),
                    desired_completion_date=parse_date(row["desired_completion_date"]),
                    allows_partial_payment=parse_bool(row["allows_partial_payment"]),
                    request_text=row.get("request_text", ""),
                    gt=gt,
                )
                self.requests[req.request_id] = req
                self.request_order.append(req.request_id)
        return [self.requests[rid] for rid in self.request_order]
