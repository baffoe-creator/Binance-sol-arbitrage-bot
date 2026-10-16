"""SOL balance helpers that understand Binance Simple Earn "LD" tokens.

Binance reports SOL that sits in Simple Earn Flexible as a separate asset,
``LDSOL``, inside the normal ``get_account()`` balances. A call such as
``get_asset_balance("SOL")`` only sees the spot wallet, so it ignores LDSOL.

Two different questions need two different answers:

  * "How much SOL do I own?"              -> SOL + LDSOL  (trailing stop)
  * "How much SOL can I trade right now?" -> SOL only     (order sizing)

Only explicitly allow-listed symbols are counted. Do NOT widen this to a
substring match on "SOL": BNSOL (Binance staked SOL), SOLV and similar are
different assets with different prices and would silently distort your capital
figure. Such assets are reported in ``SolBalance.other_sol_like`` for logging
only.
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_UP

logger = logging.getLogger("bot.balances")

SPOT_ASSET = "SOL"
EARN_ASSET = "LDSOL"
RECV_WINDOW = 60000

# A trade may go ahead with at least this fraction of the intended size. It
# matches the 5% drawdown used by TrailingCapitalStop, so a balance below this
# level would be halting the bot anyway.
MIN_TRADE_FRACTION = Decimal("0.95")

# Binance limits flexible redemptions to 1 request per 3 s per account. We are
# far more conservative so a failing redeem can never be hammered every cycle.
REDEEM_COOLDOWN_SECONDS = 60

_QUANT = Decimal("0.00000001")
_state: dict = {"last_redeem_attempt": None}


def _d(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(0)


@dataclass(frozen=True)
class SolBalance:
    spot_free: Decimal = Decimal(0)
    spot_locked: Decimal = Decimal(0)
    earn_free: Decimal = Decimal(0)    # LDSOL (Simple Earn Flexible)
    earn_locked: Decimal = Decimal(0)
    other_sol_like: tuple = ()         # ((asset, amount), ...) NOT counted as SOL

    @property
    def total(self) -> Decimal:
        """All SOL the account owns, wherever it sits. Use for capital tracking."""
        return self.spot_free + self.spot_locked + self.earn_free + self.earn_locked

    def describe(self) -> str:
        return (
            f"spot_free={self.spot_free} spot_locked={self.spot_locked} "
            f"LDSOL_free={self.earn_free} LDSOL_locked={self.earn_locked} "
            f"total={self.total}"
        )


def parse_sol_balance(balances) -> SolBalance:
    """Pure function over the ``balances`` list returned by ``get_account()``."""
    spot_free = spot_locked = earn_free = earn_locked = Decimal(0)
    other = []
    for row in balances or []:
        asset = str(row.get("asset", "")).upper()
        free, locked = _d(row.get("free")), _d(row.get("locked"))
        if asset == SPOT_ASSET:
            spot_free += free
            spot_locked += locked
        elif asset == EARN_ASSET:
            earn_free += free
            earn_locked += locked
        elif "SOL" in asset and (free + locked) > 0:
            other.append((asset, free + locked))
    return SolBalance(spot_free, spot_locked, earn_free, earn_locked, tuple(other))


def get_sol_balance(client) -> SolBalance:
    account = client.get_account(recvWindow=RECV_WINDOW)
    return parse_sol_balance(account.get("balances", []))


# --------------------------------------------------------------------------
# Simple Earn (flexible) access
#
# python-binance 1.0.19 (the version pinned in requirements.txt) has no
# wrapper for the current Simple Earn endpoints (its lending_* helpers target
# retired endpoints). Newer releases do, so use those when present and fall
# back to a direct signed SAPI call otherwise.
# --------------------------------------------------------------------------
def get_flexible_sol_positions(client) -> list:
    params = {"asset": SPOT_ASSET, "recvWindow": RECV_WINDOW}
    public = getattr(client, "get_simple_earn_flexible_product_position", None)
    if public is not None:
        resp = public(**params)
    else:
        resp = client._request_margin_api(
            "get", "simple-earn/flexible/position", signed=True, data=params
        )
    return list(resp.get("rows", [])) if isinstance(resp, dict) else []


def redeem_flexible_sol(client, amount: Decimal) -> dict:
    """Redeem ``amount`` SOL from Simple Earn Flexible to the Spot wallet.

    Needs the "Enable Spot & Margin Trading" permission on the API key.
    """
    positions = [p for p in get_flexible_sol_positions(client) if _d(p.get("totalAmount")) > 0]
    redeemable = [p for p in positions if p.get("canRedeem", True)]
    if not redeemable:
        raise RuntimeError("No redeemable Simple Earn flexible SOL position found")

    pos = max(redeemable, key=lambda p: _d(p.get("totalAmount")))
    product_id = pos.get("productId")
    if not product_id:
        raise RuntimeError(f"Simple Earn position has no productId: {pos}")
    if pos.get("autoSubscribe"):
        logger.warning(
            "Simple Earn auto-subscribe is ON for %s. Binance may move idle SOL "
            "back into Earn after it is redeemed; turn it off in the Binance app "
            "if you want the bot to keep SOL in Spot.", product_id,
        )

    available = _d(pos.get("totalAmount")).quantize(_QUANT, rounding=ROUND_DOWN)
    wanted = amount.quantize(_QUANT, rounding=ROUND_UP)

    params = {"productId": product_id, "destAccount": "SPOT", "recvWindow": RECV_WINDOW}
    if wanted >= available:
        params["redeemAll"] = "true"   # lowercase string: Binance rejects "True"
    else:
        params["amount"] = format(wanted, "f")

    public = getattr(client, "redeem_simple_earn_flexible_product", None)
    if public is not None:
        resp = public(**params)
    else:
        resp = client._request_margin_api(
            "post", "simple-earn/flexible/redeem", signed=True, data=params
        )
    if not (isinstance(resp, dict) and resp.get("success")):
        raise RuntimeError(f"Redeem was not accepted: {resp}")
    logger.info("Simple Earn redeem accepted: %s (params=%s)", resp, params)
    return resp


# --------------------------------------------------------------------------
# Policy layer used by the bot
# --------------------------------------------------------------------------
def auto_redeem_enabled() -> bool:
    """Opt-in via AUTO_REDEEM_LDSOL=true. Always off on testnet (no SAPI there)."""
    if os.environ.get("USE_TESTNET", "true") == "true":
        return False
    return os.environ.get("AUTO_REDEEM_LDSOL", "false").strip().lower() in {"1", "true", "yes", "on"}


def reset_redeem_cooldown() -> None:
    _state["last_redeem_attempt"] = None


@dataclass(frozen=True)
class SpotSolCheck:
    balance: SolBalance
    ready: bool            # True -> spot SOL is enough to trade right now
    code: str              # ok | no_funds | earn_manual | redeem_cooldown | redeem_failed | redeem_submitted
    reason: str = ""
    redeemed: Decimal = Decimal(0)


def ensure_spot_sol(client, required, auto_redeem: bool = False) -> SpotSolCheck:
    """Make sure the Spot wallet holds enough SOL to trade ``required``.

    Never waits. If a redeem is submitted the check reports ``ready=False`` and
    the caller should simply skip this cycle: by the next cycle the SOL has
    landed in Spot and the price edge has been re-evaluated on fresh data.
    """
    required = _d(required)
    balance = get_sol_balance(client)
    floor = required * MIN_TRADE_FRACTION

    if balance.spot_free >= floor:
        return SpotSolCheck(balance, True, "ok")

    if balance.earn_free <= 0:
        return SpotSolCheck(
            balance, False, "no_funds",
            f"Spot SOL {balance.spot_free} is below the {floor} needed and no LDSOL is available.",
        )

    if not auto_redeem:
        return SpotSolCheck(
            balance, False, "earn_manual",
            f"Spot SOL is {balance.spot_free} but {balance.earn_free} SOL sits in Simple Earn (LDSOL). "
            f"Redeem it to Spot in the Binance app, or set AUTO_REDEEM_LDSOL=true.",
        )

    now = time.monotonic()
    last = _state["last_redeem_attempt"]
    if last is not None and now - last < REDEEM_COOLDOWN_SECONDS:
        return SpotSolCheck(
            balance, False, "redeem_cooldown",
            "A redeem was attempted recently; waiting before trying again.",
        )
    _state["last_redeem_attempt"] = now

    amount = min(required - balance.spot_free, balance.earn_free)
    try:
        redeem_flexible_sol(client, amount)
    except Exception as e:
        return SpotSolCheck(balance, False, "redeem_failed", f"Auto-redeem of {amount} LDSOL failed: {e}")

    return SpotSolCheck(
        balance, False, "redeem_submitted",
        f"Redeemed {amount} SOL from Simple Earn to Spot; trading resumes next cycle.",
        redeemed=amount,
    )