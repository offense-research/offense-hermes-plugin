"""Shared test doubles."""

from __future__ import annotations

import json

from offense_plugin.offense_client import OffenseClient


def response(status: int, payload: dict) -> tuple[int, dict, bytes]:
    return status, {}, json.dumps(payload).encode("utf-8")


class FakeTransport:
    """Deterministic transport recording every call."""

    def __init__(self, *responses: tuple[int, dict]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, method, url, headers, data, timeout):
        self.calls.append(
            {
                "method": method,
                "url": url,
                "headers": headers,
                "body": json.loads(data.decode()) if data else None,
                "timeout": timeout,
            }
        )
        if not self.responses:
            raise AssertionError(f"unexpected request: {method} {url}")
        return self.responses.pop(0)


def make_client(transport: FakeTransport, **overrides) -> OffenseClient:
    return OffenseClient(
        base_url="https://api.example.test/",
        api_key="offense_sk_test",
        transport=transport,
        sleep=lambda _seconds: None,
        **overrides,
    )
