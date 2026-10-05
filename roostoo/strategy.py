"""The 30-day relative momentum rule. This is the whole trading signal."""

from __future__ import annotations

TARGETS = ("long_btc", "long_eth", "short_btc")


def target(btc_ret_30d: float, eth_ret_30d: float) -> str:
    """Return 'long_btc', 'long_eth', or 'short_btc'."""
    b = btc_ret_30d
    e = eth_ret_30d
    if b > 0 and e > 0:
        return "long_btc" if b >= e else "long_eth"
    if b > 0:
        return "long_btc"
    if e > 0:
        return "long_eth"
    return "short_btc"


def describe(target_name: str) -> str:
    return {
        "long_btc": "long 100% Bitcoin",
        "long_eth": "long 100% Ethereum",
        "short_btc": "short 100% Bitcoin",
    }.get(target_name, target_name)
