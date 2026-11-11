"""Client tests: HTTP shape, config persistence, device login, polling."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from offense_plugin.offense_client import (
    OffenseApiError,
    OffenseAuthError,
    OffenseClient,
    OffenseConnectionError,
    clean_base_url,
)

from tests.helpers import FakeTransport, make_client, response


def test_clean_base_url():
    assert clean_base_url("https://app.offense.sh/") == "https://app.offense.sh"
    assert clean_base_url(None) == "https://app.offense.sh"


def test_request_requires_key():
    client = OffenseClient(base_url="https://x.test", api_key="", transport=FakeTransport())
    with pytest.raises(OffenseAuthError):
        client.whoami()


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


def test_config_roundtrip_is_owner_only(tmp_path: Path):
    path = tmp_path / "nested" / "hermes.json"
    transport = FakeTransport()
    client = make_client(transport, config_path=path).load_config()
    client.save_config()

    assert json.loads(path.read_text())["apiKey"] == "offense_sk_test"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    restored = OffenseClient(
        base_url=None, api_key="", config_path=path, transport=transport
    ).load_config()
    assert restored.has_key
    assert restored.api_key == "offense_sk_test"


def test_reads_shared_mcp_config(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OFFENSE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "mcp.json").write_text(
        json.dumps({"baseUrl": "https://mcp.example.test", "apiKey": "offense_sk_mcp"})
    )
    client = OffenseClient(
        base_url=None, api_key=None, transport=FakeTransport(), sleep=lambda _s: None
    ).load_config()
    assert client.api_key == "offense_sk_mcp"
    assert client.base_url == "https://mcp.example.test"


def test_logout_does_not_reattach_to_shared_config(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OFFENSE_CONFIG_DIR", str(tmp_path))
    (tmp_path / "mcp.json").write_text(json.dumps({"apiKey": "offense_sk_mcp"}))
    client = OffenseClient(
        base_url=None, api_key=None, transport=FakeTransport(), sleep=lambda _s: None
    ).load_config()
    assert client.has_key
    client.logout()
    client.load_config()
    assert not client.has_key
    assert (tmp_path / "mcp.json").exists()


def test_env_api_key_is_used(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("OFFENSE_API_KEY", "offense_sk_env")
    monkeypatch.setenv("OFFENSE_CONFIG_DIR", str(tmp_path))
    client = OffenseClient(
        base_url=None, api_key=None, transport=FakeTransport(), sleep=lambda _s: None
    ).load_config()
    assert client.api_key == "offense_sk_env"


def test_device_login_start_and_finish(tmp_path: Path):
    config = tmp_path / "hermes.json"
    transport = FakeTransport(
        response(
            201,
            {
                "device_code": "dev-1",
                "user_code": "ABCD-1234",
                "verification_uri": "https://app.offense.sh/activate?code=ABCD-1234",
                "expires_in": 600,
                "interval": 5,
            },
        ),
        response(428, {"error": "authorization_pending"}),
        response(
            200,
            {
                "access_token": "offense_sk_new",
                "workspace_id": "w1",
                "scopes": ["assessments:create"],
            },
        ),
    )
    client = OffenseClient(
        base_url="https://app.offense.sh",
        api_key="",
        config_path=config,
        transport=transport,
        sleep=lambda _seconds: None,
    )
    started = client.start_login()
    assert started["user_code"] == "ABCD-1234"
    assert client.pending_login is not None

    finished = client.finish_login(timeout_seconds=10)
    assert finished["connected"] is True
    assert client.api_key == "offense_sk_new"
    assert client.pending_login is None
    assert json.loads(config.read_text())["apiKey"] == "offense_sk_new"

    token_call = transport.calls[-1]
    assert token_call["url"].endswith("/api/device/token")
    assert "authorization" not in token_call["headers"]


def test_device_login_expired_code():
    transport = FakeTransport(response(400, {"error": "expired_token"}))
    client = make_client(transport)
    client.pending_login = {
        "device_code": "dev-1",
        "interval": 1,
        "expires_at": __import__("time").time() + 100,
        "base_url": client.base_url,
    }
    with pytest.raises(OffenseAuthError, match="expired"):
        client.finish_login(timeout_seconds=5)
    assert client.pending_login is None


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
