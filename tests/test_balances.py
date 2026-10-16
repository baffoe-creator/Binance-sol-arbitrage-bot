from decimal import Decimal

import pytest

from src.exchange import balances as bal


def row(asset, free="0", locked="0"):
    return {"asset": asset, "free": free, "locked": locked}


class FakeClient:
    """Mimics a newer python-binance that has public Simple Earn wrappers."""

    def __init__(self, rows, positions=None, redeem_response=None):
        self.rows = rows
        self.positions = positions if positions is not None else []
        self.redeem_response = redeem_response or {"redeemId": 1, "success": True}
        self.redeem_calls = []

    def get_account(self, **kw):
        return {"balances": self.rows}

    def get_simple_earn_flexible_product_position(self, **kw):
        return {"rows": self.positions, "total": len(self.positions)}

    def redeem_simple_earn_flexible_product(self, **kw):
        self.redeem_calls.append(kw)
        if isinstance(self.redeem_response, Exception):
            raise self.redeem_response
        return self.redeem_response


class LegacyClient:
    """Mimics python-binance 1.0.19: no public Simple Earn wrappers."""

    def __init__(self, rows, positions):
        self.rows, self.positions, self.calls = rows, positions, []

    def get_account(self, **kw):
        return {"balances": self.rows}

    def _request_margin_api(self, method, path, signed=False, version=1, **kwargs):
        self.calls.append((method, path, signed, dict(kwargs["data"])))
        if method == "get":
            return {"rows": self.positions}
        return {"redeemId": 7, "success": True}


POSITION = {"productId": "SOL001", "totalAmount": "5.0", "canRedeem": True, "autoSubscribe": False}


@pytest.fixture(autouse=True)
def _reset():
    bal.reset_redeem_cooldown()


# ---------------------------------------------------------------- parsing
def test_counts_sol_and_ldsol_only():
    b = bal.parse_sol_balance([
        row("SOL", "0.5", "0.1"), row("LDSOL", "2.0"),
        row("BNSOL", "3.0"), row("SOLV", "10"), row("BTC", "1"),
    ])
    assert b.spot_free == Decimal("0.5")
    assert b.spot_locked == Decimal("0.1")
    assert b.earn_free == Decimal("2.0")
    assert b.total == Decimal("2.6")
    # similar-looking assets are reported but never counted
    assert dict(b.other_sol_like) == {"BNSOL": Decimal("3.0"), "SOLV": Decimal("10")}


def test_only_ldsol_means_zero_spot_but_nonzero_total():
    b = bal.parse_sol_balance([row("LDSOL", "1.5"), row("LDBTC", "0.01")])
    assert b.spot_free == 0
    assert b.total == Decimal("1.5")


def test_empty_and_garbage_input_do_not_crash():
    assert bal.parse_sol_balance(None).total == 0
    assert bal.parse_sol_balance([]).total == 0
    assert bal.parse_sol_balance([{"asset": "SOL", "free": None, "locked": "abc"}]).total == 0


# ---------------------------------------------------------- ensure_spot_sol
def test_enough_spot_sol_is_ready_and_never_redeems():
    c = FakeClient([row("SOL", "1.0"), row("LDSOL", "5")], [POSITION])
    r = bal.ensure_spot_sol(c, 1.0, auto_redeem=True)
    assert r.ready and r.code == "ok"
    assert c.redeem_calls == []


def test_spot_within_trade_fraction_is_ready():
    c = FakeClient([row("SOL", "0.96")], [])
    assert bal.ensure_spot_sol(c, 1.0).ready


def test_ldsol_only_with_auto_redeem_off_reports_and_does_not_touch_funds():
    c = FakeClient([row("LDSOL", "5")], [POSITION])
    r = bal.ensure_spot_sol(c, 1.0, auto_redeem=False)
    assert not r.ready and r.code == "earn_manual"
    assert "LDSOL" in r.reason
    assert c.redeem_calls == []


def test_auto_redeem_submits_exact_shortfall_to_spot():
    c = FakeClient([row("SOL", "0.2"), row("LDSOL", "5")], [POSITION])
    r = bal.ensure_spot_sol(c, 1.0, auto_redeem=True)
    assert not r.ready and r.code == "redeem_submitted"      # skip this cycle
    assert r.redeemed == Decimal("0.8")
    call = c.redeem_calls[0]
    assert call["productId"] == "SOL001"
    assert call["destAccount"] == "SPOT"
    assert Decimal(call["amount"]) == Decimal("0.8")
    assert "redeemAll" not in call


def test_redeem_everything_uses_redeem_all_lowercase_string():
    c = FakeClient([row("LDSOL", "0.5")], [{**POSITION, "totalAmount": "0.5"}])
    bal.ensure_spot_sol(c, 1.0, auto_redeem=True)
    call = c.redeem_calls[0]
    assert call["redeemAll"] == "true"
    assert "amount" not in call


def test_redeem_cooldown_prevents_repeat_calls():
    c = FakeClient([row("LDSOL", "5")], [POSITION])
    bal.ensure_spot_sol(c, 1.0, auto_redeem=True)
    r2 = bal.ensure_spot_sol(c, 1.0, auto_redeem=True)
    assert r2.code == "redeem_cooldown"
    assert len(c.redeem_calls) == 1


def test_redeem_failure_is_reported_not_raised():
    c = FakeClient([row("LDSOL", "5")], [POSITION], redeem_response=RuntimeError("permission denied"))
    r = bal.ensure_spot_sol(c, 1.0, auto_redeem=True)
    assert r.code == "redeem_failed" and "permission denied" in r.reason


def test_position_that_cannot_be_redeemed_is_a_clean_failure():
    c = FakeClient([row("LDSOL", "5")], [{**POSITION, "canRedeem": False}])
    r = bal.ensure_spot_sol(c, 1.0, auto_redeem=True)
    assert r.code == "redeem_failed"
    assert c.redeem_calls == []


def test_nothing_anywhere():
    r = bal.ensure_spot_sol(FakeClient([row("BTC", "1")]), 1.0, auto_redeem=True)
    assert not r.ready and r.code == "no_funds"


# ------------------------------------------- python-binance 1.0.19 fallback
def test_legacy_client_uses_current_simple_earn_endpoints():
    c = LegacyClient([row("LDSOL", "5")], [POSITION])
    r = bal.ensure_spot_sol(c, 1.0, auto_redeem=True)
    assert r.code == "redeem_submitted"
    (m1, p1, s1, d1), (m2, p2, s2, d2) = c.calls
    assert (m1, p1, s1) == ("get", "simple-earn/flexible/position", True)
    assert d1["asset"] == "SOL"
    assert (m2, p2, s2) == ("post", "simple-earn/flexible/redeem", True)
    assert d2["productId"] == "SOL001" and d2["destAccount"] == "SPOT"


# ------------------------------------------------------------------- env flag
def test_auto_redeem_flag(monkeypatch):
    monkeypatch.setenv("USE_TESTNET", "false")
    monkeypatch.delenv("AUTO_REDEEM_LDSOL", raising=False)
    assert bal.auto_redeem_enabled() is False            # opt-in only
    monkeypatch.setenv("AUTO_REDEEM_LDSOL", "true")
    assert bal.auto_redeem_enabled() is True
    monkeypatch.setenv("USE_TESTNET", "true")
    assert bal.auto_redeem_enabled() is False            # never on testnet