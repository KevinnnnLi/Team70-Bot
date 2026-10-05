"""Plain data structures shared between the API client and the strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _to_int(value: Any, default: int = 0) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Wallet:
    free: float = 0.0
    lock: float = 0.0

    @property
    def total(self) -> float:
        return self.free + self.lock

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "Wallet":
        return cls(
            free=_to_float(data.get("Free")),
            lock=_to_float(data.get("Lock")),
        )


@dataclass(frozen=True)
class Balance:
    wallets: Mapping[str, Wallet]

    def _wallet(self, coin: str) -> Wallet:
        return self.wallets.get(coin, Wallet())

    def free(self, coin: str) -> float:
        return self._wallet(coin).free

    def lock(self, coin: str) -> float:
        return self._wallet(coin).lock

    def total(self, coin: str) -> float:
        return self._wallet(coin).total

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "Balance":
        wallets = {
            coin: Wallet.from_api(entry)
            for coin, entry in data.items()
            if isinstance(entry, Mapping)
        }
        return cls(wallets=wallets)


@dataclass(frozen=True)
class Ticker:
    pair: str
    last_price: float
    max_bid: float = 0.0
    min_ask: float = 0.0

    @classmethod
    def from_api(cls, pair: str, data: Mapping[str, Any]) -> "Ticker":
        return cls(
            pair=pair,
            last_price=_to_float(data.get("LastPrice")),
            max_bid=_to_float(data.get("MaxBid")),
            min_ask=_to_float(data.get("MinAsk")),
        )


@dataclass(frozen=True)
class ShortPosition:
    pair: str
    short_qty: float = 0.0
    collateral: float = 0.0
    unrealized_pnl: float = 0.0
    position_value: float = 0.0

    @classmethod
    def from_api(cls, data: Mapping[str, Any]) -> "ShortPosition":
        return cls(
            pair=str(data.get("Pair", "")),
            short_qty=_to_float(data.get("ShortQty")),
            collateral=_to_float(data.get("Collateral")),
            unrealized_pnl=_to_float(data.get("UnrealizedPNL")),
            position_value=_to_float(data.get("PositionValue")),
        )


@dataclass(frozen=True)
class PairInfo:
    pair: str
    can_trade: bool
    amount_precision: int
    price_precision: int
    mini_order: float

    @classmethod
    def from_api(cls, pair: str, data: Mapping[str, Any]) -> "PairInfo":
        return cls(
            pair=str(data.get("Pair", pair)),
            can_trade=bool(data.get("CanTrade", False)),
            amount_precision=_to_int(data.get("AmountPrecision")),
            price_precision=_to_int(data.get("PricePrecision")),
            mini_order=_to_float(data.get("MiniOrder")),
        )


@dataclass(frozen=True)
class ExchangeInfo:
    pairs: Mapping[str, PairInfo]
    initial_wallet: Mapping[str, Any] = field(default_factory=dict)
    is_running: bool = True

    def pair(self, pair: str) -> PairInfo:
        try:
            return self.pairs[pair]
        except KeyError as exc:
            raise KeyError(
                f"{pair} is not in the exchange info response: "
                f"{sorted(self.pairs)}"
            ) from exc


@dataclass(frozen=True)
class Candle:
    open_time_ms: int
    close_time_ms: int
    close: float


@dataclass(frozen=True)
class Signal:
    btc_ret_30d: float
    eth_ret_30d: float
    candle_open_time_ms: int


@dataclass(frozen=True)
class Action:
    """One order-sized step, e.g. Action("sell", "ETH")."""

    kind: str
    coin: str
