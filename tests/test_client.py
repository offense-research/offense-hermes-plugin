"""Client tests: HTTP shape, credential resolution, polling."""

from __future__ import annotations

import pytest
from offense_plugin.offense_client import (
    API_KEY_ENV,
    OffenseApiError,
    OffenseAuthError,
    OffenseClient,
    OffenseConnectionError,
    clean_base_url,
    resolve_api_key,
)

from tests.helpers import FakeTransport, make_client, response


def test_clean_base_url():
    assert clean_base_url("https://app.offense.sh/") == "https://app.offense.sh"
    assert clean_base_url(None) == "https://app.offense.sh"


def test_request_requires_key(monkeypatch):
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    client = OffenseClient(base_url="https://x.test", transport=FakeTransport())
    assert not client.has_key
    with pytest.raises(OffenseAuthError) as caught:
        client.whoami()
    assert "not configured" in str(caught.value)
    assert client.keys_url() in str(caught.value)


def test_env_api_key_is_used(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, "offense_sk_env")
    assert resolve_api_key() == "offense_sk_env"
    client = OffenseClient(base_url="https://x.test", transport=FakeTransport())
    assert client.has_key


def test_explicit_key_overrides_environment(monkeypatch):
    monkeypatch.setenv(API_KEY_ENV, "offense_sk_env")
    client = OffenseClient(api_key="offense_sk_explicit", transport=FakeTransport())
    assert client.api_key == "offense_sk_explicit"


def test_request_sends_bearer_and_parses_json():
    transport = FakeTransport(response(200, {"workspace": {"id": "w1"}}))
    client = make_client(transport)
    data = client.whoami()
    assert data["workspace"]["id"] == "w1"
    call = transport.calls[0]
    assert call["method"] == "GET"
    assert call["url"] == "https://api.example.test/api/v1/whoami"
    assert call["headers"]["authorization"] == "Bearer offense_sk_test"


def test_api_error_carries_code_and_status():
    transport = FakeTransport(
        response(402, {"error": "insufficient_credits", "balanceMicros": 100})
    )
    client = make_client(transport)
    with pytest.raises(OffenseApiError) as caught:
        client.launch_sandboxes(budget_micros=1_000_000)
    assert caught.value.status == 402
    assert caught.value.code == "insufficient_credits"
    assert caught.value.data["balanceMicros"] == 100


def test_connection_error_is_wrapped():
    def broken(*_args, **_kwargs):
        raise OffenseConnectionError("Could not reach Offense: refused")

    client = OffenseClient(
        base_url="https://x.test", api_key="key", transport=broken
    )
    with pytest.raises(OffenseConnectionError):
        client.whoami()


def test_wait_for_sandbox_returns_terminal_state():
    transport = FakeTransport(
        response(200, {"sandbox": {"id": "s1", "status": "testing"}}),
        response(200, {"sandbox": {"id": "s1", "status": "completed"}}),
    )
    client = make_client(transport)
    result = client.wait_for_sandbox("s1", timeout_seconds=30, poll_seconds=1)
    assert result["terminal"] is True
    assert result["timed_out"] is False
    assert result["sandbox"]["status"] == "completed"
    assert len(transport.calls) == 2


def test_wait_for_sandbox_times_out():
    transport = FakeTransport(
        response(200, {"sandbox": {"id": "s1", "status": "testing"}}),
    )

    def clock() -> float:
        clock.value += 2.0
        return clock.value

    clock.value = 0.0
    client = make_client(transport, now=clock)
    result = client.wait_for_sandbox("s1", timeout_seconds=1, poll_seconds=1)
    assert result["terminal"] is False
    assert result["timed_out"] is True
    assert len(transport.calls) == 1


def test_wait_for_swarm_stops_when_terminal():
    transport = FakeTransport(
        response(
            200,
            {
                "swarm": {"id": "sw1", "status": "running"},
                "sandboxes": [],
                "findings": [],
            },
        ),
        response(
            200,
            {
                "swarm": {"id": "sw1", "status": "completed"},
                "sandboxes": [{"id": "s1"}],
                "findings": [{"id": "f1"}],
                "reportUrl": "https://app.offense.sh/app/swarms/sw1",
            },
        ),
    )
    client = make_client(transport)
    result = client.wait_for_swarm("sw1", timeout_seconds=30, poll_seconds=1)
    assert result["terminal"] is True
    assert result["report_url"].endswith("/app/swarms/sw1")
    assert result["findings"][0]["id"] == "f1"


def test_launch_swarm_request_shape():
    transport = FakeTransport(response(201, {"swarm": {"id": "sw1"}}))
    client = make_client(transport)
    client.summon_swarm(
        agents=5,
        budget_micros=2_000_000,
        instruction="Check tenant isolation",
        model="strix-1",
    )
    call = transport.calls[0]
    assert call["method"] == "POST"
    assert call["url"] == "https://api.example.test/api/v1/swarms"
    assert call["body"] == {
        "count": 5,
        "budgetMicros": 2_000_000,
        "instruction": "Check tenant isolation",
        "model": "strix-1",
        "idempotencyKey": call["body"]["idempotencyKey"],
    }
    assert call["headers"]["idempotency-key"] == call["body"]["idempotencyKey"]


def test_no_credential_file_is_written(tmp_path, monkeypatch):
    """The plugin must not own a key file (catalog rule 11)."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(API_KEY_ENV, "offense_sk_env")
    client = OffenseClient(base_url="https://x.test", transport=FakeTransport())
    assert client.has_key
    assert list(tmp_path.iterdir()) == []
    assert not (tmp_path / ".config").exists()


def test_client_never_imports_shared_mcp_config():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1] / "offense_client.py"
    ).read_text(encoding="utf-8")
    assert "mcp.json" not in source
    assert "save_config" not in source
