"""Roostoo REST client: signing, retries, and tolerant response parsing."""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Any, Mapping, Optional, Sequence

from . import signing, sizing
from .config import Config
from .models import (
    Balance,
    ExchangeInfo,
    PairInfo,
    ShortPosition,
    Ticker,
    Wallet,
)
from .transport import HttpResponse, RequestsTransport, TransportError

RETRY_BACKOFF_SECONDS = (2, 4, 8)
SHORT_NOT_ALLOWED_MARKER = "does not allow short"


class RoostooError(RuntimeError):
    """Base class for Roostoo request failures."""


class ApiError(RoostooError):
    """HTTP 200 with ``Success: false``."""

    def __init__(self, err_msg: str, body: Optional[Mapping[str, Any]] = None):
        super().__init__(err_msg)
        self.err_msg = err_msg
        self.body = dict(body or {})


class ShortNotAllowedError(ApiError):
    """The competition account may not open shorts."""


def _error_for(err_msg: str, body: Mapping[str, Any]) -> ApiError:
    if SHORT_NOT_ALLOWED_MARKER in (err_msg or "").lower():
        return ShortNotAllowedError(err_msg, body)
    return ApiError(err_msg, body)


def _looks_like_pairs(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and bool(value)
        and any(isinstance(entry, dict) for entry in value.values())
        and any(
            isinstance(entry, dict) and "CanTrade" in entry
            for entry in value.values()
        )
    )


def _extract_pair_map(body: Mapping[str, Any]) -> Optional[dict]:
    data = body.get("Data")
    containers = [body]
    if isinstance(data, dict):
        containers.append(data)
    for container in containers:
        for key in ("TradePairs", "Pairs", "pairInfo", "PairInfo"):
            value = container.get(key)
            if _looks_like_pairs(value):
                return value
    for container in containers:
        if _looks_like_pairs(container):
            return container
    return None


def _looks_like_wallets(value: Any) -> bool:
    return isinstance(value, dict) and any(
        isinstance(entry, dict) and ("Free" in entry or "Lock" in entry)
        for entry in value.values()
    )


def _extract_wallets(body: Mapping[str, Any]) -> Mapping[str, Any]:
    """Find the coin->wallet map in the several shapes the API uses.

    The live endpoint wraps it as ``SpotWallet``; older fixtures put the
    wallets at the top level or under ``Data``.
    """
    data = body.get("Data")
    containers = [body]
    if isinstance(data, dict):
        containers.append(data)
    for container in containers:
        for key in ("SpotWallet", "Wallet", "Wallets", "Balance"):
            value = container.get(key)
            if _looks_like_wallets(value):
                return value
    for container in containers:
        if _looks_like_wallets(container):
            return container
    return {}


class RoostooClient:
    def __init__(
        self,
        config: Config,
        transport=None,
        clock=None,
        sleep=None,
        logger: Optional[logging.Logger] = None,
    ):
        self._config = config
        self._transport = transport or RequestsTransport(config.request_timeout)
        self._clock = clock or (lambda: int(time.time() * 1000))
        self._sleep = sleep or time.sleep
        self._logger = logger or logging.getLogger("roostoo.client")
        self._offset_ms = 0
        self._last_sync_local_ms: Optional[int] = None

    # -- time -----------------------------------------------------------
    @property
    def time_offset_ms(self) -> int:
        return self._offset_ms

    def _now_ms(self) -> int:
        return int(self._clock())

    def timestamp(self) -> int:
        return signing.signed_timestamp(self._now_ms(), self._offset_ms)

    def sync_time(self, force: bool = False) -> int:
        now = self._now_ms()
        if (
            not force
            and self._last_sync_local_ms is not None
            and abs(now - self._last_sync_local_ms)
            < self._config.time_sync_seconds * 1000
        ):
            return self._offset_ms
        response = self._with_retries(
            "GET /v3/serverTime",
            lambda: self._send("GET", "/v3/serverTime", {}, signed=False),
        )
        body = self._parse_body(response, "/v3/serverTime")
        try:
            server_ms = int(body["ServerTime"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TransportError(
                f"/v3/serverTime did not return ServerTime: {body}"
            ) from exc
        self._offset_ms = signing.timestamp_offset(server_ms, now)
        self._last_sync_local_ms = now
        return self._offset_ms

    # -- endpoints ------------------------------------------------------
    def exchange_info(self) -> ExchangeInfo:
        body = self._request("GET", "/v3/exchangeInfo", signed=False)
        pair_map = _extract_pair_map(body)
        if pair_map is None:
            raise ApiError(
                "exchangeInfo did not include a trade-pair map", body
            )
        pairs = {
            pair: PairInfo.from_api(pair, entry)
            for pair, entry in pair_map.items()
            if isinstance(entry, dict)
        }
        initial: Mapping[str, Any] = {}
        if isinstance(body.get("InitialWallet"), dict):
            initial = body["InitialWallet"]
        elif isinstance(body.get("Data"), dict) and isinstance(
            body["Data"].get("InitialWallet"), dict
        ):
            initial = body["Data"]["InitialWallet"]
        is_running = body.get("IsRunning")
        if is_running is None and isinstance(body.get("Data"), dict):
            is_running = body["Data"].get("IsRunning")
        return ExchangeInfo(
            pairs=pairs,
            initial_wallet=initial,
            is_running=True if is_running is None else bool(is_running),
        )

    def balance(self) -> Balance:
        body = self._request("GET", "/v3/balance", signed=True)
        container = _extract_wallets(body)
        wallets = {
            coin: Wallet.from_api(entry)
            for coin, entry in container.items()
            if isinstance(entry, dict)
            and ("Free" in entry or "Lock" in entry)
        }
        return Balance(wallets=wallets)

    def ticker(self, pair: str) -> Ticker:
        body = self._request(
            "GET",
            "/v3/ticker",
            params={"timestamp": self.timestamp(), "pair": pair},
            signed=False,
        )
        data = body.get("Data")
        if isinstance(data, dict):
            entry = data.get(pair)
            if not isinstance(entry, dict) and "LastPrice" in data:
                entry = data
            if isinstance(entry, dict):
                return Ticker.from_api(pair, entry)
        if isinstance(data, list):
            for row in data:
                if isinstance(row, dict) and str(row.get("Pair")) == pair:
                    return Ticker.from_api(pair, row)
        raise TransportError(f"/v3/ticker did not include {pair}: {body}")

    def short_positions(self) -> list[ShortPosition]:
        body = self._request("GET", "/v6/short_positions", signed=True)
        entries = body.get("Positions")
        if entries is None:
            data = body.get("Data")
            if isinstance(data, list):
                entries = data
            elif isinstance(data, dict):
                entries = data.get("Positions", [])
        if not isinstance(entries, list):
            entries = []
        return [
            ShortPosition.from_api(entry)
            for entry in entries
            if isinstance(entry, dict)
        ]

    def place_order(
        self, pair: str, side: str, quantity: Decimal, amount_precision: int
    ) -> dict:
        return self._request(
            "POST",
            "/v3/place_order",
            params={
                "pair": pair,
                "side": side,
                "type": "MARKET",
                "quantity": sizing.format_decimal(quantity, amount_precision),
            },
            signed=True,
        )

    def cancel_order(self, order_id: Any) -> dict:
        return self._request(
            "POST", "/v3/cancel_order", params={"id": order_id}, signed=True
        )

    def short_open(self, pair: str, collateral: Decimal) -> dict:
        return self._request(
            "POST",
            "/v6/short_open",
            params={"pair": pair, "collateral": f"{collateral:.2f}"},
            signed=True,
        )

    def short_close(self, pair: str) -> dict:
        return self._request(
            "POST", "/v6/short_close", params={"pair": pair}, signed=True
        )

    # -- plumbing -------------------------------------------------------
    def _request(
        self,
        method: str,
        path: str,
        params: Optional[Mapping[str, Any]] = None,
        signed: bool = True,
    ) -> dict:
        if signed:
            self.sync_time()
        resynced = False
        while True:
            response = self._with_retries(
                f"{method} {path}",
                lambda: self._send(method, path, params or {}, signed),
            )
            body = self._parse_body(response, path)
            success = body.get("Success")
            err_msg = str(
                body.get("ErrMsg")
                or body.get("Error")
                or body.get("Message")
                or ""
            )
            if success is True:
                return body
            if "Success" not in body and not err_msg:
                # Some public endpoints (notably /v3/exchangeInfo) return a
                # bare payload with no Success flag at all.
                self._logger.debug(
                    "%s returned no Success flag; accepting the body", path
                )
                return body
            if not err_msg:
                err_msg = f"{path} returned Success=false"
            if signed and not resynced and signing.is_timestamp_error(err_msg):
                self._logger.warning(
                    "server rejected the timestamp (%s); resyncing", err_msg
                )
                self.sync_time(force=True)
                resynced = True
                continue
            raise _error_for(err_msg, body)

    def _send(
        self, method: str, path: str, params: Mapping[str, Any], signed: bool
    ) -> HttpResponse:
        url = f"{self._config.base_url}{path}"
        data = {key: str(value) for key, value in params.items()}
        headers = {"RST-API-KEY": self._config.api_key}
        if signed:
            data["timestamp"] = str(self.timestamp())
            headers["MSG-SIGNATURE"] = signing.sign(
                self._config.secret_key, data
            )
        if method == "GET":
            return self._transport.get(url, params=data, headers=headers)
        return self._transport.post(url, data=data, headers=headers)

    def _with_retries(self, description: str, call) -> HttpResponse:
        attempt = 0
        while True:
            try:
                response = call()
            except TransportError as exc:
                if attempt < len(RETRY_BACKOFF_SECONDS):
                    delay = RETRY_BACKOFF_SECONDS[attempt]
                    self._logger.warning(
                        "%s failed (%s); retrying in %ss",
                        description,
                        exc,
                        delay,
                    )
                    self._sleep(delay)
                    attempt += 1
                    continue
                raise
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < len(RETRY_BACKOFF_SECONDS):
                    delay = RETRY_BACKOFF_SECONDS[attempt]
                    self._logger.warning(
                        "%s returned HTTP %s; retrying in %ss",
                        description,
                        response.status_code,
                        delay,
                    )
                    self._sleep(delay)
                    attempt += 1
                    continue
                raise TransportError(
                    f"{description}: HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                )
            if response.status_code >= 400:
                raise TransportError(
                    f"{description}: HTTP {response.status_code}: "
                    f"{response.text[:200]}"
                )
            return response

    @staticmethod
    def _parse_body(response: HttpResponse, path: str) -> dict:
        try:
            body = response.json()
        except ValueError as exc:
            raise TransportError(
                f"{path}: response was not JSON: {response.text[:200]}"
            ) from exc
        if not isinstance(body, dict):
            raise TransportError(f"{path}: response was not a JSON object")
        return body


def require_tradeable_pairs(
    exchange: ExchangeInfo, pairs: Sequence[str] = ("BTC/USD", "ETH/USD")
) -> None:
    """Refuse to run unless every configured pair reports ``CanTrade``."""
    problems = []
    if not exchange.is_running:
        problems.append("the exchange reports IsRunning=false")
    for pair in pairs:
        try:
            info = exchange.pair(pair)
        except KeyError:
            problems.append(f"{pair} is missing")
            continue
        if not info.can_trade:
            problems.append(f"{pair} has CanTrade=false")
    if problems:
        raise RoostooError("exchange info is not tradeable: " + "; ".join(problems))
