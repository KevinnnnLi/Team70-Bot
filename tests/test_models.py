import unittest

from roostoo.models import Balance, ShortPosition, Ticker, Wallet


class BalanceTests(unittest.TestCase):
    def test_free_and_total_lookup(self):
        balance = Balance(
            wallets={
                "USD": Wallet(free=100.0, lock=25.0),
                "BTC": Wallet(free=0.5, lock=0.25),
            }
        )
        self.assertEqual(balance.free("USD"), 100.0)
        self.assertEqual(balance.lock("USD"), 25.0)
        self.assertEqual(balance.total("BTC"), 0.75)

    def test_missing_coin_reads_as_zero(self):
        balance = Balance(wallets={})
        self.assertEqual(balance.free("ETH"), 0.0)
        self.assertEqual(balance.total("ETH"), 0.0)


class ShortPositionTests(unittest.TestCase):
    def test_defaults_for_omitted_zero_fields(self):
        position = ShortPosition.from_api(
            {"Pair": "BTC/USD", "ShortQty": 0.5, "Collateral": 25000.0}
        )
        self.assertEqual(position.pair, "BTC/USD")
        self.assertEqual(position.short_qty, 0.5)
        self.assertEqual(position.collateral, 25000.0)
        self.assertEqual(position.unrealized_pnl, 0.0)
        self.assertEqual(position.position_value, 0.0)

    def test_parses_full_payload(self):
        position = ShortPosition.from_api(
            {
                "Pair": "BTC/USD",
                "ShortQty": 0.5,
                "Collateral": 25000.0,
                "UnrealizedPNL": -120.5,
                "PositionValue": 24879.5,
            }
        )
        self.assertEqual(position.unrealized_pnl, -120.5)
        self.assertEqual(position.position_value, 24879.5)


class TickerTests(unittest.TestCase):
    def test_from_api_reads_last_price_and_quotes(self):
        ticker = Ticker.from_api(
            "BTC/USD",
            {"LastPrice": 64000.0, "MaxBid": 63990.0, "MinAsk": 64010.0},
        )
        self.assertEqual(ticker.pair, "BTC/USD")
        self.assertEqual(ticker.last_price, 64000.0)
        self.assertEqual(ticker.max_bid, 63990.0)
        self.assertEqual(ticker.min_ask, 64010.0)


if __name__ == "__main__":
    unittest.main()
