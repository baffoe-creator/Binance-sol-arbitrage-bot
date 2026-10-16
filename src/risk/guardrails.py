import logging

logger = logging.getLogger("bot.risk")


class CircuitBreaker:
    def __init__(self, daily_loss_limit: float):
        self.daily_loss_limit = daily_loss_limit
        self.start_of_day_equity = None

    def check(self, current_equity: float) -> bool:
        if self.start_of_day_equity is None:
            self.start_of_day_equity = current_equity
        pnl = current_equity - self.start_of_day_equity
        if pnl < self.daily_loss_limit:
            logger.critical(f"Daily loss limit breached: {pnl:.2f}. Halting.")
            return False
        return True


def confirm_loop_closed(executor, expected_legs: int = 3) -> bool:
    return len(executor.filled_legs) == expected_legs


class TrailingCapitalStop:
    def __init__(self, initial_capital: float, drawdown_pct: float = 0.05):
        self.peak_capital = initial_capital
        self.drawdown_pct = drawdown_pct
        self.stop_floor = initial_capital * (1 - drawdown_pct)

    def check(self, current_capital: float) -> bool:
        if current_capital > self.peak_capital:
            self.peak_capital = current_capital
            self.stop_floor = self.peak_capital * (1 - self.drawdown_pct)
        if current_capital < self.stop_floor:
            logger.critical(f"Trailing stop breached: {current_capital:.6f} below floor {self.stop_floor:.6f}")
            return False
        return True


def unwind_partial_loop(executor, held_asset: str, held_qty: float, quote_asset: str = "USDT"):
    if held_asset == quote_asset:
        # Already holding USDT (leg 2 succeeded, leg 3 failed) — buy back to
        # SOL directly rather than building an invalid self-pair symbol.
        logger.critical(f"Held asset is already {quote_asset}; converting back to SOL instead.")
        return executor.market_buy_by_quote(f"SOL{quote_asset}", held_qty)

    symbol = f"{held_asset}{quote_asset}"
    logger.critical(f"Unwinding partial loop: selling {held_qty} {held_asset} via {symbol}")
    return executor.market_order(symbol, "SELL", held_qty)