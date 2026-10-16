import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import logging
import threading
from dotenv import load_dotenv

from src.data.streams import SolBookCache, start_stream
from src.execution.executor import Executor
from src.risk.guardrails import CircuitBreaker, TrailingCapitalStop
from src.risk.state import init_state_db, atomic_cycle_state, check_recovery_needed
from src.arb.runner import run_cycle
from src.arb.detector import diagnostic_snapshot
from src.alerts.telegram import send_alert

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.FileHandler("logs/trading_bot_sol.log"), logging.StreamHandler()],
)
logger = logging.getLogger("bot.main")


def start_stream_thread(cache):
    thread = threading.Thread(target=start_stream, args=(cache,), daemon=True)
    thread.start()
    return thread


def main():
    init_state_db()
    if check_recovery_needed():
        msg = "Startup blocked: last run left an in-flight cycle. Check your Binance account manually."
        logger.critical(msg)
        send_alert(msg)
        return

    cache = SolBookCache(["solbtc", "btcusdt", "solusdt"])
    stream_thread = start_stream_thread(cache)
    logger.info("WebSocket stream thread started, waiting for initial book data...")
    time.sleep(5)

    executor = Executor()
    starting_capital = float(os.environ["MAX_ACCOUNT_BUDGET_SOL"])
    breaker = CircuitBreaker(daily_loss_limit=-starting_capital * 0.10)
    trailing_stop = TrailingCapitalStop(initial_capital=starting_capital)

    send_alert(f"SOL bot starting up. USE_TESTNET={os.environ.get('USE_TESTNET')}")
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
            sol_balance = float(executor.client.get_asset_balance(asset="SOL", recvWindow=60000)["free"])
            if not trailing_stop.check(sol_balance):
                msg = f"Trailing stop breached at {sol_balance:.6f} SOL. Halting bot entirely."
                logger.critical(msg)
                send_alert(msg)
                break
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
    main()