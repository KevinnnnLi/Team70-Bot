"""The trading loop: decide once per UTC day, rebalance, halt, and log."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Optional, Sequence

from . import positions, sizing, strategy
from .binance import SignalError, decision_ready
from .client import (
    ApiError,
    RoostooClient,
    ShortNotAllowedError,
    TransportError,
)
from .config import Config
from .equity import equity_usd
from .logging_utils import LogBundle
from .models import Action, Balance, ExchangeInfo, ShortPosition
from .state import State, StateStore

PAIRS = ("BTC/USD", "ETH/USD")


@dataclass
class StepResult:
    ok: bool
    sent: bool
    retryable: bool
    note: str
    row: dict


class Engine:
    def __init__(
        self,
        config: Config,
        client: RoostooClient,
        store: StateStore,
        logs: LogBundle,
        signal_source: Callable[[int], object],
        clock: Optional[Callable[[], datetime]] = None,
        sleep: Optional[Callable[[float], None]] = None,
        logger: Optional[logging.Logger] = None,
        dry_run: bool = False,
    ):
        self._config = config
        self._client = client
        self._store = store
        self._logs = logs
        self._signal_source = signal_source
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._sleep = sleep or time.sleep
        self._logger = logger or logging.getLogger("roostoo.engine")
        self._dry_run = dry_run
        self.stop_requested = False

    # -- public ---------------------------------------------------------
    def run_once(self) -> None:
        now = self._clock()
        now_ms = int(now.timestamp() * 1000)
        today = now.strftime("%Y-%m-%d")

        self._client.sync_time()
        state = self._store.load()
        exchange = self._client.exchange_info()

        equity, balance, tickers, shorts = self._mark()
        if equity <= 0:
            # Equity can only be zero if the account is empty or a response
            # was misread. Either way it is not a 100% loss, and treating it
            # as one would trip the drawdown halt permanently.
            self._logger.error(
                "equity marked at %.2f; treating it as a bad reading and "
                "skipping this loop",
                equity,
            )
            self._record(
                now,
                state,
                equity,
                balance,
                shorts,
                target="",
                order_sent=False,
                note="skipped: equity <= 0, treating the reading as bad data",
            )
            return
        state.peak_equity = max(state.peak_equity, equity)

        halt_level = state.peak_equity * (1.0 - self._config.max_drawdown)
        if not state.halted and equity <= halt_level:
            self._logger.warning(
                "drawdown halt: equity %.2f <= %.2f (peak %.2f)",
                equity,
                halt_level,
                state.peak_equity,
            )
            sent = self._flatten(exchange)
            state.halted = True
            self._store.save(state)
            equity, balance, tickers, shorts = self._mark()
            state.peak_equity = max(state.peak_equity, equity)
            self._store.save(state)
            self._record(
                now,
                state,
                equity,
                balance,
                shorts,
                target="",
                order_sent=sent,
                note=f"drawdown halt at peak {state.peak_equity:.2f}",
            )
            return

        if state.halted:
            if positions.live_position(balance, tickers, shorts) != positions.FLAT:
                self._flatten(exchange)
                equity, balance, tickers, shorts = self._mark()
                state.peak_equity = max(state.peak_equity, equity)
                self._store.save(state)
            self._record(
                now,
                state,
                equity,
                balance,
                shorts,
                target="",
                order_sent=False,
                note="halted: staying flat",
            )
            return

        made_decision = False
        if state.last_decision_date != today or not state.decision_target:
            try:
                signal_value = self._signal_source(now_ms)
            except (SignalError, TransportError) as exc:
                self._logger.info("waiting for the signal: %s", exc)
                self._store.save(state)
                self._record(
                    now,
                    state,
                    equity,
                    balance,
                    shorts,
                    target="",
                    order_sent=False,
                    note=f"waiting for signal: {exc}",
                )
                return
            if not decision_ready(signal_value.candle_open_time_ms, now_ms):
                self._store.save(state)
                self._record(
                    now,
                    state,
                    equity,
                    balance,
                    shorts,
                    target="",
                    order_sent=False,
                    note="waiting for the 00:00 UTC hourly candle to close",
                )
                return
            state.last_decision_date = today
            state.decision_target = strategy.target(
                signal_value.btc_ret_30d, signal_value.eth_ret_30d
            )
            state.decision_btc_ret = signal_value.btc_ret_30d
            state.decision_eth_ret = signal_value.eth_ret_30d
            state.decision_complete = False
            made_decision = True
            self._logger.info(
                "decision for %s: b=%.4f e=%.4f -> %s",
                today,
                signal_value.btc_ret_30d,
                signal_value.eth_ret_30d,
                state.decision_target,
            )
            self._store.save(state)

        if not made_decision and state.decision_complete:
            self._record(
                now,
                state,
                equity,
                balance,
                shorts,
                target=state.decision_target,
                order_sent=False,
                note="no order: today's decision is already handled",
            )
            return

        target = state.decision_target
        order_sent, ok, note = self._rebalance(target, exchange)
        if ok:
            state.decision_complete = True
        equity, balance, tickers, shorts = self._mark()
        state.peak_equity = max(state.peak_equity, equity)
        self._store.save(state)
        self._record(
            now,
            state,
            equity,
            balance,
            shorts,
            target=target,
            order_sent=order_sent,
            note=note,
        )

    def run_forever(self) -> None:
        while not self.stop_requested:
            try:
                self.run_once()
            except Exception:  # keep the bot alive; the next loop retries
                self._logger.exception("loop failed; will retry next cycle")
            for _ in range(int(self._config.loop_seconds)):
                if self.stop_requested:
                    return
                self._sleep(1)

    # -- trading --------------------------------------------------------
    def _rebalance(self, target: str, exchange: ExchangeInfo):
        balance = self._client.balance()
        tickers = self._fetch_tickers()
        shorts = self._client.short_positions()
        current = positions.live_position(
            balance, tickers, shorts, self._config.dust_usd
        )
        actions = positions.plan_actions(current, target)

        if not actions:
            return False, True, f"no order: already {positions.describe(current)}"

        planned = ", ".join(f"{a.kind} {a.coin}" for a in actions)
        if self._dry_run:
            self._logger.warning(
                "DRY RUN: would %s to reach %s; no orders sent", planned, target
            )
            return False, False, f"dry-run: would {planned}"

        sent_any = False
        for action in actions:
            balance = self._client.balance()
            tickers = self._fetch_tickers()
            result = self._run_action(action, balance, tickers, exchange)
            self._logs.trades.append(result.row)
            if not result.ok:
                self._logger.error(
                    "%s failed: %s (retryable=%s)",
                    action.kind,
                    result.note,
                    result.retryable,
                )
                # A non-retryable failure (for example "this competition does
                # not allow short positions") is handled: stay as we are and
                # wait for a future day's signal instead of retrying forever.
                return sent_any, not result.retryable, result.note
            if result.sent:
                self._logger.info("%s: %s", action.kind, result.note)
            sent_any = sent_any or result.sent
        return sent_any, True, f"rebalanced to {target} ({planned})"

    def _run_action(
        self,
        action: Action,
        balance: Balance,
        tickers: dict,
        exchange: ExchangeInfo,
    ) -> StepResult:
        pair = f"{action.coin}/USD"
        info = exchange.pair(pair)
        price = tickers[pair].last_price

        if action.kind == "buy":
            quantity = sizing.market_buy_quantity(
                balance.free("USD"), price, info.amount_precision
            )
            if not sizing.is_tradeable(
                quantity, price, info.mini_order, self._config.dust_usd
            ):
                return self._skip("BUY", pair, quantity, "below MiniOrder or dust floor")
            return self._submit(
                "BUY",
                pair,
                quantity,
                lambda: self._client.place_order(
                    pair, "BUY", quantity, info.amount_precision
                ),
            )

        if action.kind == "sell":
            quantity = sizing.market_sell_quantity(
                balance.free(action.coin), info.amount_precision
            )
            if not sizing.is_tradeable(
                quantity, price, info.mini_order, self._config.dust_usd
            ):
                return self._skip("SELL", pair, quantity, "below MiniOrder or dust floor")
            return self._submit(
                "SELL",
                pair,
                quantity,
                lambda: self._client.place_order(
                    pair, "SELL", quantity, info.amount_precision
                ),
            )

        if action.kind == "short_open":
            collateral = sizing.short_collateral(
                balance.free("USD"), self._config.taker_fee
            )
            if collateral < sizing.MIN_SHORT_COLLATERAL:
                return self._skip(
                    "SHORT_OPEN", pair, collateral, "collateral below the $1 minimum"
                )
            if sizing.is_dust(collateral, self._config.dust_usd):
                return self._skip(
                    "SHORT_OPEN", pair, collateral, "collateral below dust floor"
                )
            result = self._submit(
                "SHORT_OPEN",
                pair,
                collateral,
                lambda: self._client.short_open(pair, collateral),
            )
            if not result.ok:
                return result
            status = str(result.row.get("_status", "")).upper()
            if status == "OPEN":
                return result
            if status == "PENDING":
                # A limit order we never intended to leave open.
                return self._cancel_pending(pair, result, status)
            # Success on its own is not proof the short exists, so treat it
            # as unconfirmed and retry. If it did fill, the live position
            # check on the next loop stops us opening a second one.
            result.ok = False
            result.retryable = True
            result.note = (
                f"short_open returned no OPEN status (got {status or 'none'}); "
                "will confirm the position on the next loop"
            )
            result.row["err_msg"] = result.note
            return result

        if action.kind == "short_close":
            return self._submit(
                "SHORT_CLOSE", pair, None, lambda: self._client.short_close(pair)
            )

        raise ValueError(f"unknown action kind: {action.kind}")

    def _submit(self, action: str, pair: str, quantity, call) -> StepResult:
        now = self._clock()
        try:
            response = call()
        except ShortNotAllowedError as exc:
            return StepResult(
                ok=False,
                sent=False,
                retryable=False,
                note=f"short not allowed: {exc}",
                row=self._trade_row(
                    now, action, pair, quantity, False, str(exc), {}
                ),
            )
        except (ApiError, TransportError) as exc:
            return StepResult(
                ok=False,
                sent=False,
                retryable=True,
                note=str(exc),
                row=self._trade_row(
                    now, action, pair, quantity, False, str(exc), {}
                ),
            )
        row = self._trade_row(now, action, pair, quantity, True, "", response)
        row["_status"] = response.get("Status", "") if isinstance(response, dict) else ""
        row["_id"] = response.get("ID") if isinstance(response, dict) else None
        return StepResult(
            ok=True,
            sent=True,
            retryable=False,
            note=f"{action} {quantity if quantity is not None else 'all'} {pair}",
            row=row,
        )

    def _skip(self, action: str, pair: str, quantity, reason: str) -> StepResult:
        row = self._trade_row(
            self._clock(), action, pair, quantity, False, f"skipped: {reason}", {}
        )
        return StepResult(ok=True, sent=False, retryable=False, note=f"skipped: {reason}", row=row)

    def _cancel_pending(self, pair: str, result: StepResult, status: str) -> StepResult:
        order_id = result.row.get("_id")
        if order_id is not None:
            try:
                self._client.cancel_order(order_id)
            except (ApiError, TransportError) as exc:
                self._logger.error("could not cancel pending %s: %s", order_id, exc)
        result.ok = False
        result.retryable = True
        result.note = f"short order came back {status}; cancelled and will retry"
        result.row["err_msg"] = result.note
        return result

    def _flatten(self, exchange: ExchangeInfo) -> bool:
        balance = self._client.balance()
        tickers = self._fetch_tickers()
        shorts = self._client.short_positions()
        sent = False

        for coin, pair in (("BTC", "BTC/USD"), ("ETH", "ETH/USD")):
            info = exchange.pair(pair)
            price = tickers[pair].last_price
            quantity = sizing.market_sell_quantity(
                balance.free(coin), info.amount_precision
            )
            if not sizing.is_tradeable(
                quantity, price, info.mini_order, self._config.dust_usd
            ):
                continue
            result = self._submit(
                "SELL",
                pair,
                quantity,
                lambda pair=pair, quantity=quantity, info=info: self._client.place_order(
                    pair, "SELL", quantity, info.amount_precision
                ),
            )
            self._logs.trades.append(result.row)
            sent = sent or result.sent
            if not result.ok:
                self._logger.error("flatten sell %s failed: %s", pair, result.note)

        for position in shorts:
            result = self._submit(
                "SHORT_CLOSE",
                position.pair,
                None,
                lambda pair=position.pair: self._client.short_close(pair),
            )
            self._logs.trades.append(result.row)
            sent = sent or result.sent
            if not result.ok:
                self._logger.error(
                    "flatten short_close %s failed: %s", position.pair, result.note
                )
        return sent

    # -- reporting ------------------------------------------------------
    def _mark(self):
        balance = self._client.balance()
        tickers = self._fetch_tickers()
        shorts = self._client.short_positions()
        return equity_usd(balance, tickers, shorts), balance, tickers, shorts

    def _fetch_tickers(self) -> dict:
        return {pair: self._client.ticker(pair) for pair in PAIRS}

    def _record(
        self,
        now: datetime,
        state: State,
        equity: float,
        balance: Balance,
        shorts: Sequence[ShortPosition],
        target: str,
        order_sent: bool,
        note: str,
    ) -> None:
        stamp = self._iso(now)
        short_btc = sum(
            position.short_qty
            for position in shorts
            if position.pair == "BTC/USD"
        )
        self._logs.decisions.append(
            {
                "utc_time": stamp,
                "btc_ret_30d": state.decision_btc_ret,
                "eth_ret_30d": state.decision_eth_ret,
                "target": target,
                "equity": equity,
                "peak_equity": state.peak_equity,
                "halted": state.halted,
                "order_sent": order_sent,
                "note": note,
            }
        )
        self._logs.equity.append(
            {
                "utc_time": stamp,
                "equity": equity,
                "peak_equity": state.peak_equity,
                "btc_qty": balance.total("BTC"),
                "eth_qty": balance.total("ETH"),
                "usd_free": balance.free("USD"),
                "short_btc_qty": short_btc,
                "halted": state.halted,
            }
        )
        self._logger.info(
            "%s b=%s e=%s target=%s equity=%.2f peak=%.2f halted=%s "
            "order_sent=%s note=%s",
            stamp,
            _fmt(state.decision_btc_ret),
            _fmt(state.decision_eth_ret),
            target or "-",
            equity,
            state.peak_equity,
            state.halted,
            order_sent,
            note,
        )

    @staticmethod
    def _iso(now: datetime) -> str:
        return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _trade_row(
        now: datetime, action: str, pair: str, quantity, success, err_msg, response
    ) -> dict:
        request = f"{action} {pair}"
        if quantity is not None:
            request += f" qty={quantity}"
        return {
            "utc_time": Engine._iso(now),
            "action": action,
            "pair": pair,
            "request": request,
            "success": success,
            "err_msg": err_msg,
            "response": response,
        }


def _fmt(value) -> str:
    return "-" if value is None else f"{value:.4f}"
