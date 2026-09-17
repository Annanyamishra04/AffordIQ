"""
CLI entry point for the "Buy or Wait?" engine (unchanged decision logic,
see backend/engine/). Batch-processes a requests CSV against a dataset
directory and writes an output CSV in the same schema as the original
challenge.

By default this runs against the bundled synthetic demo dataset so the
project works out of the box without any private data:

    python3 backend/main.py

To run it against the original (private, not committed) challenge dataset
for local evaluation:

    python3 backend/main.py --dataset-dir /path/to/challenge/dataset \
        --requests /path/to/challenge/dataset/requests.csv --out output.csv
"""
from __future__ import annotations

import argparse
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from engine.data_loader import Dataset
from engine.pipeline import Pipeline

FIELDNAMES = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation",
]


def main():
    default_dataset_dir = os.path.join(HERE, "demo_data")
    default_requests = os.path.join(default_dataset_dir, "requests.csv")
    default_out = os.path.join(HERE, "..", "demo_output.csv")

    parser = argparse.ArgumentParser(description="Buy or Wait? affordability agent")
    parser.add_argument("--dataset-dir", default=default_dataset_dir)
    parser.add_argument("--requests", default=default_requests)
    parser.add_argument("--out", default=default_out)
    args = parser.parse_args()

    ds = Dataset(args.dataset_dir)
    requests_filename = os.path.basename(args.requests)
    is_sample = "sample" in requests_filename
    requests = ds.load_requests(requests_filename, is_sample=is_sample)

    pipeline = Pipeline(ds)
    rows = pipeline.process_all(requests)

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    print(f"Processed {len(rows)} requests -> {args.out}")


if __name__ == "__main__":
    main()
