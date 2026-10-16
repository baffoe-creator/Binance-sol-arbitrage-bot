import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import logging
import threading
from dotenv import load_dotenv

from src.data.streams import SolBookCache, start_stream
from src.execution.executor import Executor
from src.exchange.balances import (
    auto_redeem_enabled,
    ensure_spot_sol,
    get_flexible_sol_positions,
    get_sol_balance,
)
from src.risk.guardrails import CircuitBreaker, TrailingCapitalStop
from src.risk.state import init_state_db, atomic_cycle_state, check_recovery_needed
from src.arb.runner import run_cycle
from src.arb.detector import diagnostic_snapshot
from src.alerts.telegram import send_alert

load_dotenv()
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.FileHandler("logs/trading_bot_sol.log"), logging.StreamHandler()],
)
logger = logging.getLogger("bot.main")

# Exit codes. run_arb_sol_supervised.ps1 does NOT restart on 2 or 3, so a
# deliberate safety halt is not silently undone ten seconds later.
EXIT_OK = 0
EXIT_RISK_HALT = 2
EXIT_RECOVERY_REQUIRED = 3


def start_stream_thread(cache):
    thread = threading.Thread(target=start_stream, args=(cache,), daemon=True)
    thread.start()
    return thread


def report_startup_balances(executor, starting_capital: float) -> None:
    """Log where the SOL really is, and move Earn SOL to Spot if allowed."""
    try:
        bal = get_sol_balance(executor.client)
    except Exception as e:
        logger.error(f"Startup balance read failed: {e}")
        return

    logger.info(f"SOL holdings at startup: {bal.describe()}")
    if bal.other_sol_like:
        logger.warning(
            f"SOL-like assets present but NOT counted as SOL (different assets): {list(bal.other_sol_like)}"
        )

    if bal.earn_free > 0:
        try:
            for row in get_flexible_sol_positions(executor.client):
                logger.info(
                    f"Simple Earn SOL position: productId={row.get('productId')} "
                    f"totalAmount={row.get('totalAmount')} canRedeem={row.get('canRedeem')} "
                    f"autoSubscribe={row.get('autoSubscribe')}"
                )
        except Exception as e:
            logger.warning(f"Could not read Simple Earn position (API key may lack permission): {e}")

    try:
        check = ensure_spot_sol(executor.client, starting_capital, auto_redeem=auto_redeem_enabled())
        if not check.ready:
            logger.warning(f"Spot SOL not ready at startup [{check.code}]: {check.reason}")
            send_alert(f"SOL bot startup: {check.reason}")
    except Exception as e:
        logger.error(f"Startup spot-SOL check failed: {e}")


def main() -> int:
    init_state_db()
    if check_recovery_needed():
        msg = "Startup blocked: last run left an in-flight cycle. Check your Binance account manually."
        logger.critical(msg)
        send_alert(msg)
        return EXIT_RECOVERY_REQUIRED

    cache = SolBookCache(["solbtc", "btcusdt", "solusdt"])
    stream_thread = start_stream_thread(cache)
    logger.info("WebSocket stream thread started, waiting for initial book data...")
    time.sleep(5)

    executor = Executor()
    starting_capital = float(os.environ["MAX_ACCOUNT_BUDGET_SOL"])
    breaker = CircuitBreaker(daily_loss_limit=-starting_capital * 0.10)
    trailing_stop = TrailingCapitalStop(initial_capital=starting_capital)

    send_alert(f"SOL bot starting up. USE_TESTNET={os.environ.get('USE_TESTNET')}")
    report_startup_balances(executor, starting_capital)
    logger.info("Entering main loop.")

    cycle_count = 0
    while True:
        try:
            with atomic_cycle_state():
                run_cycle(cache, executor, breaker)
        except Exception as e:
            logger.error(f"Unhandled error in cycle: {e}")
            send_alert(f"Unhandled error in cycle: {e}")

        try:
            # Total SOL owned (Spot + LDSOL). Reading only Spot "SOL" reported
            # zero whenever the SOL sat in Simple Earn and tripped the stop.
            sol_total = float(get_sol_balance(executor.client).total)
            if not trailing_stop.check(sol_total):
                msg = f"Trailing stop breached at {sol_total:.6f} SOL. Halting bot entirely."
                logger.critical(msg)
                send_alert(msg)
                return EXIT_RISK_HALT
        except Exception as e:
            logger.error(f"Trailing stop balance check failed: {e}")

        cycle_count += 1
        if cycle_count % 30 == 0:
            snapshot = diagnostic_snapshot(cache.snapshot())
            stale_seconds = cache.seconds_since_update()
            if stale_seconds > 30:
                msg = f"Price feed stale for {stale_seconds:.0f}s — restarting WebSocket thread."
                logger.critical(msg)
                send_alert(msg)
                stream_thread = start_stream_thread(cache)
                time.sleep(5)
            logger.info(
                f"Still scanning — {cycle_count} cycles completed. "
                f"Feed age: {stale_seconds:.0f}s. Edges: {snapshot}"
            )

        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())