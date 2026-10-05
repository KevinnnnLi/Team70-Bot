import unittest

from roostoo.models import Balance, ShortPosition, Ticker, Wallet
from roostoo.positions import live_position, plan_actions


def balance(usd=0.0, btc=0.0, eth=0.0, btc_lock=0.0, eth_lock=0.0):
    return Balance(
        wallets={
            "USD": Wallet(free=usd, lock=0.0),
            "BTC": Wallet(free=btc, lock=btc_lock),
            "ETH": Wallet(free=eth, lock=eth_lock),
        }
    )


TICKERS = {
    "BTC/USD": Ticker(pair="BTC/USD", last_price=50000.0),
    "ETH/USD": Ticker(pair="ETH/USD", last_price=2000.0),
}


class LivePositionTests(unittest.TestCase):
    def test_all_zero_is_flat(self):
        self.assertEqual(
            live_position(balance(usd=100000.0), TICKERS, []), "flat"
        )

    def test_bitcoin_holding_is_a_long(self):
        self.assertEqual(
            live_position(balance(btc=1.0), TICKERS, []), "long_btc"
        )

    def test_ethereum_holding_is_a_long(self):
        self.assertEqual(
            live_position(balance(eth=10.0), TICKERS, []), "long_eth"
        )

    def test_locked_coins_count_towards_the_position(self):
        self.assertEqual(
            live_position(
                balance(eth=0.0, eth_lock=10.0), TICKERS, []
            ),
            "long_eth",
        )

    def test_open_short_is_the_position(self):
        short = ShortPosition(
            pair="BTC/USD", short_qty=1.0, collateral=50000.0
        )
        self.assertEqual(
            live_position(balance(usd=1000.0), TICKERS, [short]), "short_btc"
        )

    def test_dust_only_holding_reads_as_flat(self):
        # 0.001 BTC at 50000 is 50 USD, below the 75 USD dust floor.
        self.assertEqual(
            live_position(balance(btc=0.001), TICKERS, []), "flat"
        )

    def test_both_coins_above_dust_is_mixed(self):
        self.assertEqual(
            live_position(balance(btc=1.0, eth=10.0), TICKERS, []), "mixed"
        )

    def test_short_wins_over_a_long_holding(self):
        short = ShortPosition(
            pair="BTC/USD", short_qty=1.0, collateral=50000.0
        )
        self.assertEqual(
            live_position(balance(eth=10.0), TICKERS, [short]), "short_btc"
        )


class PlanActionsTests(unittest.TestCase):
    """The action table from the strategy handoff, verbatim."""

    def test_transition_table(self):
        table = [
            ("flat", "long_btc", [("buy", "BTC")]),
            ("flat", "long_eth", [("buy", "ETH")]),
            ("flat", "short_btc", [("short_open", "BTC")]),
            ("long_eth", "long_btc", [("sell", "ETH"), ("buy", "BTC")]),
            ("long_btc", "long_eth", [("sell", "BTC"), ("buy", "ETH")]),
            ("long_eth", "short_btc", [("sell", "ETH"), ("short_open", "BTC")]),
            ("long_btc", "short_btc", [("sell", "BTC"), ("short_open", "BTC")]),
            ("short_btc", "long_eth", [("short_close", "BTC"), ("buy", "ETH")]),
            ("short_btc", "long_btc", [("short_close", "BTC"), ("buy", "BTC")]),
        ]
        for current, target, expected in table:
            with self.subTest(current=current, target=target):
                actions = plan_actions(current, target)
                self.assertEqual(
                    [(a.kind, a.coin) for a in actions], expected
                )

    def test_same_target_sends_no_order(self):
        for position in ["long_btc", "long_eth", "short_btc"]:
            with self.subTest(position=position):
                self.assertEqual(plan_actions(position, position), [])

    def test_mixed_holding_is_flattened_before_entering(self):
        actions = plan_actions("mixed", "long_eth")
        self.assertEqual(
            [(a.kind, a.coin) for a in actions],
            [("sell", "BTC"), ("sell", "ETH"), ("buy", "ETH")],
        )

    def test_mixed_to_short_flattens_first(self):
        actions = plan_actions("mixed", "short_btc")
        self.assertEqual(
            [(a.kind, a.coin) for a in actions],
            [("sell", "BTC"), ("sell", "ETH"), ("short_open", "BTC")],
        )

    def test_unknown_target_is_rejected(self):
        with self.assertRaises(ValueError):
            plan_actions("flat", "long_dogecoin")


if __name__ == "__main__":
    unittest.main()
