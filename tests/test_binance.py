import unittest

from roostoo import binance

HOUR_MS = 3_600_000


def kline(open_time_ms, close, close_time_ms=None):
    if close_time_ms is None:
        close_time_ms = open_time_ms + HOUR_MS - 1
    return [
        open_time_ms,
        "1",
        "1",
        "1",
        str(close),
        "1",
        close_time_ms,
        "0",
        0,
        "0",
        "0",
        "0",
    ]


class ParseTests(unittest.TestCase):
    def test_parses_open_close_and_close_time(self):
        candle = binance.parse_kline(kline(1000, 42.5))
        self.assertEqual(candle.open_time_ms, 1000)
        self.assertEqual(candle.close, 42.5)
        self.assertEqual(candle.close_time_ms, 1000 + HOUR_MS - 1)


class CompletedClosesTests(unittest.TestCase):
    def test_drops_the_still_forming_candle(self):
        now = 9 * HOUR_MS + 30 * 60 * 1000  # 09:30, mid-way through hour 9
        rows = [kline(8 * HOUR_MS, 10.0), kline(9 * HOUR_MS, 11.0)]
        # The 9th hour candle opened in the current hour, so it is still forming.
        closes = binance.completed_closes(rows, now_ms=now, minimum=1)
        self.assertEqual(closes, [10.0])

    def test_keeps_a_candle_that_closed_exactly_now(self):
        now = 10 * HOUR_MS
        rows = [kline(9 * HOUR_MS, 11.0, close_time_ms=now - 1)]
        closes = binance.completed_closes(rows, now_ms=now, minimum=1)
        self.assertEqual(closes, [11.0])

    def test_raises_when_history_is_too_short(self):
        rows = [kline(0, 10.0)]
        with self.assertRaises(binance.SignalError):
            binance.completed_closes(rows, now_ms=10 * HOUR_MS, minimum=721)


class ReturnTests(unittest.TestCase):
    def test_computes_thirty_day_return(self):
        closes = [100.0] * 720 + [110.0]
        self.assertAlmostEqual(binance.return_30d(closes), 0.10)

    def test_uses_exactly_the_last_721_closes(self):
        closes = [1.0] * 100 + [100.0] * 720 + [150.0]
        self.assertAlmostEqual(binance.return_30d(closes), 0.5)

    def test_rejects_short_history(self):
        with self.assertRaises(binance.SignalError):
            binance.return_30d([100.0] * 720)

    def test_zero_start_price_is_a_signal_error(self):
        with self.assertRaises(binance.SignalError):
            binance.return_30d([0.0] + [1.0] * 720)

    def test_exact_lookback_constant(self):
        self.assertEqual(binance.LOOKBACK_HOURS, 720)
        self.assertEqual(binance.MIN_COMPLETED_CLOSES, 721)


class DecisionReadyTests(unittest.TestCase):
    DAY = 86_400_000

    def test_day_start_is_midnight_utc(self):
        self.assertEqual(binance.utc_day_start_ms(5 * self.DAY + 12_345), 5 * self.DAY)

    def test_yesterdays_last_candle_is_not_enough(self):
        now = 5 * self.DAY + 30 * 60 * 1000  # 00:30 UTC
        candle_open = 4 * self.DAY + 23 * 3_600_000  # 23:00 the day before
        self.assertFalse(binance.decision_ready(candle_open, now))

    def test_todays_midnight_candle_is_enough(self):
        now = 5 * self.DAY + 3_600_000  # 01:00 UTC
        self.assertTrue(binance.decision_ready(5 * self.DAY, now))

    def test_a_later_candle_is_still_ready(self):
        now = 5 * self.DAY + 9 * 3_600_000
        self.assertTrue(binance.decision_ready(5 * self.DAY + 4 * 3_600_000, now))


if __name__ == "__main__":
    unittest.main()
