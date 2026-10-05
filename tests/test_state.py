import json
import tempfile
import unittest
from pathlib import Path

from roostoo.state import State, StateError, StateStore


class StateStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.path = Path(self._tmp.name) / "state.json"
        self.store = StateStore(self.path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_missing_file_yields_defaults(self):
        state = self.store.load()
        self.assertIsNone(state.last_decision_date)
        self.assertEqual(state.peak_equity, 0.0)
        self.assertFalse(state.halted)
        self.assertFalse(state.decision_complete)

    def test_round_trip(self):
        state = State(
            last_decision_date="2026-10-04",
            decision_target="long_eth",
            decision_btc_ret=0.049,
            decision_eth_ret=0.068,
            decision_complete=True,
            peak_equity=104_321.5,
            halted=False,
        )
        self.store.save(state)
        loaded = self.store.load()
        self.assertEqual(loaded.last_decision_date, "2026-10-04")
        self.assertEqual(loaded.decision_target, "long_eth")
        self.assertAlmostEqual(loaded.decision_btc_ret, 0.049)
        self.assertAlmostEqual(loaded.decision_eth_ret, 0.068)
        self.assertTrue(loaded.decision_complete)
        self.assertAlmostEqual(loaded.peak_equity, 104_321.5)
        self.assertFalse(loaded.halted)

    def test_save_leaves_a_backup_of_the_previous_file(self):
        self.store.save(State(peak_equity=100_000.0))
        self.store.save(State(peak_equity=101_000.0))
        backup = StateStore(Path(str(self.path) + ".bak")).load()
        self.assertAlmostEqual(backup.peak_equity, 100_000.0)
        self.assertAlmostEqual(self.store.load().peak_equity, 101_000.0)

    def test_corrupt_primary_falls_back_to_backup(self):
        self.store.save(State(peak_equity=100_000.0))
        self.store.save(State(peak_equity=101_000.0))
        self.path.write_text("{not json", encoding="utf-8")
        state = self.store.load()
        self.assertAlmostEqual(state.peak_equity, 100_000.0)

    def test_corrupt_primary_and_backup_raises(self):
        self.path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(StateError):
            self.store.load()

    def test_unknown_keys_are_ignored_and_missing_keys_default(self):
        self.path.write_text(
            json.dumps({"peak_equity": 5.0, "something_else": 1}), encoding="utf-8"
        )
        state = self.store.load()
        self.assertAlmostEqual(state.peak_equity, 5.0)
        self.assertIsNone(state.last_decision_date)

    def test_written_file_is_valid_json(self):
        self.store.save(State(halted=True))
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertTrue(payload["halted"])


if __name__ == "__main__":
    unittest.main()
