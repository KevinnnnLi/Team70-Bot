"""Persistent bot state, written atomically with a backup copy."""

from __future__ import annotations

import json
import logging
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Mapping, Optional


class StateError(RuntimeError):
    """The state file exists but cannot be parsed."""


@dataclass
class State:
    last_decision_date: Optional[str] = None
    decision_target: Optional[str] = None
    decision_btc_ret: Optional[float] = None
    decision_eth_ret: Optional[float] = None
    decision_complete: bool = False
    peak_equity: float = 0.0
    halted: bool = False

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "State":
        known = {field: data.get(field) for field in cls.__dataclass_fields__}
        return cls(**known)


class StateStore:
    def __init__(self, path, logger: Optional[logging.Logger] = None):
        self.path = Path(path)
        self.backup_path = Path(str(self.path) + ".bak")
        self._logger = logger or logging.getLogger("roostoo.state")

    def load(self) -> State:
        if not self.path.exists():
            return State()
        try:
            return State.from_dict(self._read(self.path))
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            self._logger.warning(
                "state file %s is unreadable (%s); falling back to backup",
                self.path,
                exc,
            )
        try:
            return State.from_dict(self._read(self.backup_path))
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            raise StateError(
                f"neither {self.path} nor {self.backup_path} is readable: {exc}"
            ) from exc

    def save(self, state: State) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state.to_dict(), indent=2, sort_keys=True)
        temp_path = Path(str(self.path) + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if self.path.exists():
            shutil.copyfile(self.path, self.backup_path)
        os.replace(temp_path, self.path)

    @staticmethod
    def _read(path: Path) -> dict:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise TypeError("state root is not an object")
        return data
