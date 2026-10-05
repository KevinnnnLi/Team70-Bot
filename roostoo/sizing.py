"""Order sizing and precision rules.

All arithmetic uses :class:`decimal.Decimal` so that flooring never
reintroduces the float dust the exchange would reject.
"""

from __future__ import annotations

from decimal import ROUND_FLOOR, Decimal
from typing import Union

Number = Union[int, float, str, Decimal]

TAKER_FEE = 0.001
DUST_USD = 75.0
MIN_SHORT_COLLATERAL = Decimal("1")


def _dec(value: Number) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def floor_to_precision(value: Number, precision: int) -> Decimal:
    """Floor ``value`` to ``precision`` decimal places (never rounds up)."""
    quantum = Decimal(1).scaleb(-int(precision))
    return _dec(value).quantize(quantum, rounding=ROUND_FLOOR)


def floor_to_cents(value: Number) -> Decimal:
    return floor_to_precision(value, 2)


def format_decimal(value: Number, precision: int) -> str:
    """Fixed-point string, never scientific notation."""
    return f"{_dec(value):.{int(precision)}f}"


def market_buy_quantity(
    free_usd: Number, price: Number, precision: int, taker_fee: Number = TAKER_FEE
) -> Decimal:
    """Coin quantity buyable with ``free_usd`` after reserving the taker fee."""
    price_dec = _dec(price)
    if price_dec <= 0:
        return Decimal(0)
    spendable = _dec(free_usd) / (Decimal(1) + _dec(taker_fee))
    return floor_to_precision(spendable / price_dec, precision)


def market_sell_quantity(free_coin: Number, precision: int) -> Decimal:
    return floor_to_precision(free_coin, precision)


def short_collateral(
    free_usd: Number, taker_fee: Number = TAKER_FEE
) -> Decimal:
    """Collateral to lock, floored to cents, leaving room for the open fee."""
    return floor_to_cents(_dec(free_usd) / (Decimal(1) + _dec(taker_fee)))


def notional(quantity: Number, price: Number) -> Decimal:
    return _dec(quantity) * _dec(price)


def meets_mini_order(notional_value: Number, mini_order: Number) -> bool:
    """The exchange allows an order when notional is strictly above MiniOrder."""
    return _dec(notional_value) > _dec(mini_order)


def is_dust(notional_value: Number, dust_usd: Number = DUST_USD) -> bool:
    return _dec(notional_value) < _dec(dust_usd)


def is_tradeable(
    quantity: Number,
    price: Number,
    mini_order: Number,
    dust_usd: Number = DUST_USD,
) -> bool:
    value = notional(quantity, price)
    return meets_mini_order(value, mini_order) and not is_dust(value, dust_usd)
