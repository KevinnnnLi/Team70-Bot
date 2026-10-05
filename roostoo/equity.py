"""Mark-to-market equity in USD, using Roostoo prices."""

from __future__ import annotations

from typing import Mapping, Sequence

from .models import Balance, ShortPosition, Ticker


def equity_usd(
    balance: Balance,
    tickers: Mapping[str, Ticker],
    shorts: Sequence[ShortPosition],
) -> float:
    """USD.Free + USD.Lock + coin value + unrealized short P&L.

    ``USD.Lock`` already contains short collateral, so collateral is never
    added a second time.
    """
    usd = balance.free("USD") + balance.lock("USD")
    btc = balance.total("BTC") * tickers["BTC/USD"].last_price
    eth = balance.total("ETH") * tickers["ETH/USD"].last_price
    unrealized = sum(position.unrealized_pnl for position in shorts)
    return usd + btc + eth + unrealized
