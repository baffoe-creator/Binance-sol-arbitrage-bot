import logging

from src.exchange.client import get_client
from src.exchange.precision import get_lot_size_step, round_step_size

logger = logging.getLogger("bot.execution")


class Executor:
    def __init__(self):
        self.client = get_client()
        self.filled_legs = []

    def market_order(self, symbol: str, side: str, quantity: float):
        """SELL legs: you know the exact base-asset quantity to sell."""
        symbol = symbol.upper()
        step = get_lot_size_step(self.client, symbol)
        rounded_qty = round_step_size(quantity, step)
        if rounded_qty <= 0:
            raise ValueError(
                f"Quantity {quantity} rounds to {rounded_qty} at step {step} for {symbol} — "
                f"too small to trade, check MAX_ACCOUNT_BUDGET_SOL sizing."
            )
        order = self.client.create_order(
            symbol=symbol, side=side, type="MARKET", quantity=rounded_qty, recvWindow=60000
        )
        self.filled_legs.append(order)
        logger.info(f"Filled {side} {rounded_qty} {symbol} (requested {quantity}): {order.get('status')}")
        return order

    def market_buy_by_quote(self, symbol: str, quote_qty: float):
        """BUY legs: spend a known amount of the QUOTE asset, let Binance
        compute the base quantity server-side via quoteOrderQty — avoids
        manual price-division bugs entirely."""
        symbol = symbol.upper()
        order = self.client.create_order(
            symbol=symbol, side="BUY", type="MARKET", quoteOrderQty=quote_qty, recvWindow=60000
        )
        self.filled_legs.append(order)
        logger.info(f"Filled BUY {symbol} spending {quote_qty} quote: {order.get('status')}")
        return order