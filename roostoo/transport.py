"""Thin HTTP layer, kept swappable so the client can be tested offline.

`RequestsTransport` is preferred when the `requests` package is installed.
`UrllibTransport` is a standard-library fallback so the bot still runs on an
instance that cannot reach PyPI.
"""

from __future__ import annotations

import importlib.util
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class TransportError(RuntimeError):
    """Network-level failure: connection, timeout, or a 5xx response."""


@dataclass
class HttpResponse:
    status_code: int
    text: str

    def json(self):
        return json.loads(self.text)


class RequestsTransport:
    def __init__(self, timeout: float = 30.0):
        try:
            import requests
        except ImportError as exc:  # pragma: no cover - depends on install
            raise TransportError(
                "the 'requests' package is missing; run "
                "'pip install -r requirements.txt'"
            ) from exc
        self._requests = requests
        self._timeout = timeout

    def get(self, url, params=None, headers=None) -> HttpResponse:
        return self._call(self._requests.get, url, params=params, headers=headers)

    def post(self, url, data=None, headers=None) -> HttpResponse:
        return self._call(self._requests.post, url, data=data, headers=headers)

    def close(self) -> None:
        pass

    def _call(self, method, url, **kwargs) -> HttpResponse:
        try:
            response = method(url, timeout=self._timeout, **kwargs)
        except self._requests.RequestException as exc:
            raise TransportError(f"{url}: {exc}") from exc
        return HttpResponse(status_code=response.status_code, text=response.text)


class UrllibTransport:
    """Standard-library HTTP transport with the same interface."""

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout

    def get(self, url, params=None, headers=None) -> HttpResponse:
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        return self._open(url, data=None, headers=headers)

    def post(self, url, data=None, headers=None) -> HttpResponse:
        payload = urllib.parse.urlencode(data or {}).encode("utf-8")
        return self._open(url, data=payload, headers=headers)

    def close(self) -> None:
        pass

    def _open(self, url, data, headers) -> HttpResponse:
        headers = dict(headers or {})
        headers.setdefault("User-Agent", "roostoo-momentum-bot/1.0")
        request = urllib.request.Request(
            url, data=data, headers=headers, method=None
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                body = response.read().decode("utf-8", "replace")
                return HttpResponse(status_code=response.status, text=body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            return HttpResponse(status_code=exc.code, text=body)
        except (urllib.error.URLError, OSError) as exc:
            raise TransportError(f"{url}: {exc}") from exc


def default_transport(timeout: float = 30.0):
    """Use `requests` when installed, otherwise fall back to `urllib`."""
    if importlib.util.find_spec("requests") is not None:
        return RequestsTransport(timeout)
    return UrllibTransport(timeout)
