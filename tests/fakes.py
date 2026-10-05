"""Duck-typed doubles so the engine loop can be tested without a network."""

from __future__ import annotations

from typing import Sequence

from roostoo.client import ApiError, ShortNotAllowedError
from roostoo.models import (
    Balance,
    ExchangeInfo,
    PairInfo,
    ShortPosition,
    Ticker,
    Wallet,
)

PAIRS = {
    "BTC/USD": PairInfo("BTC/USD", True, 5, 2, 1.0),
    "ETH/USD": PairInfo("ETH/USD", True, 4, 2, 1.0),
}


class FakeClient:
    """A miniature in-memory Roostoo account."""

    def __init__(
        self,
        usd_free: float = 100_000.0,
        usd_lock: float = 0.0,
        btc: float = 0.0,
        eth: float = 0.0,
        prices: dict | None = None,
        shorts: Sequence[ShortPosition] = (),
        fail_orders: int = 0,
        short_not_allowed: bool = False,
    ):
        self.usd_free = usd_free
        self.usd_lock = usd_lock
        self.coins = {"BTC": btc, "ETH": eth}
        self.prices = prices or {"BTC/USD": 50_000.0, "ETH/USD": 2_000.0}
        self.shorts = list(shorts)
        self.fail_orders = fail_orders
        self.short_not_allowed = short_not_allowed
        self.orders: list[tuple] = []
        self.attempts: list[tuple] = []
        self.sync_calls = 0

    # -- read side ------------------------------------------------------
    def sync_time(self, force: bool = False) -> int:
        self.sync_calls += 1
        return 0

    def exchange_info(self) -> ExchangeInfo:
        return ExchangeInfo(pairs=PAIRS, initial_wallet={"USD": 100_000})

    def balance(self) -> Balance:
        return Balance(
            wallets={
                "USD": Wallet(free=self.usd_free, lock=self.usd_lock),
                "BTC": Wallet(free=self.coins["BTC"], lock=0.0),
                "ETH": Wallet(free=self.coins["ETH"], lock=0.0),
            }
        )

    def ticker(self, pair: str) -> Ticker:
        return Ticker(pair=pair, last_price=self.prices[pair])

    def short_positions(self) -> list[ShortPosition]:
        return list(self.shorts)

    # -- write side -----------------------------------------------------
    def _maybe_fail(self) -> None:
        if self.fail_orders > 0:
            self.fail_orders -= 1
            raise ApiError("insufficient balance")

    def place_order(self, pair, side, quantity, amount_precision):
        self.attempts.append(("place_order", pair, side, str(quantity)))
        self._maybe_fail()
        coin = pair.split("/")[0]
        price = self.prices[pair]
        size = float(quantity)
        if side == "BUY":
            self.usd_free -= size * price
            self.coins[coin] += size
        else:
            self.coins[coin] -= size
            self.usd_free += size * price
        self.orders.append((pair, side, str(quantity)))
        return {"Success": True}

    def short_open(self, pair, collateral):
        self.attempts.append(("short_open", pair, str(collateral)))
        if self.short_not_allowed:
            raise ShortNotAllowedError(
                "this competition does not allow short positions"
            )
        self._maybe_fail()
        amount = float(collateral)
        self.usd_free -= amount
        self.usd_lock += amount
        self.shorts.append(
            ShortPosition(
                pair=pair,
                short_qty=amount / self.prices[pair],
                collateral=amount,
            )
        )
        self.orders.append((pair, "SHORT_OPEN", str(collateral)))
        return {"Success": True, "Status": "OPEN"}

    def short_close(self, pair):
        self.attempts.append(("short_close", pair))
        self._maybe_fail()
        for position in list(self.shorts):
            if position.pair == pair:
                self.shorts.remove(position)
                self.usd_lock -= position.collateral
                self.usd_free += position.collateral + position.unrealized_pnl
        self.orders.append((pair, "SHORT_CLOSE", ""))
        return {"Success": True, "FullyClosed": True}
