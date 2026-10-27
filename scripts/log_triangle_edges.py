#!/usr/bin/env python3
import csv
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.arb.detector import get_triangle_metrics
from src.data.streams import BinanceBookStream, SolBookCache

CSV_PATH = Path(os.environ.get("TRIANGLE_LOG_PATH", "logs/triangle_edges.csv"))


def main():
    pairs = ["solbtc", "btcusdt", "solusdt"]
    cache = SolBookCache(pairs)
    stream = BinanceBookStream(cache)
    stream.start()

    # Give the websocket a moment to populate data.
    time.sleep(2.0)

    CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

    with CSV_PATH.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([
            "timestamp",
            "solbtc_bid",
            "solbtc_ask",
            "btcusdt_bid",
            "btcusdt_ask",
            "solusdt_bid",
            "solusdt_ask",
            "solbtc_spread_pct",
            "btcusdt_spread_pct",
            "solusdt_spread_pct",
            "solbtc_age_s",
            "btcusdt_age_s",
            "solusdt_age_s",
            "usdt_btc_sol_usdt_gross",
            "usdt_btc_sol_usdt_net",
            "usdt_sol_btc_usdt_gross",
            "usdt_sol_btc_usdt_net",
            "stale_skip",
        ])

        while True:
            books = cache.snapshot()
            solbtc = books.get("solbtc", {})
            btcusdt = books.get("btcusdt", {})
            solusdt = books.get("solusdt", {})

            def spread_pct(bid, ask):
                if bid is None or ask is None or ask == 0:
                    return None
                return ((ask - bid) / ask) * 100.0

            row = [
                datetime.now(timezone.utc).isoformat(timespec="seconds"),
                solbtc.get("bid"),
                solbtc.get("ask"),
                btcusdt.get("bid"),
                btcusdt.get("ask"),
                solusdt.get("bid"),
                solusdt.get("ask"),
                spread_pct(solbtc.get("bid"), solbtc.get("ask")),
                spread_pct(btcusdt.get("bid"), btcusdt.get("ask")),
                spread_pct(solusdt.get("bid"), solusdt.get("ask")),
                solbtc.get("age_s"),
                btcusdt.get("age_s"),
                solusdt.get("age_s"),
            ]

            metrics = get_triangle_metrics(books)
            by_name = {m["name"]: m for m in metrics if m.get("name")}

            for name in ["USDT-BTC-SOL-USDT", "USDT-SOL-BTC-USDT"]:
                entry = by_name.get(name, {})
                row.append(entry.get("gross_edge"))
                row.append(entry.get("net_edge"))

            stale_skip = any((m.get("stale") is True or m.get("missing") is True) for m in metrics)
            row.append(stale_skip)

            writer.writerow(row)
            fh.flush()
            time.sleep(1.0)


if __name__ == "__main__":
    main()