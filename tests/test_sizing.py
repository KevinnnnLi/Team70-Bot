import unittest
from decimal import Decimal

from roostoo import sizing


class FloorTests(unittest.TestCase):
    def test_floors_to_five_decimals(self):
        self.assertEqual(
            sizing.floor_to_precision("0.001239999", 5), Decimal("0.00123")
        )

    def test_floors_to_two_decimals_without_rounding_up(self):
        self.assertEqual(sizing.floor_to_precision("0.999999", 2), Decimal("0.99"))

    def test_zero_precision(self):
        self.assertEqual(sizing.floor_to_precision("9.99", 0), Decimal("9"))

    def test_never_rounds_up_even_when_closer(self):
        self.assertEqual(
            sizing.floor_to_precision("0.000019", 5), Decimal("0.00001")
        )

    def test_accepts_float_input_via_string_conversion(self):
        self.assertEqual(sizing.floor_to_precision(0.5, 2), Decimal("0.50"))


class FormatTests(unittest.TestCase):
    def test_formats_with_fixed_places(self):
        self.assertEqual(sizing.format_decimal(Decimal("9.99000"), 5), "9.99000")

    def test_never_uses_scientific_notation(self):
        self.assertEqual(sizing.format_decimal(Decimal("0.00001"), 5), "0.00001")


class MarketBuyTests(unittest.TestCase):
    def test_leaves_the_taker_fee_before_sizing(self):
        qty = sizing.market_buy_quantity(free_usd=1000.0, price=100.0, precision=5)
        self.assertEqual(qty, Decimal("9.99000"))

    def test_quantity_notional_stays_within_free_balance(self):
        qty = sizing.market_buy_quantity(free_usd=1000.0, price=100.0, precision=5)
        cost_with_fee = qty * Decimal("100") * Decimal("1.001")
        self.assertLessEqual(cost_with_fee, Decimal("1000"))

    def test_tiny_balance_floors_to_zero(self):
        qty = sizing.market_buy_quantity(free_usd=0.01, price=50000.0, precision=5)
        self.assertEqual(qty, Decimal("0.00000"))


class MarketSellTests(unittest.TestCase):
    def test_sells_the_whole_free_balance_floored(self):
        qty = sizing.market_sell_quantity(free_coin=0.123456789, precision=5)
        self.assertEqual(qty, Decimal("0.12345"))


class ShortCollateralTests(unittest.TestCase):
    def test_leaves_the_taker_fee_and_floors_to_cents(self):
        self.assertEqual(
            sizing.short_collateral(free_usd=1000.0), Decimal("999.00")
        )

    def test_collateral_plus_fee_fits_inside_free_balance(self):
        collateral = sizing.short_collateral(free_usd=1000.0)
        self.assertLessEqual(
            collateral * Decimal("1.001"), Decimal("1000")
        )


class TradeableTests(unittest.TestCase):
    def test_notional_must_be_strictly_greater_than_mini_order(self):
        self.assertFalse(sizing.meets_mini_order(Decimal("1.0"), 1.0))
        self.assertTrue(sizing.meets_mini_order(Decimal("1.00001"), 1.0))

    def test_dust_below_flat_threshold_is_rejected(self):
        self.assertTrue(sizing.is_dust(Decimal("74.99")))
        self.assertFalse(sizing.is_dust(Decimal("75.01")))

    def test_tradeable_requires_mini_order_and_non_dust(self):
        self.assertFalse(
            sizing.is_tradeable(
                quantity=Decimal("0.002"), price=1000.0, mini_order=1.0
            ),
            "2 USD notional is above MiniOrder but below the dust floor",
        )
        self.assertTrue(
            sizing.is_tradeable(
                quantity=Decimal("0.2"), price=1000.0, mini_order=1.0
            )
        )

    def test_tradeable_can_bypass_dust_for_unit_testing(self):
        self.assertTrue(
            sizing.is_tradeable(
                quantity=Decimal("0.002"),
                price=1000.0,
                mini_order=1.0,
                dust_usd=0.0,
            )
        )


if __name__ == "__main__":
    unittest.main()
