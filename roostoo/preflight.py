"""Read-only startup check. Never sends an order."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, List, Optional

from . import strategy
from .client import RoostooClient, require_tradeable_pairs
from .equity import equity_usd
from .positions import describe as describe_position
from .positions import live_position
from .state import StateStore

PAIRS = ("BTC/USD", "ETH/USD")


@dataclass
class PreflightReport:
    ok: bool = True
    lines: List[str] = field(default_factory=list)

    def text(self) -> str:
        return "\n".join(self.lines)


def run_preflight(
    client: RoostooClient,
    store: StateStore,
    signal_source: Callable[[int], object],
    now_ms: Optional[int] = None,
) -> PreflightReport:
    report = PreflightReport()
    if now_ms is None:
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)

    try:
        offset = client.sync_time(force=True)
        report.lines.append(f"server time : OK (offset {offset:+d} ms)")
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        report.ok = False
        report.lines.append(f"server time : FAILED ({exc})")

    exchange = None
    try:
        exchange = client.exchange_info()
        for pair in PAIRS:
            info = exchange.pair(pair)
            report.lines.append(
                f"{pair:<12}: CanTrade={info.can_trade} "
                f"amountPrecision={info.amount_precision} "
                f"pricePrecision={info.price_precision} "
                f"MiniOrder={info.mini_order}"
            )
        report.lines.append(f"IsRunning   : {exchange.is_running}")
        report.lines.append(f"InitialWallet: {dict(exchange.initial_wallet)}")
        require_tradeable_pairs(exchange, PAIRS)
    except Exception as exc:  # noqa: BLE001
        report.ok = False
        report.lines.append(f"exchange info: FAILED ({exc})")

    balance = None
    try:
        balance = client.balance()
        report.lines.append(
            f"balance     : USD free={balance.free('USD'):.2f} "
            f"lock={balance.lock('USD'):.2f} "
            f"BTC={balance.total('BTC')} ETH={balance.total('ETH')}"
        )
    except Exception as exc:  # noqa: BLE001
        report.ok = False
        report.lines.append(f"balance     : FAILED ({exc})")

    tickers = {}
    try:
        for pair in PAIRS:
            ticker = client.ticker(pair)
            tickers[pair] = ticker
            report.lines.append(f"ticker {pair:<6}: {ticker.last_price}")
    except Exception as exc:  # noqa: BLE001
        report.ok = False
        report.lines.append(f"ticker      : FAILED ({exc})")

    try:
        signal_value = signal_source(now_ms)
        candle = datetime.fromtimestamp(
            signal_value.candle_open_time_ms / 1000, tz=timezone.utc
        )
        report.lines.append(
            f"signal      : b={signal_value.btc_ret_30d:.4%} "
            f"e={signal_value.eth_ret_30d:.4%} "
            f"(candle {candle:%Y-%m-%d %H:%M} UTC)"
        )
        chosen = strategy.target(
            signal_value.btc_ret_30d, signal_value.eth_ret_30d
        )
        report.lines.append(f"target      : {chosen} ({strategy.describe(chosen)})")
    except Exception as exc:  # noqa: BLE001
        report.ok = False
        report.lines.append(f"signal      : FAILED ({exc})")

    try:
        shorts = client.short_positions()
        if balance is not None and len(tickers) == len(PAIRS):
            position = live_position(balance, tickers, shorts)
            report.lines.append(
                f"position    : {describe_position(position)} "
                f"equity={equity_usd(balance, tickers, shorts):.2f}"
            )
        else:
            report.lines.append("position    : skipped (missing balance/ticker)")
    except Exception as exc:  # noqa: BLE001
        report.ok = False
        report.lines.append(f"position    : FAILED ({exc})")

    state = store.load()
    report.lines.append(
        f"state       : last_decision_date={state.last_decision_date} "
        f"peak_equity={state.peak_equity:.2f} halted={state.halted}"
    )
    return report
