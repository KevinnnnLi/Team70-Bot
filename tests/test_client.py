import json
import unittest
from decimal import Decimal
from pathlib import Path

from roostoo import signing
from roostoo.client import (
    ApiError,
    RoostooClient,
    ShortNotAllowedError,
    TransportError,
)
from roostoo.config import Config
from roostoo.transport import HttpResponse

NOW = 1_700_000_000_000
BASE_URL = "https://mock-api.roostoo.com"


def body(payload):
    return HttpResponse(200, json.dumps(payload))


def server_time(ms=NOW):
    return body({"Success": True, "ServerTime": ms})


def http_error(code):
    return HttpResponse(code, "server exploded")


class FakeTransport:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def _next(self):
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def get(self, url, params=None, headers=None):
        self.calls.append(("GET", url, dict(params or {}), dict(headers or {})))
        return self._next()

    def post(self, url, data=None, headers=None):
        self.calls.append(("POST", url, dict(data or {}), dict(headers or {})))
        return self._next()


def make_client(responses, secret="topsecret", key="key123"):
    transport = FakeTransport(responses)
    sleeps = []
    config = Config(
        api_key=key,
        secret_key=secret,
        base_url=BASE_URL,
        state_path=Path("state.json"),
        log_dir=Path("logs"),
    )
    client = RoostooClient(
        config,
        transport=transport,
        clock=lambda: NOW,
        sleep=sleeps.append,
    )
    return client, transport, sleeps


class SigningTests(unittest.TestCase):
    def test_signed_get_syncs_time_then_signs_the_timestamp(self):
        client, transport, _ = make_client(
            [
                server_time(),
                body({"Success": True, "USD": {"Free": 10.0, "Lock": 0.0}}),
            ]
        )
        client.balance()

        self.assertEqual(transport.calls[0][1], f"{BASE_URL}/v3/serverTime")
        method, url, params, headers = transport.calls[1]
        self.assertEqual(method, "GET")
        self.assertEqual(url, f"{BASE_URL}/v3/balance")
        self.assertEqual(params, {"timestamp": str(NOW)})
        self.assertEqual(headers["RST-API-KEY"], "key123")
        self.assertEqual(
            headers["MSG-SIGNATURE"],
            signing.sign("topsecret", {"timestamp": str(NOW)}),
        )

    def test_place_order_signs_exactly_the_documented_parameters(self):
        client, transport, _ = make_client([server_time(), body({"Success": True})])
        client.place_order(
            "BTC/USD", "BUY", Decimal("0.50000"), amount_precision=5
        )

        _, url, data, headers = transport.calls[1]
        self.assertEqual(url, f"{BASE_URL}/v3/place_order")
        self.assertEqual(
            data,
            {
                "pair": "BTC/USD",
                "side": "BUY",
                "type": "MARKET",
                "quantity": "0.50000",
                "timestamp": str(NOW),
            },
        )
        self.assertEqual(
            headers["MSG-SIGNATURE"], signing.sign("topsecret", data)
        )
        self.assertNotIn("order_type", data)

    def test_short_open_sends_string_collateral_and_no_order_type(self):
        client, transport, _ = make_client([server_time(), body({"Success": True})])
        client.short_open("BTC/USD", Decimal("999.00"))
        _, url, data, headers = transport.calls[1]
        self.assertEqual(url, f"{BASE_URL}/v6/short_open")
        self.assertEqual(
            data,
            {
                "pair": "BTC/USD",
                "collateral": "999.00",
                "timestamp": str(NOW),
            },
        )
        self.assertEqual(
            headers["MSG-SIGNATURE"], signing.sign("topsecret", data)
        )

    def test_short_close_sends_only_pair_and_timestamp(self):
        client, transport, _ = make_client([server_time(), body({"Success": True})])
        client.short_close("BTC/USD")
        _, url, data, _ = transport.calls[1]
        self.assertEqual(url, f"{BASE_URL}/v6/short_close")
        self.assertEqual(
            data, {"pair": "BTC/USD", "timestamp": str(NOW)}
        )

    def test_cancel_order_uses_order_id_not_id(self):
        """The official docs name the parameter order_id."""
        client, transport, _ = make_client([server_time(), body({"Success": True})])
        client.cancel_order(999)
        _, url, data, headers = transport.calls[1]
        self.assertEqual(url, f"{BASE_URL}/v3/cancel_order")
        self.assertEqual(
            data, {"order_id": "999", "timestamp": str(NOW)}
        )
        self.assertNotIn("id", data)
        self.assertEqual(
            headers["MSG-SIGNATURE"], signing.sign("topsecret", data)
        )

    def test_market_sell_signs_the_same_parameters_with_side_sell(self):
        client, transport, _ = make_client([server_time(), body({"Success": True})])
        client.place_order(
            "ETH/USD", "SELL", Decimal("18.0000"), amount_precision=4
        )
        _, url, data, headers = transport.calls[1]
        self.assertEqual(
            data,
            {
                "pair": "ETH/USD",
                "side": "SELL",
                "type": "MARKET",
                "quantity": "18.0000",
                "timestamp": str(NOW),
            },
        )
        self.assertEqual(
            headers["MSG-SIGNATURE"], signing.sign("topsecret", data)
        )

    def test_ticker_is_unsigned_but_still_carries_a_timestamp(self):
        client, transport, _ = make_client(
            [
                body(
                    {
                        "Success": True,
                        "Data": {
                            "BTC/USD": {
                                "LastPrice": 64000.0,
                                "MaxBid": 63990.0,
                                "MinAsk": 64010.0,
                            }
                        },
                    }
                )
            ]
        )
        ticker = client.ticker("BTC/USD")

        self.assertEqual(len(transport.calls), 1)
        method, url, params, headers = transport.calls[0]
        self.assertEqual(url, f"{BASE_URL}/v3/ticker")
        self.assertEqual(params, {"timestamp": str(NOW), "pair": "BTC/USD"})
        self.assertNotIn("MSG-SIGNATURE", headers)
        self.assertEqual(ticker.last_price, 64000.0)


class ErrorTests(unittest.TestCase):
    def test_success_false_raises_api_error(self):
        client, _, _ = make_client(
            [server_time(), body({"Success": False, "ErrMsg": "insufficient balance"})]
        )
        with self.assertRaises(ApiError) as caught:
            client.balance()
        self.assertIn("insufficient balance", str(caught.exception))

    def test_short_not_allowed_is_a_distinct_error_type(self):
        client, _, _ = make_client(
            [
                server_time(),
                body(
                    {
                        "Success": False,
                        "ErrMsg": "this competition does not allow short positions",
                    }
                ),
            ]
        )
        with self.assertRaises(ShortNotAllowedError):
            client.short_open("BTC/USD", Decimal("999.00"))


class RetryTests(unittest.TestCase):
    def test_retries_http_500_with_2_4_8_backoff(self):
        client, transport, sleeps = make_client(
            [
                server_time(),
                http_error(500),
                http_error(500),
                http_error(500),
                body({"Success": True, "USD": {"Free": 1.0, "Lock": 0.0}}),
            ]
        )
        balance = client.balance()
        self.assertEqual(balance.free("USD"), 1.0)
        self.assertEqual(sleeps, [2, 4, 8])
        self.assertEqual(len(transport.calls), 5)

    def test_gives_up_after_three_retries(self):
        client, _, sleeps = make_client(
            [server_time(), http_error(500), http_error(500), http_error(500), http_error(500)]
        )
        with self.assertRaises(TransportError):
            client.balance()
        self.assertEqual(sleeps, [2, 4, 8])

    def test_retries_transport_exceptions(self):
        client, _, sleeps = make_client(
            [
                server_time(),
                TransportError("connection reset"),
                body({"Success": True, "USD": {"Free": 2.0, "Lock": 0.0}}),
            ]
        )
        self.assertEqual(client.balance().free("USD"), 2.0)
        self.assertEqual(sleeps, [2])

    def test_timestamp_error_resyncs_and_retries_once(self):
        client, transport, _ = make_client(
            [
                server_time(),
                body({"Success": False, "ErrMsg": "timestamp expired"}),
                server_time(NOW + 5_000),
                body({"Success": True, "USD": {"Free": 3.0, "Lock": 0.0}}),
            ]
        )
        balance = client.balance()
        self.assertEqual(balance.free("USD"), 3.0)
        server_time_calls = [
            call for call in transport.calls if call[1].endswith("/v3/serverTime")
        ]
        self.assertEqual(len(server_time_calls), 2)
        self.assertEqual(client.time_offset_ms, 5_000)


class ParsingTests(unittest.TestCase):
    def test_exchange_info_accepts_trade_pairs_at_the_top_level(self):
        client, _, _ = make_client(
            [
                body(
                    {
                        "Success": True,
                        "TradePairs": {
                            "BTC/USD": {
                                "Pair": "BTC/USD",
                                "CanTrade": True,
                                "AmountPrecision": 5,
                                "PricePrecision": 2,
                                "MiniOrder": 1.0,
                            },
                            "ETH/USD": {
                                "Pair": "ETH/USD",
                                "CanTrade": True,
                                "AmountPrecision": 4,
                                "PricePrecision": 2,
                                "MiniOrder": 1.0,
                            },
                        },
                        "InitialWallet": {"USD": 100000},
                    }
                )
            ]
        )
        info = client.exchange_info()
        self.assertTrue(info.pair("BTC/USD").can_trade)
        self.assertEqual(info.pair("ETH/USD").amount_precision, 4)
        self.assertEqual(info.pair("BTC/USD").mini_order, 1.0)
        self.assertEqual(info.initial_wallet, {"USD": 100000})

    def test_exchange_info_accepts_pairs_nested_under_data(self):
        client, _, _ = make_client(
            [
                body(
                    {
                        "Success": True,
                        "Data": {
                            "TradePairs": {
                                "BTC/USD": {
                                    "Pair": "BTC/USD",
                                    "CanTrade": True,
                                    "AmountPrecision": 5,
                                    "PricePrecision": 2,
                                    "MiniOrder": 1.0,
                                }
                            }
                        },
                    }
                )
            ]
        )
        self.assertTrue(client.exchange_info().pair("BTC/USD").can_trade)

    def test_exchange_info_without_a_success_field_is_not_an_error(self):
        """The live API returns IsRunning/InitialWallet/TradePairs only."""
        client, _, _ = make_client(
            [
                body(
                    {
                        "IsRunning": True,
                        "InitialWallet": {"USD": 50000},
                        "TradePairs": {
                            "BTC/USD": {
                                "Coin": "BTC",
                                "Unit": "USD",
                                "CanTrade": True,
                                "PricePrecision": 2,
                                "AmountPrecision": 5,
                                "MiniOrder": 1,
                                "AssetType": "crypto",
                            },
                            "ETH/USD": {
                                "Coin": "ETH",
                                "Unit": "USD",
                                "CanTrade": True,
                                "PricePrecision": 2,
                                "AmountPrecision": 4,
                                "MiniOrder": 1,
                                "AssetType": "crypto",
                            },
                        },
                    }
                )
            ]
        )
        info = client.exchange_info()
        self.assertTrue(info.is_running)
        self.assertTrue(info.pair("BTC/USD").can_trade)
        self.assertEqual(info.pair("BTC/USD").amount_precision, 5)
        self.assertEqual(info.initial_wallet, {"USD": 50000})

    def test_error_body_without_a_success_field_is_still_an_error(self):
        client, _, _ = make_client([body({"ErrMsg": "pair not found"})])
        with self.assertRaises(ApiError):
            client.exchange_info()

    def test_balance_accepts_wallets_nested_under_data(self):
        client, _, _ = make_client(
            [
                server_time(),
                body(
                    {
                        "Success": True,
                        "Data": {
                            "USD": {"Free": 12.5, "Lock": 7.5},
                            "BTC": {"Free": 0.25, "Lock": 0.0},
                        },
                    }
                ),
            ]
        )
        balance = client.balance()
        self.assertEqual(balance.free("USD"), 12.5)
        self.assertEqual(balance.total("BTC"), 0.25)

    def test_balance_accepts_the_live_spot_wallet_envelope(self):
        """The live API wraps wallets in SpotWallet, not Data."""
        client, _, _ = make_client(
            [
                server_time(),
                body(
                    {
                        "Success": True,
                        "ErrMsg": "",
                        "SpotWallet": {
                            "USD": {
                                "Free": 50000,
                                "Lock": 0,
                                "PendingOrders": 0,
                                "ShortCollateral": 0,
                            }
                        },
                        "MarginWallet": {},
                    }
                ),
            ]
        )
        balance = client.balance()
        self.assertEqual(balance.free("USD"), 50000.0)
        self.assertEqual(balance.lock("USD"), 0.0)

    def test_ticker_accepts_a_list_of_rows(self):
        client, _, _ = make_client(
            [
                body(
                    {
                        "Success": True,
                        "Data": [
                            {"Pair": "BTC/USD", "LastPrice": 1.0},
                            {"Pair": "ETH/USD", "LastPrice": 2.0},
                        ],
                    }
                )
            ]
        )
        self.assertEqual(client.ticker("ETH/USD").last_price, 2.0)

    def test_ticker_with_a_non_positive_price_is_an_error(self):
        client, _, _ = make_client(
            [
                body(
                    {
                        "Success": True,
                        "Data": {"BTC/USD": {"LastPrice": 0}},
                    }
                )
            ]
        )
        with self.assertRaises(TransportError):
            client.ticker("BTC/USD")

    def test_balance_with_an_unrecognised_shape_is_an_error(self):
        client, _, _ = make_client(
            [
                server_time(),
                body({"Success": True, "SomethingElse": {"a": 1}}),
            ]
        )
        with self.assertRaises(TransportError):
            client.balance()

    def test_short_positions_empty_list(self):
        client, _, _ = make_client(
            [server_time(), body({"Success": True, "Positions": []})]
        )
        self.assertEqual(client.short_positions(), [])

    def test_short_positions_parses_entries(self):
        client, _, _ = make_client(
            [
                server_time(),
                body(
                    {
                        "Success": True,
                        "Positions": [
                            {
                                "Pair": "BTC/USD",
                                "ShortQty": 0.5,
                                "Collateral": 25000.0,
                                "UnrealizedPNL": -12.5,
                            }
                        ],
                    }
                ),
            ]
        )
        positions = client.short_positions()
        self.assertEqual(len(positions), 1)
        self.assertEqual(positions[0].short_qty, 0.5)
        self.assertEqual(positions[0].unrealized_pnl, -12.5)

    def test_non_json_response_is_a_transport_error(self):
        client, _, _ = make_client([server_time(), HttpResponse(200, "<html>")])
        with self.assertRaises(TransportError):
            client.balance()


if __name__ == "__main__":
    unittest.main()
