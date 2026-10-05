#!/usr/bin/env python3
"""Entry point for the Roostoo 30-day relative momentum bot.

Reads the strategy in STRATEGY_HANDOFF.md. Run with no arguments to trade,
``--check`` for a read-only preflight, or ``--dry-run`` to exercise the loop
without sending orders while testing a deployment.
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
from typing import Optional, Sequence

from roostoo import __version__, binance
from roostoo.client import RoostooClient, require_tradeable_pairs
from roostoo.config import ConfigError, load_config
from roostoo.engine import Engine
from roostoo.logging_utils import LogBundle, build_logger, close_logger
from roostoo.preflight import run_preflight
from roostoo.state import StateStore
from roostoo.transport import default_transport


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bot.py",
        description=(
            "Hold the stronger of BTC/ETH by 30-day Binance return, or short "
            "Bitcoin when both are negative. Decisions are made once per UTC day."
        ),
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="read-only preflight: credentials, API, signal. Sends no orders.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "run the loop but never send orders. Use only to test a "
            "deployment; never leave this on during live trading."
        ),
    )
    parser.add_argument(
        "--once", action="store_true", help="run a single loop, then exit"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    return parser.parse_args(argv)


def _install_signal_handlers(engine: Engine, logger: logging.Logger) -> None:
    def handler(signum, _frame):
        logger.warning(
            "received signal %s: finishing the current loop, then exiting",
            signum,
        )
        engine.stop_requested = True

    for name in ("SIGTERM", "SIGINT"):
        sig = getattr(signal, name, None)
        if sig is None:
            continue
        try:
            signal.signal(sig, handler)
        except (ValueError, OSError):  # not on the main thread
            pass


def main(argv=None, env=None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(env)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    logger = build_logger(config.log_dir)
    transport = default_transport(config.request_timeout)
    client = RoostooClient(config, transport=transport, logger=logger)
    store = StateStore(config.state_path, logger=logger)
    logs = LogBundle.open(config.log_dir)

    def signal_source(now_ms: int):
        return binance.fetch_signal(transport, now_ms, config.binance_base_url)

    try:
        if args.check:
            report = run_preflight(client, store, signal_source)
            print("Roostoo preflight (read-only, no orders)")
            print(report.text())
            print("RESULT:", "OK" if report.ok else "FAILED")
            return 0 if report.ok else 1

        exchange = client.exchange_info()
        require_tradeable_pairs(exchange)
        for pair in ("BTC/USD", "ETH/USD"):
            info = exchange.pair(pair)
            logger.info(
                "universe %s: amountPrecision=%s pricePrecision=%s MiniOrder=%s",
                pair,
                info.amount_precision,
                info.price_precision,
                info.mini_order,
            )

        engine = Engine(
            config=config,
            client=client,
            store=store,
            logs=logs,
            signal_source=signal_source,
            logger=logger,
            dry_run=args.dry_run,
        )
        _install_signal_handlers(engine, logger)

        if args.dry_run:
            logger.warning(
                "DRY RUN: the loop will decide and log but never send orders"
            )
        if args.once:
            engine.run_once()
        else:
            engine.run_forever()
        return 0
    except Exception as exc:  # noqa: BLE001 - top-level failure
        logger.exception("fatal: %s", exc)
        return 1
    finally:
        close_logger(logger)
        transport.close()


if __name__ == "__main__":
    raise SystemExit(main())
