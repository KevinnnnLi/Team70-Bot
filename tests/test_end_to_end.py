"""End-to-end test over a real localhost socket, using the stdlib transport.

The fake exchange verifies the HMAC signature of every signed request, so a
signing regression fails this test rather than silently passing.
"""

import json
import tempfile
import threading
import unittest
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bot import main
from roostoo import signing

SECRET = "e2e-secret"
KEY = "e2e-key"
HOUR_MS = 3_600_000

SIGNED_PATHS = {
    "/v3/balance",
    "/v3/place_order",
    "/v6/short_positions",
    "/v6/short_open",
    "/v6/short_close",
}


class FakeExchange:
    def __init__(self):
        self.now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        self.usd_free = 100_000.0
        self.coins = {"BTC": 0.0, "ETH": 0.0}
        self.prices = {"BTC/USD": 50_000.0, "ETH/USD": 2_000.0}
        self.requests = []
        self.orders = []
        self.bad_signatures = 0

    def klines(self, symbol):
        last_close = 105.0 if symbol == "BTCUSDT" else 108.0
        last_hour = self.now_ms // HOUR_MS - 1
        rows = []
        for index in range(1000):
            open_ms = (last_hour - (999 - index)) * HOUR_MS
            close = last_close if index == 999 else 100.0
            rows.append(
                [
                    open_ms,
                    "100",
                    "100",
                    "100",
                    str(close),
                    "1",
                    open_ms + HOUR_MS - 1,
                    "0",
                    0,
                    "0",
                    "0",
                    "0",
                ]
            )
        return rows


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def _handle(self, method):
        parsed = urlparse(self.path)
        params = {key: values[0] for key, values in parse_qs(parsed.query).items()}
        length = int(self.headers.get("Content-Length") or 0)
        if length:
            raw = self.rfile.read(length).decode("utf-8")
            params.update(
                {key: values[0] for key, values in parse_qs(raw).items()}
            )

        exchange = self.server.exchange
        exchange.requests.append(
            (method, parsed.path, params, dict(self.headers))
        )

        if parsed.path in SIGNED_PATHS:
            if self.headers.get("MSG-SIGNATURE") != signing.sign(SECRET, params):
                exchange.bad_signatures += 1
                return self._json({"Success": False, "ErrMsg": "bad signature"})

        return self._route(parsed.path, params, exchange)

    def _route(self, path, params, exchange):
        if path == "/v3/serverTime":
            return self._json({"Success": True, "ServerTime": exchange.now_ms})
        if path == "/v3/exchangeInfo":
            return self._json(
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
                    "InitialWallet": {"USD": 100_000},
                }
            )
        if path == "/v3/ticker":
            pair = params["pair"]
            price = exchange.prices[pair]
            return self._json(
                {
                    "Success": True,
                    "Data": {
                        pair: {
                            "LastPrice": price,
                            "MaxBid": price - 10,
                            "MinAsk": price + 10,
                        }
                    },
                }
            )
        if path == "/v3/balance":
            return self._json(
                {
                    "Success": True,
                    "USD": {"Free": exchange.usd_free, "Lock": 0.0},
                    "BTC": {"Free": exchange.coins["BTC"], "Lock": 0.0},
                    "ETH": {"Free": exchange.coins["ETH"], "Lock": 0.0},
                }
            )
        if path == "/v6/short_positions":
            return self._json({"Success": True, "Positions": []})
        if path == "/v3/place_order":
            return self._place(params, exchange)
        if path == "/api/v3/klines":
            return self._json(exchange.klines(params["symbol"]))
        return self._json({"Success": False, "ErrMsg": f"no route for {path}"})

    def _place(self, params, exchange):
        pair = params["pair"]
        side = params["side"]
        quantity = float(params["quantity"])
        price = exchange.prices[pair]
        coin = pair.split("/")[0]
        if side == "BUY":
            exchange.usd_free -= quantity * price
            exchange.coins[coin] += quantity
        else:
            exchange.coins[coin] -= quantity
            exchange.usd_free += quantity * price
        exchange.orders.append((pair, side, params["quantity"]))
        return self._json({"Success": True})

    def _json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class EndToEndTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.exchange = FakeExchange()
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.exchange = cls.exchange
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.exchange.orders = []
        self.exchange.bad_signatures = 0
        self.exchange.usd_free = 100_000.0
        self.exchange.coins = {"BTC": 0.0, "ETH": 0.0}

    def tearDown(self):
        self._tmp.cleanup()

    def env(self):
        return {
            "ROOSTOO_API_KEY": KEY,
            "ROOSTOO_SECRET_KEY": SECRET,
            "ROOSTOO_BASE_URL": self.base_url,
            "BINANCE_BASE_URL": self.base_url,
            "ROOSTOO_STATE_PATH": str(self.dir / "state.json"),
            "ROOSTOO_LOG_DIR": str(self.dir / "logs"),
        }

    def test_preflight_runs_against_a_real_socket(self):
        self.assertEqual(main(["--check"], env=self.env()), 0)
        self.assertEqual(self.exchange.orders, [])
        self.assertEqual(self.exchange.bad_signatures, 0)

    def test_preflight_writes_logs_and_state_dir(self):
        main(["--check"], env=self.env())
        self.assertTrue((self.dir / "logs").exists())

    @unittest.skipIf(
        datetime.now(timezone.utc).hour == 0,
        "the bot deliberately waits for the 00:00 UTC candle to close",
    )
    def test_full_loop_buys_the_signal_winner_over_the_wire(self):
        self.assertEqual(main(["--once"], env=self.env()), 0)
        self.assertEqual(self.exchange.bad_signatures, 0)
        self.assertEqual(len(self.exchange.orders), 1)
        pair, side, quantity = self.exchange.orders[0]
        self.assertEqual((pair, side), ("ETH/USD", "BUY"))
        self.assertGreater(float(quantity), 0)
        self.assertTrue((self.dir / "logs" / "decisions.csv").exists())

    @unittest.skipIf(
        datetime.now(timezone.utc).hour == 0,
        "the bot deliberately waits for the 00:00 UTC candle to close",
    )
    def test_second_loop_does_not_double_trade_after_a_restart(self):
        main(["--once"], env=self.env())
        main(["--once"], env=self.env())
        self.assertEqual(len(self.exchange.orders), 1)


if __name__ == "__main__":
    unittest.main()
