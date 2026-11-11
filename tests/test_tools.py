"""Handler tests: preflight, budgets, error surfacing, and safe defaults."""

from __future__ import annotations

import json

from offense_plugin.offense_client import OffenseClient
from offense_plugin.offense_tools import ActivityReporter, build_handlers

from tests.helpers import FakeTransport, make_client, response

TARGET_READY = {
    "targets": [
        {
            "id": "t1",
            "target": "https://staging.example.com",
            "verified": True,
            "identities": [{"org": "A"}, {"org": "B"}],
        }
    ]
}

TARGET_UNVERIFIED = {
    "targets": [
        {
            "id": "t1",
            "target": "https://staging.example.com",
            "verified": False,
            "identities": [],
            "verification": {
                "url": "https://staging.example.com/.well-known/offense-verify.txt",
                "token": "verify-token",
            },
        }
    ]
}


def handlers_for(transport: FakeTransport):
    client = make_client(transport)
    return build_handlers(client, settings={}), client


def test_status_without_key_reports_login_tool():
    client = OffenseClient(
        base_url="https://x.test", api_key="", transport=FakeTransport()
    )
    handlers = build_handlers(client, settings={})
    payload = json.loads(handlers["offense_status"]({}))
    assert payload["success"] is False
    assert payload["code"] == "not_connected"
    assert payload["login_tool"] == "offense_login"
    assert "target" in payload["setup"]


def test_launch_blocked_without_target_does_not_post():
    transport = FakeTransport(response(200, {"targets": []}))
    handlers, _client = handlers_for(transport)
    payload = json.loads(handlers["offense_launch_sandbox"]({"task": "x"}))
    assert payload["success"] is False
    assert payload["code"] == "target_missing"
    assert len(transport.calls) == 1  # the targets preflight only


def test_launch_blocked_when_target_unverified():
    transport = FakeTransport(response(200, TARGET_UNVERIFIED))
    handlers, _client = handlers_for(transport)
    payload = json.loads(handlers["offense_launch_sandbox"]({}))
    assert payload["success"] is False
    assert payload["code"] == "target_unverified"
    assert payload["verification"]["token"] == "verify-token"
    assert "offense-verify.txt" in payload["next_step"]


def test_launch_sandbox_uses_default_budget_and_count():
    transport = FakeTransport(
        response(200, TARGET_READY),
        response(201, {"sandboxes": [{"id": "s1", "status": "queued"}]}),
    )
    handlers, client = handlers_for(transport)
    payload = json.loads(
        handlers["offense_launch_sandbox"]({"task": "Check invoice access"})
    )
    assert payload["success"] is True
    assert payload["count"] == 1
    launch = transport.calls[1]
    assert launch["url"].endswith("/api/v1/sandboxes")
    assert launch["body"]["budgetMicros"] == 1_000_000
    assert launch["body"]["count"] == 1
    assert launch["body"]["instruction"] == "Check invoice access"
    assert payload["sandboxes"][0]["url"] == f"{client.base_url}/app/assessments/s1"


def test_launch_sandbox_clamps_count_to_batch_max():
    transport = FakeTransport(
        response(200, TARGET_READY),
        response(201, {"sandboxes": [{"id": "s1", "status": "queued"}]}),
    )
    handlers, _client = handlers_for(transport)
    handlers["offense_launch_sandbox"]({"count": 99})
    assert transport.calls[1]["body"]["count"] == 5


def test_launch_sandbox_surfaces_credit_error_details():
    transport = FakeTransport(
        response(200, TARGET_READY),
        response(
            402,
            {
                "error": "insufficient_credits",
                "balanceMicros": 100,
                "requiredMicros": 1_000_000,
            },
        ),
    )
    handlers, _client = handlers_for(transport)
    payload = json.loads(handlers["offense_launch_sandbox"]({}))
    assert payload["success"] is False
    assert payload["code"] == "insufficient_credits"
    assert payload["status"] == 402
    assert payload["balanceMicros"] == 100


def test_summon_swarm_clamps_agents_to_minimum():
    transport = FakeTransport(
        response(200, TARGET_READY),
        response(
            201,
            {
                "swarm": {"id": "sw1", "status": "queued", "memberCount": 2},
                "sandboxes": [
                    {"id": "s1", "status": "queued", "swarmRole": "auth"},
                    {"id": "s2", "status": "queued", "swarmRole": "object-authz"},
                ],
                "findings": [],
                "reportUrl": "https://app.offense.sh/app/swarms/sw1",
            },
        ),
    )
    handlers, _client = handlers_for(transport)
    payload = json.loads(handlers["offense_summon_swarm"]({"agents": 1}))
    assert payload["success"] is True
    assert transport.calls[1]["body"]["count"] == 2
    assert payload["reserved"] == "$2.00"
    assert payload["report_url"].endswith("/app/swarms/sw1")
    assert [member["swarm_role"] for member in payload["members"]] == [
        "auth",
        "object-authz",
    ]


def test_wait_sandbox_reports_timeout():
    transport = FakeTransport(
        response(200, {"sandbox": {"id": "s1", "status": "testing"}}),
    )

    def clock() -> float:
        clock.value += 2.0
        return clock.value

    clock.value = 0.0
    client = make_client(transport, now=clock)
    handlers = build_handlers(client, settings={})
    payload = json.loads(
        handlers["offense_wait_sandbox"](
            {"sandbox_id": "s1", "timeout_seconds": 1, "poll_seconds": 1}
        )
    )
    assert payload["success"] is True
    assert payload["timed_out"] is True
    assert payload["terminal"] is False
    assert len(transport.calls) == 1


def test_handlers_never_raise_on_bad_arguments():
    transport = FakeTransport(response(200, TARGET_READY))
    handlers, _client = handlers_for(transport)
    for name in ("offense_get_sandbox", "offense_wait_sandbox", "offense_stop_swarm"):
        payload = json.loads(handlers[name]({"sandbox_id": None, "budget_micros": "abc"}))
        assert payload["success"] is False
        assert "error" in payload


def test_findings_summarize_verification_counts():
    transport = FakeTransport(
        response(
            200,
            {
                "findings": [
                    {"id": "f1", "verificationStatus": "verified"},
                    {"id": "f2", "verificationStatus": "unverified"},
                    {"id": "f3"},
                ]
            },
        )
    )
    handlers, _client = handlers_for(transport)
    payload = json.loads(handlers["offense_sandbox_findings"]({"sandbox_id": "s1"}))
    assert payload["count"] == 3
    assert payload["by_verification"] == {"verified": 1, "unverified": 2}
    assert "not confirmed" in payload["note"]


def test_activity_reporter_is_silent_without_work_and_caches():
    transport = FakeTransport(
        response(200, {"sandboxes": [{"status": "completed"}]}),
        response(200, {"swarms": []}),
    )
    client = make_client(transport)
    reporter = ActivityReporter(client, ttl_seconds=45)
    assert reporter.line() is None

    busy_transport = FakeTransport(
        response(200, {"sandboxes": [{"status": "running"}]}),
        response(200, {"swarms": [{"status": "running"}]}),
    )
    busy_client = make_client(busy_transport)
    busy = ActivityReporter(busy_client, ttl_seconds=45)
    line = busy.line()
    assert line is not None and "1 active sandbox" in line and "1 active swarm" in line
    busy.line()  # cached
    busy.line()
    assert len(busy_transport.calls) == 2  # no polling per turn
