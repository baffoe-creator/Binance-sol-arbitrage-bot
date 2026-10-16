import logging
import os
import time

from src.alerts.telegram import send_alert
from src.arb.detector import find_sol_triangle_opportunity
from src.exchange.balances import auto_redeem_enabled, ensure_spot_sol
from src.risk.guardrails import CircuitBreaker, confirm_loop_closed, unwind_partial_loop

logger = logging.getLogger("bot.arb")

# Opportunities are re-detected every ~2 s. Without throttling, a persistent
# "no spendable SOL" condition would send a Telegram message every cycle.
ALERT_COOLDOWN_SECONDS = 900
_last_alert_at: dict[str, float] = {}


def _notify_throttled(key: str, message: str) -> None:
    now = time.monotonic()
    last = _last_alert_at.get(key)
    if last is not None and now - last < ALERT_COOLDOWN_SECONDS:
        return
    _last_alert_at[key] = now
    logger.warning(message)
    try:
        send_alert(message)
    except Exception as e:
        logger.error(f"Alert could not be sent: {e}")


def run_cycle(cache, executor, breaker: CircuitBreaker):
    books = cache.snapshot()
    min_edge = float(os.environ.get("MIN_SOL_ARB_EDGE", 0.0035))
    opp = find_sol_triangle_opportunity(books, min_edge)
    if not opp:
        return

    sol_budget = float(os.environ["MAX_ACCOUNT_BUDGET_SOL"])
    if not breaker.check(sol_budget):
        return

    # The first leg sells SOL, so it must be SOL in the SPOT wallet. SOL that
    # sits in Simple Earn (shown by Binance as LDSOL) cannot be sold directly.
    try:
        check = ensure_spot_sol(executor.client, sol_budget, auto_redeem=auto_redeem_enabled())
    except Exception as e:
        logger.error(f"Spot SOL balance check failed, skipping opportunity: {e}")
        return
    if not check.ready:
        _notify_throttled(
            f"spot_sol:{check.code}",
            f"Skipped {opp['name']} opportunity: {check.reason}",
        )
        return

    # Never try to sell more than the spot wallet actually holds.
    trade_qty = min(sol_budget, float(check.balance.spot_free))

    # filled_legs lives as long as the Executor. Without this reset the second
    # successful loop would see 6 legs instead of 3 and report "did not close".
    executor.filled_legs = []

    held_qty = trade_qty
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