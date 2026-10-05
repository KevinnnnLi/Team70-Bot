"""Binance public klines used for the 30-day signal. No API key needed."""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from .models import Candle, Signal

KLINE_URL = "https://api.binance.com/api/v3/klines"
KLINE_PATH = "/api/v3/klines"
DEFAULT_BASE_URL = "https://api.binance.com"
LOOKBACK_HOURS = 720
MIN_COMPLETED_CLOSES = LOOKBACK_HOURS + 1
HOUR_MS = 3_600_000
DAY_MS = 86_400_000
DEFAULT_LIMIT = 1000
SYMBOLS = {"BTC/USD": "BTCUSDT", "ETH/USD": "ETHUSDT"}


class SignalError(RuntimeError):
    """The Binance history is missing, malformed, or too short."""


def utc_day_start_ms(now_ms: int) -> int:
    return (int(now_ms) // DAY_MS) * DAY_MS


def decision_ready(candle_open_time_ms: int, now_ms: int) -> bool:
    """True once today's 00:00 UTC candle has closed and is available.

    The handoff asks for the decision to wait until "the hourly candle that
    contains that midnight has closed", which is the 00:00 UTC candle.
    """
    return int(candle_open_time_ms) >= utc_day_start_ms(now_ms)


def parse_kline(row: Sequence[Any]) -> Candle:
    return Candle(
        open_time_ms=int(row[0]),
        close_time_ms=int(row[6]),
        close=float(row[4]),
    )


def parse_klines(rows: Iterable[Sequence[Any]]) -> list[Candle]:
    return [parse_kline(row) for row in rows]


def completed_closes(
    rows: Iterable[Sequence[Any]],
    now_ms: int,
    minimum: int = MIN_COMPLETED_CLOSES,
) -> list[float]:
    """Closes of candles that have finished, oldest first.

    A candle is finished when its open time plus one hour is at or before
    ``now_ms``. The trailing in-progress candle is therefore dropped.
    """
    return [
        candle.close
        for candle in completed_candles(rows, now_ms=now_ms, minimum=minimum)
    ]


def completed_candles(
    rows: Iterable[Sequence[Any]],
    now_ms: int,
    minimum: int = MIN_COMPLETED_CLOSES,
) -> list[Candle]:
    candles = [
        candle
        for candle in parse_klines(rows)
        if candle.open_time_ms + HOUR_MS <= now_ms
    ]
    if len(candles) < minimum:
        raise SignalError(
            f"need at least {minimum} completed candles, got {len(candles)}"
        )
    return candles


def return_30d(closes: Sequence[float]) -> float:
    if len(closes) < MIN_COMPLETED_CLOSES:
        raise SignalError(
            f"need at least {MIN_COMPLETED_CLOSES} closes, got {len(closes)}"
        )
    start = closes[-MIN_COMPLETED_CLOSES]
    if start == 0:
        raise SignalError("30-day-ago close is zero; cannot compute a return")
    return closes[-1] / start - 1.0


def fetch_klines(
    transport,
    symbol: str,
    limit: int = DEFAULT_LIMIT,
    base_url: str = DEFAULT_BASE_URL,
) -> list:
    url = f"{base_url.rstrip('/')}{KLINE_PATH}"
    response = transport.get(
        url, params={"symbol": symbol, "interval": "1h", "limit": limit}
    )
    if response.status_code != 200:
        raise SignalError(
            f"Binance klines for {symbol} returned HTTP {response.status_code}: "
            f"{response.text[:200]}"
        )
    try:
        rows = response.json()
    except ValueError as exc:
        raise SignalError(f"Binance klines for {symbol} was not JSON") from exc
    if not isinstance(rows, list) or not rows:
        raise SignalError(f"Binance klines for {symbol} was empty")
    return rows


def fetch_30d_return(
    transport,
    symbol: str,
    now_ms: int,
    base_url: str = DEFAULT_BASE_URL,
) -> tuple[float, Candle]:
    rows = fetch_klines(transport, symbol, base_url=base_url)
    candles = completed_candles(rows, now_ms=now_ms)
    closes = [candle.close for candle in candles]
    return return_30d(closes), candles[-1]


def fetch_signal(
    transport, now_ms: int, base_url: str = DEFAULT_BASE_URL
) -> Signal:
    btc_ret, btc_candle = fetch_30d_return(
        transport, SYMBOLS["BTC/USD"], now_ms, base_url
    )
    eth_ret, eth_candle = fetch_30d_return(
        transport, SYMBOLS["ETH/USD"], now_ms, base_url
    )
    if btc_candle.open_time_ms != eth_candle.open_time_ms:
        raise SignalError(
            "BTC and ETH klines disagree on the latest completed candle: "
            f"{btc_candle.open_time_ms} vs {eth_candle.open_time_ms}"
        )
    return Signal(
        btc_ret_30d=btc_ret,
        eth_ret_30d=eth_ret,
        candle_open_time_ms=btc_candle.open_time_ms,
    )
