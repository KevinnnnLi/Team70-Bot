import unittest

from roostoo.strategy import target


class TargetTests(unittest.TestCase):
    def test_both_positive_picks_the_larger_return(self):
        self.assertEqual(target(0.05, 0.08), "long_eth")
        self.assertEqual(target(0.08, 0.05), "long_btc")

    def test_equal_positive_returns_hold_bitcoin(self):
        self.assertEqual(target(0.05, 0.05), "long_btc")

    def test_only_bitcoin_positive_longs_bitcoin(self):
        self.assertEqual(target(0.001, -0.20), "long_btc")

    def test_only_ethereum_positive_longs_ethereum(self):
        self.assertEqual(target(-0.20, 0.001), "long_eth")

    def test_both_negative_shorts_bitcoin(self):
        self.assertEqual(target(-0.01, -0.02), "short_btc")
        self.assertEqual(target(0.0, 0.0), "short_btc")

    def test_flat_returns_are_not_positive(self):
        # Zero is treated as "not above zero", so both-zero shorts.
        self.assertEqual(target(0.0, -0.5), "short_btc")
        self.assertEqual(target(0.0, 0.5), "long_eth")

    def test_tiny_edge_still_counts(self):
        self.assertEqual(target(0.0, 0.0000001), "long_eth")


if __name__ == "__main__":
    unittest.main()
