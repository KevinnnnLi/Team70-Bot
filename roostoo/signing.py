"""Roostoo request signing.

The server signs only the parameters listed by the endpoint, plus
``timestamp``. Extra keys break the signature, so callers must build the
exact parameter set for each endpoint.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Mapping

_TIMESTAMP_ERROR_MARKERS = (
    "timestamp",
    "request time",
    "server time",
)


def signing_payload(params: Mapping[str, object]) -> str:
    """Stringify values, sort keys, and join as ``k=v`` pairs with ``&``."""
    stringified = {key: str(value) for key, value in params.items()}
    return "&".join(f"{key}={stringified[key]}" for key in sorted(stringified))


def sign(secret: str, params: Mapping[str, object]) -> str:
    """Lowercase hex HMAC-SHA256 of :func:`signing_payload`."""
    return hmac.new(
        secret.encode(), signing_payload(params).encode(), hashlib.sha256
    ).hexdigest()


def timestamp_offset(server_time_ms: int, local_time_ms: int) -> int:
    """Milliseconds to add to local time so it matches the server."""
    return int(server_time_ms) - int(local_time_ms)


def signed_timestamp(local_time_ms: int, offset_ms: int) -> int:
    return int(local_time_ms) + int(offset_ms)


def is_timestamp_error(message: str) -> bool:
    lowered = (message or "").lower()
    return any(marker in lowered for marker in _TIMESTAMP_ERROR_MARKERS)
