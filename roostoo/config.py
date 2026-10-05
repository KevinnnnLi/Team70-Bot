"""Environment-driven configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

DEFAULT_BASE_URL = "https://mock-api.roostoo.com"
DEFAULT_BINANCE_BASE_URL = "https://api.binance.com"


class ConfigError(RuntimeError):
    """Raised when required environment variables are missing."""


@dataclass(frozen=True)
class Config:
    api_key: str
    secret_key: str
    base_url: str = DEFAULT_BASE_URL
    binance_base_url: str = DEFAULT_BINANCE_BASE_URL
    state_path: Path = Path("state.json")
    log_dir: Path = Path("logs")
    loop_seconds: int = 300
    max_drawdown: float = 0.20
    taker_fee: float = 0.001
    dust_usd: float = 75.0
    time_sync_seconds: int = 300
    request_timeout: float = 30.0


def load_config(env: Optional[Mapping[str, str]] = None) -> Config:
    env = os.environ if env is None else env
    api_key = (env.get("ROOSTOO_API_KEY") or "").strip()
    secret_key = (env.get("ROOSTOO_SECRET_KEY") or "").strip()

    missing = [
        name
        for name, value in (
            ("ROOSTOO_API_KEY", api_key),
            ("ROOSTOO_SECRET_KEY", secret_key),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            "refusing to start: set " + " and ".join(missing) + " first"
        )

    base_url = (env.get("ROOSTOO_BASE_URL") or DEFAULT_BASE_URL).strip()
    binance_base_url = (
        env.get("BINANCE_BASE_URL") or DEFAULT_BINANCE_BASE_URL
    ).strip()
    return Config(
        api_key=api_key,
        secret_key=secret_key,
        base_url=base_url.rstrip("/"),
        binance_base_url=binance_base_url.rstrip("/"),
        state_path=Path(env.get("ROOSTOO_STATE_PATH") or "state.json"),
        log_dir=Path(env.get("ROOSTOO_LOG_DIR") or "logs"),
    )
