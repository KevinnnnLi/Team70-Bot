import tempfile
import unittest
from pathlib import Path

from roostoo.models import ExchangeInfo, PairInfo, Signal
from roostoo.preflight import run_preflight
from roostoo.state import State, StateStore

from .fakes import FakeClient

PAIRS = {
    "BTC/USD": PairInfo("BTC/USD", True, 5, 2, 1.0),
    "ETH/USD": PairInfo("ETH/USD", True, 4, 2, 1.0),
}


def signal(btc, eth):
    return Signal(btc_ret_30d=btc, eth_ret_30d=eth, candle_open_time_ms=0)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = StateStore(Path(self._tmp.name) / "state.json")

    def tearDown(self):
        self._tmp.cleanup()

    def test_healthy_account_reports_ok(self):
        report = run_preflight(
            FakeClient(), self.store, lambda now_ms: signal(0.049, 0.068)
        )
        self.assertTrue(report.ok)
        text = report.text()
        self.assertIn("CanTrade=True", text)
        self.assertIn("long_eth", text)
        self.assertIn("equity=100000.00", text)

    def test_untradeable_pair_fails_the_check(self):
        client = FakeClient()
        client.exchange_info = lambda: ExchangeInfo(
            pairs={
                **PAIRS,
                "ETH/USD": PairInfo("ETH/USD", False, 4, 2, 1.0),
            }
        )
        report = run_preflight(client, self.store, lambda now_ms: signal(0, 0))
        self.assertFalse(report.ok)
        self.assertIn("CanTrade=false", report.text())

    def test_signal_failure_does_not_raise(self):
        def boom(now_ms):
            raise RuntimeError("binance unreachable")

        report = run_preflight(FakeClient(), self.store, boom)
        self.assertFalse(report.ok)
        self.assertIn("binance unreachable", report.text())

    def test_exchange_not_running_fails_the_check(self):
        client = FakeClient()
        client.exchange_info = lambda: ExchangeInfo(pairs=PAIRS, is_running=False)
        report = run_preflight(client, self.store, lambda now_ms: signal(0, 0))
        self.assertFalse(report.ok)
        self.assertIn("IsRunning=false", report.text())

    def test_reports_persisted_state(self):
        self.store.save(State(halted=True, peak_equity=123.0))
        report = run_preflight(
            FakeClient(), self.store, lambda now_ms: signal(0.01, 0.02)
        )
        self.assertIn("halted=True", report.text())

    def test_preflight_sends_no_orders(self):
        client = FakeClient()
        run_preflight(client, self.store, lambda now_ms: signal(0.049, 0.068))
        self.assertEqual(client.orders, [])


if __name__ == "__main__":
    unittest.main()
