import logging
import os
import random
import sys
import threading
import time
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.alerts.telegram import send_alert
from src.arb.detector import diagnostic_snapshot
from src.arb.runner import run_cycle
from src.data.streams import BinanceBookStream, SolBookCache
from src.execution.executor import Executor
from src.exchange.balances import (
    auto_redeem_enabled,
    ensure_spot_sol,
    get_flexible_sol_positions,
    get_sol_balance,
)
from src.risk.guardrails import CircuitBreaker, TrailingCapitalStop
from src.risk.state import atomic_cycle_state, check_recovery_needed, init_state_db

load_dotenv()
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    handlers=[logging.FileHandler("logs/trading_bot_sol.log"), logging.StreamHandler()],
)
logger = logging.getLogger("bot.main")

EXIT_OK = 0
EXIT_RISK_HALT = 2
EXIT_RECOVERY_REQUIRED = 3


def ping_binance_until_ready(client, max_attempts: int = 12, base_delay: float = 1.0, max_delay: float = 60.0) -> bool:
    backoff = base_delay
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            client.get_server_time()
            logger.info("Binance ping succeeded on attempt %s/%s", attempt, max_attempts)
            return True
        except Exception as exc:
            last_exc = exc
            sleep_for = min(max_delay, backoff) + random.uniform(0.0, 0.5)
            logger.warning(
                "Binance ping attempt %s/%s failed: %s. Retrying in %.1fs",
                attempt,
                max_attempts,
                exc,
                sleep_for,
            )
            if attempt == max_attempts:
                break
            time.sleep(sleep_for)
            backoff = min(max_delay, backoff * 2.0)
    raise RuntimeError(f"Binance ping failed after {max_attempts} attempts: {last_exc}")


def wait_for_initial_books(cache: SolBookCache, timeout_seconds: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        snapshot = cache.snapshot()
        if all(
            snapshot.get(pair, {}).get("bid") is not None and snapshot.get(pair, {}).get("ask") is not None
            for pair in cache.pairs
        ):
            logger.info("Initial book data received for all pairs.")
            return True
        time.sleep(0.5)
    logger.warning("Timed out waiting for initial book data; continuing anyway.")
    return False


class BalancePoller(threading.Thread):
    def __init__(self, client, interval_seconds: float = 30.0):
        super().__init__(name="balance-poller", daemon=True)
        self.client = client
        self.interval_seconds = interval_seconds
        self.stop_event = threading.Event()
        self.latest_balance = None
        self.latest_error = None

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.latest_balance = get_sol_balance(self.client)
                self.latest_error = None
            except Exception as exc:
                self.latest_error = exc

            self.stop_event.wait(self.interval_seconds)

    def snapshot(self):
        return self.latest_balance

    def stop(self):
        self.stop_event.set()
        self.join(timeout=5.0)


def report_startup_balances(executor, starting_capital: float) -> None:
    try:
        bal = get_sol_balance(executor.client)
    except Exception as e:
        logger.error("Startup balance read failed: %s", e)
        return

    logger.info("SOL holdings at startup: %s", bal.describe())
    if bal.other_sol_like:
        logger.warning(
            "SOL-like assets present but NOT counted as SOL (different asset names): %s",
            list(bal.other_sol_like),
        )

    if bal.earn_free > 0:
        try:
            for row in get_flexible_sol_positions(executor.client):
                logger.info(
                    "Simple Earn SOL position: productId=%s totalAmount=%s canRedeem=%s autoSubscribe=%s",
                    row.get("productId"),
                    row.get("totalAmount"),
                    row.get("canRedeem"),
                    row.get("autoSubscribe"),
                )
        except Exception as e:
            logger.warning("Could not read Simple Earn position (API key may lack permission): %s", e)

    try:
        check = ensure_spot_sol(executor.client, starting_capital, auto_redeem=auto_redeem_enabled())
        if not check.ready:
            logger.warning("Spot SOL not ready at startup [%s]: %s", check.code, check.reason)
            send_alert(f"SOL bot startup: {check.reason}")
    except Exception as e:
        logger.error("Startup spot-SOL check failed: %s", e)


def main() -> int:
    init_state_db()
    if check_recovery_needed():
        msg = "Startup blocked: last run left an in-flight cycle. Check your Binance account manually."
        logger.critical(msg)
        send_alert(msg)
        return EXIT_RECOVERY_REQUIRED

    cache = SolBookCache(["solbtc", "btcusdt", "solusdt"])
    stream = BinanceBookStream(cache)
    stream.start()
    logger.info("WebSocket stream started; waiting for initial book data...")

    executor = Executor()
    try:
        ping_binance_until_ready(executor.client)
    except Exception as exc:
        logger.critical("Binance API not reachable; startup failed: %s", exc)
        send_alert(f"Binance startup ping failed: {exc}")
        return EXIT_RECOVERY_REQUIRED

    wait_for_initial_books(cache, timeout_seconds=15.0)

    balance_poller = BalancePoller(executor.client, interval_seconds=30.0)
    balance_poller.start()
    try:
        balance_poller.latest_balance = get_sol_balance(executor.client)
    except Exception as exc:
        logger.warning("Initial balance poll failed: %s", exc)

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
            logger.error("Unhandled error in cycle: %s", e)
            send_alert(f"Unhandled error in cycle: {e}")

        try:
            current_balance = balance_poller.snapshot()
            if current_balance is None:
                raise RuntimeError("Balance cache is empty; no successful poll yet.")
            sol_total = float(current_balance.total)
            if not trailing_stop.check(sol_total):
                msg = f"Trailing stop breached at {sol_total:.6f} SOL. Halting bot entirely."
                logger.critical(msg)
                send_alert(msg)
                return EXIT_RISK_HALT
        except Exception as e:
            logger.error("Trailing stop balance check failed: %s", e)

        cycle_count += 1
        if cycle_count % 30 == 0:
            snapshot = diagnostic_snapshot(cache.snapshot())
            stale_seconds = max(cache.seconds_since_update(pair) for pair in cache.pairs)
            if stale_seconds > 15:
                msg = f"Price feed stale for {stale_seconds:.0f}s — restarting WebSocket thread."
                logger.critical(msg)
                send_alert(msg)
                stream.stop()
                time.sleep(1)
                stream.start()
            logger.info(
                "Still scanning — %s cycles completed. Feed age: %.0fs. Edges: %s",
                cycle_count,
                stale_seconds,
                snapshot,
            )

        time.sleep(2)


if __name__ == "__main__":
    sys.exit(main())