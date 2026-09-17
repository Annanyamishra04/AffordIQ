"""
Generates a small, clearly-synthetic demo dataset with the same schema as
the "Buy or Wait?" challenge dataset, so the app can be run and explored by
anyone without access to the private challenge data.

None of the numbers, names, or dates here come from the original challenge
dataset -- they are invented for this demo. Run:

    python3 backend/demo_data/generate_demo_data.py

to regenerate the CSVs in this directory.
"""
import csv
import os
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))

# Fixed "as of" anchor date for the demo history. The API treats this as
# "today" for the bundled demo users, so the demo behaves identically no
# matter when you actually run it.
ANCHOR = date(2025, 1, 15)


def month_back(d: date, n: int) -> date:
    m = d.month - 1 - n
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, 28)
    return date(y, m, day)


def write_csv(name, fieldnames, rows):
    path = os.path.join(HERE, name)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    print(f"wrote {path} ({len(rows)} rows)")


def main():
    profiles = [
        dict(user_id="demo_alex", home_currency="USD", current_available_balance=6200.00,
             minimum_balance_to_keep=1500.00, financial_priorities="debt_repayment",
             expense_categories_to_protect="rent|groceries|debt_repayment",
             expense_categories_user_is_willing_to_reduce="dining|shopping",
             expense_categories_user_is_willing_to_stop="streaming|delivery_membership",
             payment_methods_user_will_consider="full_payment|installments",
             max_installment_months=6),
        dict(user_id="demo_sam", home_currency="USD", current_available_balance=1850.00,
             minimum_balance_to_keep=900.00, financial_priorities="rent|education",
             expense_categories_to_protect="rent|groceries|education",
             expense_categories_user_is_willing_to_reduce="dining",
             expense_categories_user_is_willing_to_stop="streaming|gym",
             payment_methods_user_will_consider="full_payment|partial_payment|installments",
             max_installment_months=3),
        dict(user_id="demo_jordan", home_currency="EUR", current_available_balance=980.00,
             minimum_balance_to_keep=700.00, financial_priorities="debt_repayment",
             expense_categories_to_protect="rent|utilities|debt_repayment",
             expense_categories_user_is_willing_to_reduce="shopping|entertainment",
             expense_categories_user_is_willing_to_stop="cloud_storage",
             payment_methods_user_will_consider="full_payment",
             max_installment_months="",
             ),
        dict(user_id="demo_priya", home_currency="USD", current_available_balance=1200.00,
             minimum_balance_to_keep=600.00, financial_priorities="savings|debt_repayment",
             expense_categories_to_protect="rent|groceries",
             expense_categories_user_is_willing_to_reduce="dining",
             expense_categories_user_is_willing_to_stop="streaming",
             payment_methods_user_will_consider="full_payment|partial_payment|installments",
             max_installment_months=2),
    ]
    profile_fields = ["user_id", "home_currency", "current_available_balance", "minimum_balance_to_keep",
                       "financial_priorities", "expense_categories_to_protect",
                       "expense_categories_user_is_willing_to_reduce",
                       "expense_categories_user_is_willing_to_stop",
                       "payment_methods_user_will_consider", "max_installment_months"]
    write_csv("financial_profiles.csv", profile_fields, profiles)

    events = []
    eid = [0]

    def add(user_id, event_type, description, category, direction, amount, currency,
            months_ago, day_of_month, status="settled", flexibility="fixed",
            minimum_allowed_amount="", linked_event_id=""):
        eid[0] += 1
        d = month_back(ANCHOR, months_ago)
        d = date(d.year, d.month, min(day_of_month, 28))
        events.append(dict(
            event_id=f"demo_event_{eid[0]}", user_id=user_id, event_type=event_type,
            description=description, category=category, direction=direction,
            amount=amount, currency=currency, event_date=d.isoformat(), settlement_date=d.isoformat(),
            status=status, linked_event_id=linked_event_id, flexibility=flexibility,
            minimum_allowed_amount=minimum_allowed_amount,
        ))

    # --- demo_alex: comfortable, salary on the 1st, rent on the 3rd -------
    for m in range(6, 0, -1):
        add("demo_alex", "income", "Monthly salary", "salary", "credit", 4200.00, "USD", m, 1)
        add("demo_alex", "expense", "Apartment rent", "rent", "debit", 1650.00, "USD", m, 3)
        add("demo_alex", "expense", "Utilities", "utilities", "debit", 140.00, "USD", m, 5)
        add("demo_alex", "expense", "Streaming subscription", "streaming", "debit", 22.00, "USD", m, 8,
            flexibility="stoppable")
        add("demo_alex", "expense", "Grocery shopping", "groceries", "debit", 380.00, "USD", m, 10)
        add("demo_alex", "expense", "Transport", "transport", "debit", 120.00, "USD", m, 15)
        add("demo_alex", "expense", "Dining out", "dining", "debit", 210.00, "USD", m, 20, flexibility="reducible",
            minimum_allowed_amount=80.00)
        add("demo_alex", "expense", "Loan payment", "debt_repayment", "debit", 300.00, "USD", m, 25)
    add("demo_alex", "income", "Next confirmed salary", "salary", "credit", 4200.00, "USD", -1, 1,
        status="scheduled")

    # --- demo_sam: tighter budget, weekly-ish gym, needs care -------------
    for m in range(6, 0, -1):
        add("demo_sam", "income", "Bi-weekly paycheck", "salary", "credit", 1450.00, "USD", m, 1)
        add("demo_sam", "income", "Bi-weekly paycheck", "salary", "credit", 1450.00, "USD", m, 15)
        add("demo_sam", "expense", "Studio rent", "rent", "debit", 1050.00, "USD", m, 2)
        add("demo_sam", "expense", "Utilities", "utilities", "debit", 95.00, "USD", m, 6)
        add("demo_sam", "expense", "Gym membership", "gym", "debit", 45.00, "USD", m, 9,
            flexibility="stoppable")
        add("demo_sam", "expense", "Streaming subscription", "streaming", "debit", 16.00, "USD", m, 11,
            flexibility="stoppable")
        add("demo_sam", "expense", "Grocery shopping", "groceries", "debit", 260.00, "USD", m, 12)
        add("demo_sam", "expense", "Transport", "transport", "debit", 80.00, "USD", m, 16)
        add("demo_sam", "expense", "Dining out", "dining", "debit", 150.00, "USD", m, 21, flexibility="reducible",
            minimum_allowed_amount=50.00)
        add("demo_sam", "expense", "Student loan payment", "education", "debit", 180.00, "USD", m, 27)
    add("demo_sam", "income", "Next confirmed paycheck", "salary", "credit", 1450.00, "USD", -1, 1,
        status="scheduled")

    # --- demo_jordan: EUR user, already close to minimum ------------------
    for m in range(6, 0, -1):
        add("demo_jordan", "income", "Monthly salary", "salary", "credit", 2600.00, "EUR", m, 1)
        add("demo_jordan", "expense", "Apartment rent", "rent", "debit", 1400.00, "EUR", m, 3)
        add("demo_jordan", "expense", "Utilities", "utilities", "debit", 160.00, "EUR", m, 5)
        add("demo_jordan", "expense", "Cloud storage", "cloud_storage", "debit", 12.00, "EUR", m, 7,
            flexibility="stoppable")
        add("demo_jordan", "expense", "Grocery shopping", "groceries", "debit", 340.00, "EUR", m, 12)
        add("demo_jordan", "expense", "Transport", "transport", "debit", 90.00, "EUR", m, 16)
        add("demo_jordan", "expense", "Loan payment", "debt_repayment", "debit", 420.00, "EUR", m, 22)
    add("demo_jordan", "income", "Next confirmed salary", "salary", "credit", 2600.00, "EUR", -1, 1,
        status="scheduled")

    # --- demo_priya: biweekly income, tight budget, good installments fit --
    for m in range(6, 0, -1):
        add("demo_priya", "income", "Biweekly paycheck", "salary", "credit", 900.00, "USD", m, 1)
        add("demo_priya", "income", "Biweekly paycheck", "salary", "credit", 900.00, "USD", m, 15)
        add("demo_priya", "expense", "Apartment rent", "rent", "debit", 500.00, "USD", m, 3)
        add("demo_priya", "expense", "Utilities", "utilities", "debit", 60.00, "USD", m, 6)
        add("demo_priya", "expense", "Streaming subscription", "streaming", "debit", 15.00, "USD", m, 8,
            flexibility="stoppable")
        add("demo_priya", "expense", "Grocery shopping", "groceries", "debit", 150.00, "USD", m, 12)
        add("demo_priya", "expense", "Transport", "transport", "debit", 50.00, "USD", m, 16)
        add("demo_priya", "expense", "Dining out", "dining", "debit", 70.00, "USD", m, 20, flexibility="reducible",
            minimum_allowed_amount=25.00)
    add("demo_priya", "income", "Next confirmed paycheck", "salary", "credit", 900.00, "USD", -1, 1,
        status="scheduled")

    event_fields = ["event_id", "user_id", "event_type", "description", "category", "direction", "amount",
                     "currency", "event_date", "settlement_date", "status", "linked_event_id", "flexibility",
                     "minimum_allowed_amount"]
    write_csv("financial_events.csv", event_fields, events)

    # --- exchange rates: one EUR<->USD rate at the anchor date ------------
    rates = [
        dict(rate_date=ANCHOR.isoformat(), from_currency="EUR", to_currency="USD", rate=1.08),
        dict(rate_date=ANCHOR.isoformat(), from_currency="USD", to_currency="EUR", rate=0.9259),
    ]
    write_csv("exchange_rates.csv", ["rate_date", "from_currency", "to_currency", "rate"], rates)

    # --- a few illustrative batch requests (for the CLI / evaluation demo) ---
    requests = [
        dict(request_id="demo_req_1", user_id="demo_alex", request_date=ANCHOR.isoformat(),
             request_type="purchase", requested_amount=900.00,
             desired_completion_date=(ANCHOR + timedelta(days=14)).isoformat(),
             allows_partial_payment="true", request_text="New laptop for freelance work, USD 900."),
        dict(request_id="demo_req_2", user_id="demo_sam", request_date=ANCHOR.isoformat(),
             request_type="purchase", requested_amount=650.00,
             desired_completion_date=(ANCHOR + timedelta(days=45)).isoformat(),
             allows_partial_payment="true", request_text="Emergency dental work, USD 650."),
        dict(request_id="demo_req_3", user_id="demo_jordan", request_date=ANCHOR.isoformat(),
             request_type="purchase", requested_amount=500.00,
             desired_completion_date=(ANCHOR + timedelta(days=30)).isoformat(),
             allows_partial_payment="false", request_text="Flight ticket, EUR 500."),
        dict(request_id="demo_req_4", user_id="demo_priya", request_date=ANCHOR.isoformat(),
             request_type="purchase", requested_amount=900.00,
             desired_completion_date=(ANCHOR + timedelta(days=60)).isoformat(),
             allows_partial_payment="true", request_text="Used e-bike for commuting, USD 900."),
    ]
    request_fields = ["request_id", "user_id", "request_date", "request_type", "requested_amount",
                       "desired_completion_date", "allows_partial_payment", "request_text"]
    write_csv("requests.csv", request_fields, requests)

    options = [
        dict(payment_option_id="demo_opt_1", request_id="demo_req_1", payment_method="full_payment",
             payment_amount=900.00, number_of_payments=1, first_payment_date=ANCHOR.isoformat(),
             payment_frequency_days="", financing_fee=0, total_payable_amount=900.00),
        dict(payment_option_id="demo_opt_2", request_id="demo_req_1", payment_method="installments",
             payment_amount=310.00, number_of_payments=3, first_payment_date=ANCHOR.isoformat(),
             payment_frequency_days=30, financing_fee=30.00, total_payable_amount=930.00),
        dict(payment_option_id="demo_opt_3", request_id="demo_req_2", payment_method="full_payment",
             payment_amount=650.00, number_of_payments=1, first_payment_date=ANCHOR.isoformat(),
             payment_frequency_days="", financing_fee=0, total_payable_amount=650.00),
        dict(payment_option_id="demo_opt_4", request_id="demo_req_2", payment_method="installments",
             payment_amount=225.00, number_of_payments=3, first_payment_date=ANCHOR.isoformat(),
             payment_frequency_days=30, financing_fee=25.00, total_payable_amount=675.00),
        dict(payment_option_id="demo_opt_5", request_id="demo_req_3", payment_method="full_payment",
             payment_amount=500.00, number_of_payments=1, first_payment_date=ANCHOR.isoformat(),
             payment_frequency_days="", financing_fee=0, total_payable_amount=500.00),
        dict(payment_option_id="demo_opt_6", request_id="demo_req_4", payment_method="full_payment",
             payment_amount=900.00, number_of_payments=1, first_payment_date=ANCHOR.isoformat(),
             payment_frequency_days="", financing_fee=0, total_payable_amount=900.00),
    ]
    option_fields = ["payment_option_id", "request_id", "payment_method", "payment_amount",
                      "number_of_payments", "first_payment_date", "payment_frequency_days",
                      "financing_fee", "total_payable_amount"]
    write_csv("request_payment_options.csv", option_fields, options)

    messages = [
        dict(message_id="demo_msg_1", user_id="demo_sam", request_id="", related_event_id="",
             sent_at=f"{month_back(ANCHOR, 0).isoformat()}T09:00:00Z", source_type="employer",
             message_text="Hi, payroll here. Your next paycheck is confirmed at USD 1450.00."),
        dict(message_id="demo_msg_2", user_id="demo_jordan", request_id="", related_event_id="",
             sent_at=f"{month_back(ANCHOR, 0).isoformat()}T09:00:00Z", source_type="service_provider",
             message_text="Your cloud storage plan renewal is still pending review and has not been charged yet."),
        dict(message_id="demo_msg_3", user_id="demo_priya", request_id="", related_event_id="",
             sent_at=f"{month_back(ANCHOR, 0).isoformat()}T09:00:00Z", source_type="employer",
             message_text="Payroll confirmation: your biweekly paycheck of USD 900.00 is scheduled as usual."),
    ]
    message_fields = ["message_id", "user_id", "request_id", "related_event_id", "sent_at", "source_type",
                       "message_text"]
    write_csv("messages.csv", message_fields, messages)

    write_csv("images.csv", ["image_id", "user_id", "request_id", "related_event_id"], [])

    os.makedirs(os.path.join(HERE, "media", "images"), exist_ok=True)
    with open(os.path.join(HERE, "media", "images", ".gitkeep"), "w") as f:
        f.write("")

    print(f"\nDemo anchor date (treated as 'today' by the API/demo): {ANCHOR.isoformat()}")


if __name__ == "__main__":
    main()
