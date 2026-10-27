#!/usr/bin/env python3
import csv
import math
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

CSV_PATH = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("logs/triangle_edges.csv")


def parse_float(value):
    if value in ("", None):
        return None
    try:
        return float(value)
    except Exception:
        return None


def percentile(data, pct):
    if not data:
        return 0.0
    values = sorted(data)
    if len(values) == 1:
        return values[0]
    index = max(0, min(len(values) - 1, math.ceil((pct / 100.0) * len(values)) - 1))
    return values[index]


def reads():
    rows = []
    with CSV_PATH.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append(row)
    return rows


def main():
    rows = reads()
    if not rows:
        print("never")
        return

    fee_buffer = 0.0005  # 0.05%
    gross_cols = [
        ("USDT-BTC-SOL-USDT", "usdt_btc_sol_usdt_gross"),
        ("USDT-SOL-BTC-USDT", "usdt_sol_btc_usdt_gross"),
    ]

    day_buckets = defaultdict(list)
    for row in rows:
        ts = row.get("timestamp")
        if not ts:
            continue
        try:
            day = datetime.fromisoformat(ts.replace("Z", "+00:00")).date().isoformat()
        except Exception:
            continue

        for name, colname in gross_cols:
            value = parse_float(row.get(colname))
            if value is not None:
                day_buckets[(name, day)].append(value)

    total_exceed = 0
    for name, colname in gross_cols:
        count = 0
        for row in rows:
            value = parse_float(row.get(colname))
            if value is not None and value > fee_buffer:
                count += 1
        total_exceed += count

    verdict = "never"
    if total_exceed > 0:
        verdict = f"edge exceeded cost {total_exceed} times in {len(rows)} rows"

    print(f"verdict: {verdict}")

    for name, colname in gross_cols:
        values = []
        for row in rows:
            v = parse_float(row.get(colname))
            if v is not None:
                values.append(v)

        if not values:
            print(f"{name}: no data")
            continue

        print(f"{name}:")
        print(f"  p50={percentile(values, 50):.4%}")
        print(f"  p95={percentile(values, 95):.4%}")
        print(f"  p99={percentile(values, 99):.4%}")
        print(f"  max={max(values):.4%}")
        print(f"  beats_cost_plus_0.05pct={sum(1 for v in values if v > fee_buffer)}")

    for (name, day), values in sorted(day_buckets.items()):
        if not values:
            continue
        print(f"{name} {day}: p50={percentile(values,50):.4%}, p95={percentile(values,95):.4%}, p99={percentile(values,99):.4%}, max={max(values):.4%}")


if __name__ == "__main__":
    main()