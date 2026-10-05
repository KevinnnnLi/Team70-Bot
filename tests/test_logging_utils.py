import csv
import tempfile
import time
import unittest
from pathlib import Path

from roostoo.logging_utils import (
    DECISION_COLUMNS,
    EQUITY_COLUMNS,
    TRADE_COLUMNS,
    CsvLog,
    build_logger,
)


class CsvLogTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def read(self, name):
        with (self.dir / name).open(newline="", encoding="utf-8") as handle:
            return list(csv.reader(handle))

    def test_writes_header_then_rows(self):
        log = CsvLog(self.dir / "decisions.csv", DECISION_COLUMNS)
        log.append({"utc_time": "2026-10-04T01:00:00Z", "target": "long_eth"})
        log.append({"utc_time": "2026-10-05T01:00:00Z", "target": "long_btc"})
        rows = self.read("decisions.csv")
        self.assertEqual(rows[0], list(DECISION_COLUMNS))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[1][0], "2026-10-04T01:00:00Z")

    def test_missing_fields_become_empty_cells(self):
        log = CsvLog(self.dir / "equity.csv", EQUITY_COLUMNS)
        log.append({"utc_time": "now", "equity": 100.0})
        rows = self.read("equity.csv")
        self.assertEqual(len(rows[1]), len(EQUITY_COLUMNS))
        self.assertEqual(rows[1][EQUITY_COLUMNS.index("btc_qty")], "")

    def test_commas_and_newlines_are_safe(self):
        log = CsvLog(self.dir / "trades.csv", TRADE_COLUMNS)
        log.append(
            {
                "utc_time": "now",
                "note": "a,b",
                "response": '{"a": 1}\n{"b": 2}',
            }
        )
        rows = self.read("trades.csv")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1][TRADE_COLUMNS.index("response")], '{"a": 1} {"b": 2}')

    def test_header_is_not_duplicated_by_a_second_writer(self):
        CsvLog(self.dir / "equity.csv", EQUITY_COLUMNS).append({"utc_time": "a"})
        CsvLog(self.dir / "equity.csv", EQUITY_COLUMNS).append({"utc_time": "b"})
        rows = self.read("equity.csv")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], list(EQUITY_COLUMNS))

    def test_column_orders_match_the_spec(self):
        self.assertEqual(
            list(DECISION_COLUMNS),
            [
                "utc_time",
                "btc_ret_30d",
                "eth_ret_30d",
                "target",
                "equity",
                "peak_equity",
                "halted",
                "order_sent",
                "note",
            ],
        )
        self.assertEqual(
            list(TRADE_COLUMNS),
            ["utc_time", "action", "pair", "request", "success", "err_msg", "response"],
        )
        self.assertEqual(
            list(EQUITY_COLUMNS),
            [
                "utc_time",
                "equity",
                "peak_equity",
                "btc_qty",
                "eth_qty",
                "usd_free",
                "short_btc_qty",
                "halted",
            ],
        )


class LoggerTests(unittest.TestCase):
    def test_build_logger_writes_a_file_under_log_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            log_dir = Path(tmp) / "logs"
            logger = build_logger(log_dir, name="test-bot")
            logger.info("hello")
            for handler in logger.handlers:
                handler.flush()
            self.assertTrue((log_dir / "bot.log").exists())
            self.assertIn("hello", (log_dir / "bot.log").read_text(encoding="utf-8"))
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)

    def test_log_timestamps_are_utc(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = build_logger(Path(tmp) / "logs", name="utc-test-bot")
            formatter = logger.handlers[0].formatter
            self.assertIs(formatter.converter, time.gmtime)
            for handler in list(logger.handlers):
                handler.close()
                logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()
