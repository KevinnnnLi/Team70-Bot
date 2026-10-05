import csv
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from roostoo.binance import utc_day_start_ms
from roostoo.client import TransportError
from roostoo.config import Config
from roostoo.engine import Engine
from roostoo.logging_utils import LogBundle
from roostoo.models import Signal, ShortPosition
from roostoo.state import State, StateStore

from .fakes import FakeClient

NOW = datetime(2026, 10, 5, 1, 0, tzinfo=timezone.utc)
TODAY = "2026-10-05"
NOW_MS = int(NOW.timestamp() * 1000)
DAY_START_MS = utc_day_start_ms(NOW_MS)


def signal(btc_ret, eth_ret, candle_open_ms=DAY_START_MS):
    return Signal(
        btc_ret_30d=btc_ret,
        eth_ret_30d=eth_ret,
        candle_open_time_ms=candle_open_ms,
    )


class EngineTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.store = StateStore(self.dir / "state.json")
        self.logs = LogBundle.open(self.dir / "logs")
        self.signal_calls = []

    def tearDown(self):
        self._tmp.cleanup()

    def build(self, client, signal_value=None, clock=NOW, dry_run=False):
        def source(now_ms):
            self.signal_calls.append(now_ms)
            if signal_value is None:
                raise AssertionError("signal source should not have been called")
            return signal_value

        config = Config(
            api_key="key",
            secret_key="secret",
            base_url="https://mock-api.roostoo.com",
            state_path=self.dir / "state.json",
            log_dir=self.dir / "logs",
        )
        return Engine(
            config=config,
            client=client,
            store=self.store,
            logs=self.logs,
            signal_source=source,
            clock=lambda: clock,
            dry_run=dry_run,
        )

    def rows(self, name):
        path = self.dir / "logs" / name
        if not path.exists():
            return []
        with path.open(newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))


class DecisionTests(EngineTestCase):
    def test_rebalance_sells_the_old_coin_before_buying_the_new_one(self):
        client = FakeClient(usd_free=0.0, eth=18.0)  # 36,000 USD of ETH
        engine = self.build(client, signal(0.10, 0.01))  # BTC now leads
        engine.run_once()

        self.assertEqual(
            [(order[0], order[1]) for order in client.orders],
            [("ETH/USD", "SELL"), ("BTC/USD", "BUY")],
        )
        self.assertEqual(client.coins["ETH"], 0.0)
        self.assertGreater(client.coins["BTC"], 0.0)

    def test_flat_account_buys_the_signal_winner(self):
        client = FakeClient(usd_free=100_000.0)
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()

        self.assertEqual(len(client.orders), 1)
        pair, side, quantity = client.orders[0]
        self.assertEqual((pair, side), ("ETH/USD", "BUY"))
        self.assertGreater(float(quantity), 0)

        state = self.store.load()
        self.assertEqual(state.last_decision_date, TODAY)
        self.assertEqual(state.decision_target, "long_eth")
        self.assertTrue(state.decision_complete)
        self.assertAlmostEqual(state.decision_btc_ret, 0.049)
        self.assertAlmostEqual(state.decision_eth_ret, 0.068)

    def test_decision_is_written_to_decisions_csv(self):
        engine = self.build(FakeClient(), signal(0.049, 0.068))
        engine.run_once()
        rows = self.rows("decisions.csv")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["target"], "long_eth")
        self.assertEqual(rows[0]["order_sent"], "True")
        self.assertEqual(rows[0]["halted"], "False")
        self.assertAlmostEqual(float(rows[0]["equity"]), 100_000.0)

    def test_equity_is_logged_every_loop(self):
        engine = self.build(FakeClient(), signal(0.049, 0.068))
        engine.run_once()
        rows = self.rows("equity.csv")
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(float(rows[0]["equity"]), 100_000.0)
        self.assertAlmostEqual(float(rows[0]["peak_equity"]), 100_000.0)

    def test_second_loop_on_the_same_day_sends_no_second_order(self):
        client = FakeClient()
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()
        engine.run_once()
        self.assertEqual(len(client.orders), 1)
        self.assertEqual(len(self.signal_calls), 1)

    def test_restarted_process_does_not_reorder_the_same_day(self):
        client = FakeClient()
        self.build(client, signal(0.049, 0.068)).run_once()
        restarted = self.build(client, signal(0.049, 0.068))
        restarted.run_once()
        self.assertEqual(len(client.orders), 1)
        self.assertEqual(len(self.signal_calls), 1)

    def test_same_target_as_current_position_sends_no_order(self):
        client = FakeClient(usd_free=0.0, eth=10.0)
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()
        self.assertEqual(client.orders, [])
        self.assertTrue(self.store.load().decision_complete)
        self.assertIn("no order", self.rows("decisions.csv")[0]["note"])

    def test_midnight_candle_not_closed_yet_defers_the_decision(self):
        client = FakeClient()
        engine = self.build(
            client, signal(0.049, 0.068, candle_open_ms=DAY_START_MS - 3_600_000)
        )
        engine.run_once()
        self.assertEqual(client.orders, [])
        self.assertIsNone(self.store.load().last_decision_date)

    def test_dry_run_never_sends_orders(self):
        client = FakeClient()
        engine = self.build(client, signal(0.049, 0.068), dry_run=True)
        engine.run_once()
        self.assertEqual(client.orders, [])
        self.assertFalse(self.store.load().decision_complete)


class RetryTests(EngineTestCase):
    def test_binance_transport_failure_waits_instead_of_crashing(self):
        def boom(now_ms):
            raise TransportError("binance unreachable")

        client = FakeClient()
        engine = self.build(client)
        engine._signal_source = boom
        engine.run_once()  # must not raise

        self.assertEqual(client.orders, [])
        self.assertIsNone(self.store.load().last_decision_date)

    def test_failed_order_keeps_the_decision_open_for_a_retry(self):
        client = FakeClient(fail_orders=1)
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()

        state = self.store.load()
        self.assertEqual(state.decision_target, "long_eth")
        self.assertFalse(state.decision_complete)
        self.assertEqual(client.orders, [])

    def test_retry_uses_the_stored_target_and_does_not_recompute(self):
        client = FakeClient(fail_orders=1)
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()

        # A different signal arrives, but the same day's decision must stand.
        engine._signal_source = lambda now_ms: signal(-0.05, -0.06)
        engine.run_once()

        self.assertEqual(len(client.orders), 1)
        self.assertEqual(client.orders[0][0], "ETH/USD")
        self.assertEqual(client.orders[0][1], "BUY")
        self.assertTrue(self.store.load().decision_complete)

    def test_failed_order_is_recorded_in_trades_csv(self):
        client = FakeClient(fail_orders=1)
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()
        rows = self.rows("trades.csv")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["success"], "False")
        self.assertIn("insufficient balance", rows[0]["err_msg"])


class ShortTests(EngineTestCase):
    def test_both_returns_negative_opens_a_bitcoin_short(self):
        client = FakeClient(usd_free=100_000.0)
        engine = self.build(client, signal(-0.01, -0.02))
        engine.run_once()
        self.assertEqual(len(client.orders), 1)
        self.assertEqual(client.orders[0][1], "SHORT_OPEN")
        state = self.store.load()
        self.assertEqual(state.decision_target, "short_btc")
        self.assertTrue(state.decision_complete)

    def test_short_open_without_an_open_status_is_not_trusted(self):
        """Success: true but no Status: OPEN means unconfirmed, so retry."""
        client = FakeClient()
        client.short_open = lambda pair, collateral: {"Success": True}
        engine = self.build(client, signal(-0.01, -0.02))
        engine.run_once()
        self.assertFalse(self.store.load().decision_complete)

    def test_unconfirmed_short_is_confirmed_by_position_not_stacked(self):
        client = FakeClient()
        client.short_open = lambda pair, collateral: {"Success": True}
        engine = self.build(client, signal(-0.01, -0.02))
        engine.run_once()
        self.assertFalse(self.store.load().decision_complete)

        # It did fill after all. The next loop must see the position and stop,
        # not open a second short.
        client.shorts = [
            ShortPosition(pair="BTC/USD", short_qty=1.0, collateral=50_000.0)
        ]
        client.orders = []
        engine.run_once()

        self.assertTrue(self.store.load().decision_complete)
        self.assertEqual(client.orders, [])

    def test_pending_short_is_cancelled_and_retried(self):
        client = FakeClient()
        cancelled = []
        client.short_open = lambda pair, collateral: {
            "Success": True,
            "Status": "PENDING",
            "ID": 999,
        }
        client.cancel_order = lambda order_id: (
            cancelled.append(order_id) or {"Success": True}
        )
        engine = self.build(client, signal(-0.01, -0.02))
        engine.run_once()

        self.assertEqual(cancelled, [999])
        self.assertFalse(self.store.load().decision_complete)

    def test_short_not_allowed_is_logged_and_not_retried(self):
        client = FakeClient(short_not_allowed=True)
        engine = self.build(client, signal(-0.01, -0.02))
        engine.run_once()

        state = self.store.load()
        self.assertTrue(state.decision_complete)
        attempts_after_first = len(client.attempts)
        self.assertEqual(attempts_after_first, 1)

        engine.run_once()
        self.assertEqual(len(client.attempts), attempts_after_first)
        rows = self.rows("trades.csv")
        self.assertIn("does not allow short", rows[-1]["err_msg"])

    def test_short_to_long_closes_first_then_buys(self):
        client = FakeClient(
            usd_free=0.0,
            usd_lock=50_000.0,
            shorts=[ShortPosition(pair="BTC/USD", short_qty=1.0, collateral=50_000.0)],
        )
        engine = self.build(client, signal(0.05, 0.01))
        engine.run_once()
        kinds = [order[1] for order in client.orders]
        self.assertEqual(kinds, ["SHORT_CLOSE", "BUY"])


class HaltTests(EngineTestCase):
    def test_zero_equity_reading_never_trips_the_halt(self):
        """A bad read must not permanently halt the account."""
        client = FakeClient(usd_free=0.0)
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()

        state = self.store.load()
        self.assertFalse(state.halted, "0 equity is bad data, not a 100% loss")
        self.assertEqual(client.orders, [])

    def test_zero_equity_reading_does_not_trade(self):
        client = FakeClient(usd_free=0.0)
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()
        self.assertEqual(client.orders, [])
        self.assertIsNone(self.store.load().last_decision_date)

    def test_twenty_percent_drawdown_flattens_and_halts(self):
        client = FakeClient(usd_free=0.0, eth=39.5)  # 79,000 USD at 2,000
        self.store.save(
            State(
                last_decision_date=TODAY,
                decision_target="long_eth",
                decision_complete=True,
                peak_equity=100_000.0,
            )
        )
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()

        state = self.store.load()
        self.assertTrue(state.halted)
        self.assertEqual(client.orders, [("ETH/USD", "SELL", "39.5000")])
        self.assertIn("drawdown", self.rows("decisions.csv")[-1]["note"])

    def test_exactly_eighty_percent_halts(self):
        client = FakeClient(usd_free=80_000.0)
        self.store.save(State(peak_equity=100_000.0))
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()
        self.assertTrue(self.store.load().halted)

    def test_above_eighty_percent_does_not_halt(self):
        client = FakeClient(usd_free=80_001.0)
        self.store.save(State(peak_equity=100_000.0))
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()
        self.assertFalse(self.store.load().halted)

    def test_halted_account_never_opens_a_new_position(self):
        client = FakeClient(usd_free=100_000.0)
        self.store.save(State(halted=True, peak_equity=100_000.0))
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()
        engine.run_once()
        self.assertEqual(client.orders, [])
        self.assertEqual(self.signal_calls, [])

    def test_halt_survives_a_restart(self):
        self.store.save(State(halted=True, peak_equity=100_000.0))
        client = FakeClient(usd_free=100_000.0)
        self.build(client, signal(0.049, 0.068)).run_once()
        self.assertTrue(self.store.load().halted)
        self.assertEqual(client.orders, [])


class PeakTests(EngineTestCase):
    def test_peak_equity_ratchets_up_and_is_persisted(self):
        client = FakeClient(usd_free=110_000.0)
        self.store.save(State(peak_equity=100_000.0))
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()
        self.assertAlmostEqual(self.store.load().peak_equity, 110_000.0)

    def test_peak_equity_is_not_lowered(self):
        client = FakeClient(usd_free=95_000.0)
        self.store.save(State(peak_equity=100_000.0))
        engine = self.build(client, signal(0.049, 0.068))
        engine.run_once()
        self.assertAlmostEqual(self.store.load().peak_equity, 100_000.0)


if __name__ == "__main__":
    unittest.main()
