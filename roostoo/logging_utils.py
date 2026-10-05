"""CSV trade logs and the human-readable bot log."""

from __future__ import annotations

import csv
import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

DECISION_COLUMNS: Sequence[str] = (
    "utc_time",
    "btc_ret_30d",
    "eth_ret_30d",
    "target",
    "equity",
    "peak_equity",
    "halted",
    "order_sent",
    "note",
)
TRADE_COLUMNS: Sequence[str] = (
    "utc_time",
    "action",
    "pair",
    "request",
    "success",
    "err_msg",
    "response",
)
EQUITY_COLUMNS: Sequence[str] = (
    "utc_time",
    "equity",
    "peak_equity",
    "btc_qty",
    "eth_qty",
    "usd_free",
    "short_btc_qty",
    "halted",
)


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return repr(value)
    return str(value).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


class CsvLog:
    """Append-only CSV with a header written on first use."""

    def __init__(self, path, columns: Sequence[str]):
        self.path = Path(path)
        self.columns = tuple(columns)

    def append(self, row: Mapping[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        is_new = not self.path.exists() or self.path.stat().st_size == 0
        with self.path.open("a", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            if is_new:
                writer.writerow(self.columns)
            writer.writerow([_cell(row.get(column)) for column in self.columns])


@dataclass
class LogBundle:
    decisions: CsvLog
    trades: CsvLog
    equity: CsvLog

    @classmethod
    def open(cls, log_dir) -> "LogBundle":
        log_dir = Path(log_dir)
        return cls(
            decisions=CsvLog(log_dir / "decisions.csv", DECISION_COLUMNS),
            trades=CsvLog(log_dir / "trades.csv", TRADE_COLUMNS),
            equity=CsvLog(log_dir / "equity.csv", EQUITY_COLUMNS),
        )


def build_logger(log_dir, name: str = "roostoo-bot") -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    if logger.handlers:
        return logger
    formatter = logging.Formatter(
        "%(asctime)sZ %(levelname)s %(message)s", datefmt="%Y-%m-%dT%H:%M:%S"
    )
    formatter.converter = time.gmtime  # the trailing Z must mean UTC
    file_handler = logging.FileHandler(log_dir / "bot.log", encoding="utf-8")
    file_handler.setFormatter(formatter)
    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)
    return logger


def close_logger(logger: logging.Logger) -> None:
    """Close and detach the handlers this process added."""
    for handler in list(logger.handlers):
        try:
            handler.flush()
        finally:
            handler.close()
            logger.removeHandler(handler)
