import logging
import os

from src.alerts.telegram import send_alert
from src.arb.detector import find_sol_triangle_opportunity
from src.risk.guardrails import CircuitBreaker, confirm_loop_closed, unwind_partial_loop

logger = logging.getLogger("bot.arb")


def run_cycle(cache, executor, breaker: CircuitBreaker):
    books = cache.snapshot()
    min_edge = float(os.environ.get("MIN_SOL_ARB_EDGE", 0.0035))
    opp = find_sol_triangle_opportunity(books, min_edge)
    if not opp:
        return

    sol_budget = float(os.environ["MAX_ACCOUNT_BUDGET_SOL"])
    if not breaker.check(sol_budget):
        return

    held_qty = sol_budget
    held_asset = None  # None = no leg executed yet, original SOL budget untouched
    try:
        for pair, side, field, resulting_asset in opp["legs"]:
            if side == "SELL":
                executor.market_order(pair.upper(), "SELL", held_qty)
                # cummulativeQuoteQty = what you RECEIVED, not executedQty
                # (what you sold) — this exact field mix-up caused a real
                # bug in the ETH version.
                held_qty = float(executor.filled_legs[-1]["cummulativeQuoteQty"])
            else:
                executor.market_buy_by_quote(pair.upper(), held_qty)
                held_qty = float(executor.filled_legs[-1]["executedQty"])
            held_asset = resulting_asset
    except Exception as e:
        if not confirm_loop_closed(executor):
            if held_asset is None:
                logger.warning(f"Leg 1 failed before any fill — nothing to unwind. Error: {e}")
            elif held_asset == "SOL":
                logger.info("Held asset already SOL — nothing to unwind.")
            else:
                unwind_partial_loop(executor, held_asset, held_qty)
            send_alert(f"Partial SOL loop ({opp['name']}) handled after error: {e}")
        return

    if confirm_loop_closed(executor):
        send_alert(f"SOL triangle closed ({opp['name']}): net edge {opp['net_edge']:.4%}")
    else:
        send_alert(f"WARNING: {opp['name']} did not close cleanly, check logs")