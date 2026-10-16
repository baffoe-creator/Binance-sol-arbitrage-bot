import pytest

from src.arb import runner
from src.exchange import balances as bal
from src.risk.guardrails import CircuitBreaker

BOOKS = {  # ~4.7% gross edge, well above threshold
    "solbtc": {"bid": 0.0024, "ask": 0.0025},
    "btcusdt": {"bid": 65000, "ask": 65001},
    "solusdt": {"bid": 148.9, "ask": 149.0},
}


class FakeCache:
    def snapshot(self):
        return dict(BOOKS)


class FakeClient:
    def __init__(self, rows):
        self.rows = rows

    def get_account(self, **kw):
        return {"balances": self.rows}


class FakeExecutor:
    def __init__(self, rows):
        self.client = FakeClient(rows)
        self.filled_legs = []
        self.orders = []

    def _fill(self, symbol, side, qty):
        self.orders.append((symbol, side, qty))
        order = {"cummulativeQuoteQty": "1.0", "executedQty": "1.0", "status": "FILLED"}
        self.filled_legs.append(order)
        return order

    def market_order(self, symbol, side, quantity):
        return self._fill(symbol, side, quantity)

    def market_buy_by_quote(self, symbol, quote_qty):
        return self._fill(symbol, "BUY", quote_qty)


def rows(sol="0", ldsol="0"):
    return [
        {"asset": "SOL", "free": sol, "locked": "0"},
        {"asset": "LDSOL", "free": ldsol, "locked": "0"},
    ]


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("MAX_ACCOUNT_BUDGET_SOL", "1.0")
    monkeypatch.setenv("MIN_SOL_ARB_EDGE", "0.0035")
    monkeypatch.setenv("USE_TESTNET", "false")
    monkeypatch.setenv("AUTO_REDEEM_LDSOL", "false")
    runner._last_alert_at.clear()
    bal.reset_redeem_cooldown()
    sent = []
    monkeypatch.setattr(runner, "send_alert", sent.append)
    return sent


def breaker():
    return CircuitBreaker(daily_loss_limit=-0.1)


def test_ldsol_only_account_does_not_trade_and_alerts_once(env):
    ex = FakeExecutor(rows(sol="0", ldsol="3"))
    runner.run_cycle(FakeCache(), ex, breaker())
    runner.run_cycle(FakeCache(), ex, breaker())
    runner.run_cycle(FakeCache(), ex, breaker())
    assert ex.orders == []
    assert len(env) == 1                      # throttled, not one per cycle
    assert "LDSOL" in env[0]


def test_trade_size_is_capped_by_spot_balance(env):
    ex = FakeExecutor(rows(sol="0.97"))       # 97% of budget: still tradable
    runner.run_cycle(FakeCache(), ex, breaker())
    assert ex.orders[0][:2] == ("SOLBTC", "SELL")
    assert ex.orders[0][2] == pytest.approx(0.97)


def test_trade_size_never_exceeds_budget(env):
    ex = FakeExecutor(rows(sol="25"))
    runner.run_cycle(FakeCache(), ex, breaker())
    assert ex.orders[0][2] == pytest.approx(1.0)


def test_consecutive_successful_loops_both_report_closed(env):
    ex = FakeExecutor(rows(sol="5"))
    runner.run_cycle(FakeCache(), ex, breaker())
    runner.run_cycle(FakeCache(), ex, breaker())
    assert len(ex.orders) == 6
    assert not any("did not close" in m for m in env)
    assert sum("triangle closed" in m for m in env) == 2