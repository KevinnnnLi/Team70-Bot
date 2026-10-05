import unittest

from roostoo.equity import equity_usd
from roostoo.models import Balance, ShortPosition, Ticker, Wallet

TICKERS = {
    "BTC/USD": Ticker(pair="BTC/USD", last_price=50_000.0),
    "ETH/USD": Ticker(pair="ETH/USD", last_price=2_000.0),
}


def balance(usd_free=0.0, usd_lock=0.0, btc=0.0, eth=0.0):
    return Balance(
        wallets={
            "USD": Wallet(free=usd_free, lock=usd_lock),
            "BTC": Wallet(free=btc, lock=0.0),
            "ETH": Wallet(free=eth, lock=0.0),
        }
    )


class EquityTests(unittest.TestCase):
    def test_cash_only(self):
        self.assertEqual(
            equity_usd(balance(usd_free=100_000.0), TICKERS, []), 100_000.0
        )

    def test_free_plus_locked_usd(self):
        self.assertEqual(
            equity_usd(
                balance(usd_free=1_000.0, usd_lock=99_000.0), TICKERS, []
            ),
            100_000.0,
        )

    def test_coins_are_marked_at_the_roostoo_last_price(self):
        self.assertEqual(
            equity_usd(balance(usd_free=10_000.0, btc=1.0), TICKERS, []),
            60_000.0,
        )

    def test_ethereum_marks_to_ethereum_price(self):
        self.assertEqual(
            equity_usd(balance(usd_free=0.0, eth=10.0), TICKERS, []), 20_000.0
        )

    def test_locked_coins_are_counted(self):
        balance_with_lock = Balance(
            wallets={
                "USD": Wallet(free=0.0, lock=0.0),
                "BTC": Wallet(free=0.5, lock=0.5),
                "ETH": Wallet(free=0.0, lock=0.0),
            }
        )
        self.assertEqual(
            equity_usd(balance_with_lock, TICKERS, []), 50_000.0
        )

    def test_unrealized_short_pnl_is_added(self):
        short = ShortPosition(
            pair="BTC/USD",
            short_qty=1.0,
            collateral=25_000.0,
            unrealized_pnl=-500.0,
        )
        # Locked USD already holds the short collateral; do not add it twice.
        self.assertEqual(
            equity_usd(balance(usd_free=0.0, usd_lock=25_000.0), TICKERS, [short]),
            24_500.0,
        )

    def test_positive_short_pnl_is_added(self):
        short = ShortPosition(
            pair="BTC/USD",
            short_qty=1.0,
            collateral=25_000.0,
            unrealized_pnl=750.0,
        )
        self.assertEqual(
            equity_usd(balance(usd_lock=25_000.0), TICKERS, [short]), 25_750.0
        )

    def test_multiple_shorts_all_contribute(self):
        shorts = [
            ShortPosition(pair="BTC/USD", short_qty=1.0, unrealized_pnl=-100.0),
            ShortPosition(pair="ETH/USD", short_qty=1.0, unrealized_pnl=-50.0),
        ]
        self.assertEqual(
            equity_usd(balance(usd_free=10_000.0), TICKERS, shorts), 9_850.0
        )

    def test_missing_ticker_is_an_error(self):
        with self.assertRaises(KeyError):
            equity_usd(balance(btc=1.0), {}, [])


if __name__ == "__main__":
    unittest.main()
