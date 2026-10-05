"""Live-position detection and the current -> target action table."""

from __future__ import annotations

from typing import Mapping, Sequence

from . import sizing
from .models import Action, Balance, ShortPosition, Ticker

FLAT = "flat"
LONG_BTC = "long_btc"
LONG_ETH = "long_eth"
SHORT_BTC = "short_btc"
MIXED = "mixed"

ENTRY_ACTIONS = {
    LONG_BTC: (("buy", "BTC"),),
    LONG_ETH: (("buy", "ETH"),),
    SHORT_BTC: (("short_open", "BTC"),),
}


def live_position(
    balance: Balance,
    tickers: Mapping[str, Ticker],
    shorts: Sequence[ShortPosition],
    dust_usd: float = sizing.DUST_USD,
) -> str:
    """What the account is actually holding right now."""
    if any(position.short_qty > 0 for position in shorts):
        return SHORT_BTC

    btc_usd = balance.total("BTC") * tickers["BTC/USD"].last_price
    eth_usd = balance.total("ETH") * tickers["ETH/USD"].last_price
    holds_btc = btc_usd >= dust_usd
    holds_eth = eth_usd >= dust_usd

    if holds_btc and holds_eth:
        return MIXED
    if holds_btc:
        return LONG_BTC
    if holds_eth:
        return LONG_ETH
    return FLAT


def plan_actions(current: str, target_name: str) -> list[Action]:
    """Ordered steps to get from ``current`` to ``target_name``.

    Old risk is always closed before the new position is opened, and an
    unchanged target returns no actions.
    """
    if target_name not in ENTRY_ACTIONS:
        raise ValueError(f"unknown target: {target_name}")
    if current == target_name:
        return []

    actions: list[Action] = []
    if current == LONG_BTC:
        actions.append(Action("sell", "BTC"))
    elif current == LONG_ETH:
        actions.append(Action("sell", "ETH"))
    elif current == SHORT_BTC:
        actions.append(Action("short_close", "BTC"))
    elif current == MIXED:
        actions.append(Action("sell", "BTC"))
        actions.append(Action("sell", "ETH"))
    elif current != FLAT:
        raise ValueError(f"unknown current position: {current}")

    actions.extend(Action(kind, coin) for kind, coin in ENTRY_ACTIONS[target_name])
    return actions


def describe(position: str) -> str:
    return {
        FLAT: "flat",
        LONG_BTC: "long Bitcoin",
        LONG_ETH: "long Ethereum",
        SHORT_BTC: "short Bitcoin",
        MIXED: "holding both coins (anomaly)",
    }.get(position, position)
