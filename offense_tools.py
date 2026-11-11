"""Tool handlers for the Offense plugin.

Every handler receives the model's arguments and returns a JSON string, even
on failure. Handlers never raise: Hermes reports a raised exception as a tool
crash, which hides the actionable message the user needs.
"""

from __future__ import annotations

import functools
import json
import logging
import time
from collections.abc import Callable
from typing import Any

from .offense_client import (
    ACTIVE_SWARM_STATES,
    TERMINAL_SANDBOX_STATES,
    OffenseApiError,
    OffenseAuthError,
    OffenseClient,
    OffenseConnectionError,
    OffenseError,
)

logger = logging.getLogger(__name__)

DEFAULT_BUDGET_MICROS = 1_000_000
MAX_SANDBOX_BATCH = 5
MAX_WAIT_SANDBOX_SECONDS = 600
MAX_WAIT_SWARM_SECONDS = 3600

# Keys from an API error worth surfacing; the rest is noise to the model.
_ERROR_DETAIL_KEYS = (
    "error",
    "reason",
    "setupUrl",
    "minimum",
    "maximum",
    "maximumAgents",
    "requiredMicros",
    "balanceMicros",
    "limit",
    "active",
)


def ok(**payload: Any) -> str:
    return json.dumps({"success": True, **payload}, default=str)


def fail(message: str, **extra: Any) -> str:
    return json.dumps({"success": False, "error": message, **extra}, default=str)


def _int(args: dict[str, Any], key: str, default: int, low: int | None = None, high: int | None = None) -> int:
    try:
        value = int(args.get(key, default))
    except (TypeError, ValueError):
        value = default
    if low is not None:
        value = max(low, value)
    if high is not None:
        value = min(high, value)
    return value


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def dollars(micros: Any) -> str:
    try:
        return f"${int(micros) / 1_000_000:,.2f}"
    except (TypeError, ValueError):
        return "$0.00"


def sandbox_summary(sandbox: dict[str, Any], client: OffenseClient) -> dict[str, Any]:
    """Return the fields a model needs, without the provider plumbing."""
    sandbox_id = str(sandbox.get("id") or "")
    return {
        "id": sandbox_id,
        "status": sandbox.get("status"),
        "target": sandbox.get("target"),
        "project": sandbox.get("project") or "",
        "instruction": sandbox.get("instruction") or "",
        "model": sandbox.get("model"),
        "job_kind": sandbox.get("jobKind") or "assessment",
        "budget_micros": sandbox.get("budgetMicros"),
        "spent_micros": sandbox.get("spentMicros"),
        "swarm_id": sandbox.get("swarmId"),
        "swarm_index": sandbox.get("swarmIndex"),
        "swarm_role": sandbox.get("swarmRole") or "",
        "summary": sandbox.get("summary"),
        "created_at": sandbox.get("createdAt"),
        "started_at": sandbox.get("startedAt"),
        "completed_at": sandbox.get("completedAt"),
        "url": client.sandbox_url(sandbox_id) if sandbox_id else None,
    }


def swarm_summary(payload: dict[str, Any], client: OffenseClient) -> dict[str, Any]:
    swarm = payload.get("swarm") or {}
    swarm_id = str(swarm.get("id") or "")
    members = [
        sandbox_summary(sandbox, client) for sandbox in (payload.get("sandboxes") or [])
    ]
    return {
        "swarm": swarm,
        "members": members,
        "findings": payload.get("findings") or [],
        "report_url": payload.get("reportUrl")
        or (client.swarm_url(swarm_id) if swarm_id else None),
    }


def next_step(target: dict[str, Any] | None, client: OffenseClient) -> str:
    """One actionable sentence describing what blocks a launch."""
    if not target:
        return "Register a staging URL the user owns with offense_register_target."
    if not target.get("verified"):
        verification = target.get("verification") or {}
        url = verification.get("url") or "the /.well-known/offense-verify.txt path"
        return (
            f"Publish the verification token at {url}, then call "
            "offense_verify_target."
        )
    if len(target.get("identities") or []) != 2:
        return (
            "Open the identities page and add two test accounts in separate "
            f"organizations: {client.setup_urls()['identities']}"
        )
    return "Target is ready. Launch a sandbox or summon a swarm."


def active_work(client: OffenseClient) -> dict[str, int]:
    """Count active sandboxes and swarms. Raises on auth or network errors."""
    sandboxes = client.list_sandboxes().get("sandboxes") or []
    swarms = client.list_swarms().get("swarms") or []
    return {
        "active_sandboxes": sum(
            1 for sandbox in sandboxes if sandbox.get("status") not in TERMINAL_SANDBOX_STATES
        ),
        "active_swarms": sum(
            1 for swarm in swarms if swarm.get("status") in ACTIVE_SWARM_STATES
        ),
    }


def build_handlers(
    client: OffenseClient,
    *,
    settings: dict[str, Any] | None = None,
) -> dict[str, Callable[..., str]]:
    """Create one handler per tool, bound to a client and plugin settings."""
    settings = settings or {}

    def guard(function: Callable[..., str]) -> Callable[..., str]:
        @functools.wraps(function)
        def wrapped(args: dict[str, Any] | None = None, **kwargs: Any) -> str:
            try:
                return function(args or {}, **kwargs)
            except OffenseAuthError as error:
                return fail(
                    str(error),
                    code="not_connected",
                    login_tool="offense_login",
                    setup=client.setup_urls(),
                )
            except OffenseApiError as error:
                details = {
                    key: error.data[key]
                    for key in _ERROR_DETAIL_KEYS
                    if key in error.data and key != "error"
                }
                return fail(
                    str(error),
                    code=error.code or "api_error",
                    status=error.status or None,
                    **details,
                )
            except OffenseConnectionError as error:
                return fail(str(error), code="connection_error")
            except OffenseError as error:
                return fail(str(error), code="offense_error")
            except Exception as error:  # pragma: no cover - last-resort safety net
                logger.exception("Unexpected Offense plugin failure")
                return fail(f"Unexpected error: {error}", code="internal_error")

        return wrapped

    def preflight() -> tuple[dict[str, Any] | None, str | None]:
        """Check the target before spending money. Returns (target, error)."""
        target = client.current_target()
        if not target:
            return None, fail(
                "No target registered. Register a staging URL the user owns "
                "with offense_register_target.",
                code="target_missing",
                setup=client.setup_urls(),
            )
        if not target.get("verified"):
            return target, fail(
                "The target is not verified, so Offense cannot test it yet.",
                code="target_unverified",
                verification=target.get("verification"),
                next_step=next_step(target, client),
                setup=client.setup_urls(),
            )
        if len(target.get("identities") or []) != 2:
            return target, fail(
                "Two test identities in separate organizations are required "
                "before a sandbox can start.",
                code="identities_missing",
                target_id=target.get("id"),
                next_step=next_step(target, client),
                setup=client.setup_urls(),
            )
        return target, None

    # -- connection ----------------------------------------------------

    @guard
    def status(args: dict[str, Any], **kwargs: Any) -> str:
        del args, kwargs
        client.load_config()
        if not client.has_key:
            return fail(
                "Not connected to Offense. Call offense_login, show the user "
                "the verification URL and code, then finish the login.",
                code="not_connected",
                login_tool="offense_login",
                setup=client.setup_urls(),
            )
        whoami = client.whoami()
        target = client.current_target()
        counts = active_work(client)
        return ok(
            workspace=whoami.get("workspace"),
            key=whoami.get("key"),
            target=target,
            can_launch=bool(
                target
                and target.get("verified")
                and len(target.get("identities") or []) == 2
            ),
            next_step=next_step(target, client),
            setup=client.setup_urls(),
            **counts,
        )

    @guard
    def login(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        if _bool(args.get("finish")):
            timeout = _int(args, "timeout_seconds", 45, 1, 300)
            return ok(**client.finish_login(timeout))
        return ok(**client.start_login(str(settings.get("client_name") or "Hermes")))

    @guard
    def logout(args: dict[str, Any], **kwargs: Any) -> str:
        del args, kwargs
        client.logout()
        return ok(message="Removed the local Offense API key.")

    # -- targets -------------------------------------------------------

    @guard
    def register_target(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        target = str(args.get("target") or "").strip()
        if not target:
            return fail("Pass the staging base URL as target.", code="missing_target")
        if not target.startswith(("http://", "https://")):
            return fail(
                "The target must be an http(s) URL, for example "
                "https://staging.example.com",
                code="invalid_target",
            )
        data = client.register_target(target, str(args.get("project") or ""))
        registered = data.get("target") or {}
        return ok(
            target=registered,
            next_step=next_step(registered, client),
            setup=client.setup_urls(),
        )

    @guard
    def verify_target(args: dict[str, Any], **kwargs: Any) -> str:
        del args, kwargs
        client.verify_target()
        target = client.current_target()
        return ok(
            target=target,
            next_step=next_step(target, client),
            setup=client.setup_urls(),
        )

    # -- sandboxes -----------------------------------------------------

    @guard
    def launch_sandbox(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        _target, blocked = preflight()
        if blocked:
            return blocked
        budget = _int(args, "budget_micros", DEFAULT_BUDGET_MICROS, 1)
        count = _int(args, "count", 1, 1, MAX_SANDBOX_BATCH)
        data = client.launch_sandboxes(
            budget_micros=budget,
            count=count,
            instruction=str(args.get("task") or ""),
            model=str(args.get("model") or ""),
            idempotency_key=args.get("idempotency_key"),
        )
        sandboxes = [
            sandbox_summary(sandbox, client) for sandbox in (data.get("sandboxes") or [])
        ]
        return ok(
            sandboxes=sandboxes,
            count=len(sandboxes),
            reserved=dollars(budget * len(sandboxes)),
            message=(
                f"Launched {len(sandboxes)} sandbox(es). Follow with "
                "offense_wait_sandbox, then offense_sandbox_findings."
            ),
        )

    @guard
    def list_sandboxes(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        limit = _int(args, "limit", 10, 1, 50)
        sandboxes = client.list_sandboxes().get("sandboxes") or []
        return ok(
            sandboxes=[sandbox_summary(sandbox, client) for sandbox in sandboxes[:limit]],
            total=len(sandboxes),
        )

    @guard
    def get_sandbox(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        sandbox_id = str(args.get("sandbox_id") or "").strip()
        if not sandbox_id:
            return fail("Pass sandbox_id.", code="missing_sandbox_id")
        sandbox = client.get_sandbox(sandbox_id).get("sandbox") or {}
        return ok(sandbox=sandbox_summary(sandbox, client))

    @guard
    def wait_sandbox(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        sandbox_id = str(args.get("sandbox_id") or "").strip()
        if not sandbox_id:
            return fail("Pass sandbox_id.", code="missing_sandbox_id")
        timeout = _int(args, "timeout_seconds", 120, 1, MAX_WAIT_SANDBOX_SECONDS)
        poll = _int(args, "poll_seconds", 5, 1, 60)
        result = client.wait_for_sandbox(
            sandbox_id, timeout_seconds=timeout, poll_seconds=poll
        )
        sandbox = result.get("sandbox") or {}
        return ok(
            sandbox=sandbox_summary(sandbox, client),
            terminal=result["terminal"],
            timed_out=result["timed_out"],
            message=(
                "Sandbox finished."
                if result["terminal"]
                else "Still running. Call offense_wait_sandbox again or report progress."
            ),
        )

    @guard
    def sandbox_findings(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        sandbox_id = str(args.get("sandbox_id") or "").strip()
        if not sandbox_id:
            return fail("Pass sandbox_id.", code="missing_sandbox_id")
        data = client.sandbox_findings(sandbox_id)
        findings = data.get("findings") or []
        counts: dict[str, int] = {}
        for finding in findings:
            status_value = str(finding.get("verificationStatus") or "unverified")
            counts[status_value] = counts.get(status_value, 0) + 1
        return ok(
            findings=findings,
            count=len(findings),
            by_verification=counts,
            note=(
                "Candidate findings are not confirmed. Use offense_verify_finding "
                "or the verifier result before reporting one as reproduced."
            ),
        )

    @guard
    def sandbox_evidence(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        sandbox_id = str(args.get("sandbox_id") or "").strip()
        if not sandbox_id:
            return fail("Pass sandbox_id.", code="missing_sandbox_id")
        data = client.sandbox_evidence(sandbox_id)
        bundles = data.get("evidence") or []
        return ok(
            evidence=bundles,
            count=len(bundles),
            note="Evidence is redacted and may be partial; checksums are in each manifest.",
        )

    @guard
    def stop_sandbox(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        sandbox_id = str(args.get("sandbox_id") or "").strip()
        if not sandbox_id:
            return fail("Pass sandbox_id.", code="missing_sandbox_id")
        client.stop_sandbox(sandbox_id)
        sandbox = client.get_sandbox(sandbox_id).get("sandbox") or {}
        return ok(
            sandbox=sandbox_summary(sandbox, client),
            message="Sandbox stopped. Unused reserved budget is refunded.",
        )

    @guard
    def verify_finding(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        sandbox_id = str(args.get("sandbox_id") or "").strip()
        finding_id = str(args.get("finding_id") or "").strip()
        if not sandbox_id or not finding_id:
            return fail("Pass sandbox_id and finding_id.", code="missing_ids")
        data = client.verify_finding(sandbox_id, finding_id)
        return ok(
            result=data,
            message="Verification started. Read the result with offense_sandbox_findings.",
        )

    @guard
    def retest_finding(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        sandbox_id = str(args.get("sandbox_id") or "").strip()
        finding_id = str(args.get("finding_id") or "").strip()
        if not sandbox_id or not finding_id:
            return fail("Pass sandbox_id and finding_id.", code="missing_ids")
        data = client.retest_finding(sandbox_id, finding_id)
        assessment = data.get("assessment") or data.get("sandbox") or {}
        return ok(
            assessment=assessment,
            result=data,
            message=(
                "Retest started. Follow the new assessment with "
                "offense_wait_sandbox and offense_sandbox_findings."
            ),
        )

    # -- swarms --------------------------------------------------------

    @guard
    def list_swarms(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        limit = _int(args, "limit", 10, 1, 50)
        swarms = client.list_swarms().get("swarms") or []
        return ok(swarms=swarms[:limit], total=len(swarms))

    @guard
    def summon_swarm(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        _target, blocked = preflight()
        if blocked:
            return blocked
        agents = _int(args, "agents", 3, 2)
        budget = _int(args, "budget_micros", DEFAULT_BUDGET_MICROS, 1)
        data = client.summon_swarm(
            agents=agents,
            budget_micros=budget,
            instruction=str(args.get("task") or ""),
            model=str(args.get("model") or ""),
            idempotency_key=args.get("idempotency_key"),
        )
        summary = swarm_summary(data, client)
        member_count = len(summary["members"])
        return ok(
            **summary,
            reserved=dollars(budget * member_count),
            message=(
                f"Summoned {member_count} agents. Each has a different focus "
                "area. Follow with offense_wait_swarm, then offense_get_swarm "
                "for the combined report."
            ),
        )

    @guard
    def get_swarm(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        swarm_id = str(args.get("swarm_id") or "").strip()
        if not swarm_id:
            return fail("Pass swarm_id.", code="missing_swarm_id")
        return ok(**swarm_summary(client.get_swarm(swarm_id), client))

    @guard
    def wait_swarm(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        swarm_id = str(args.get("swarm_id") or "").strip()
        if not swarm_id:
            return fail("Pass swarm_id.", code="missing_swarm_id")
        timeout = _int(args, "timeout_seconds", 300, 1, MAX_WAIT_SWARM_SECONDS)
        poll = _int(args, "poll_seconds", 10, 1, 120)
        result = client.wait_for_swarm(
            swarm_id, timeout_seconds=timeout, poll_seconds=poll
        )
        return ok(
            swarm=result.get("swarm"),
            members=[
                sandbox_summary(sandbox, client)
                for sandbox in (result.get("sandboxes") or [])
            ],
            findings=result.get("findings") or [],
            report_url=result.get("report_url"),
            terminal=result["terminal"],
            timed_out=result["timed_out"],
            message=(
                "Swarm finished."
                if result["terminal"]
                else "Members are still running. Call offense_wait_swarm again."
            ),
        )

    @guard
    def stop_swarm(args: dict[str, Any], **kwargs: Any) -> str:
        del kwargs
        swarm_id = str(args.get("swarm_id") or "").strip()
        if not swarm_id:
            return fail("Pass swarm_id.", code="missing_swarm_id")
        data = client.stop_swarm(swarm_id)
        return ok(
            cancelled=data.get("cancelled", 0),
            swarm=data.get("swarm"),
            members=[
                sandbox_summary(sandbox, client)
                for sandbox in (data.get("sandboxes") or [])
            ],
            message="Swarm stopped. Unused reserved budget is refunded.",
        )

    return {
        "offense_status": status,
        "offense_login": login,
        "offense_logout": logout,
        "offense_register_target": register_target,
        "offense_verify_target": verify_target,
        "offense_launch_sandbox": launch_sandbox,
        "offense_list_sandboxes": list_sandboxes,
        "offense_get_sandbox": get_sandbox,
        "offense_wait_sandbox": wait_sandbox,
        "offense_sandbox_findings": sandbox_findings,
        "offense_sandbox_evidence": sandbox_evidence,
        "offense_stop_sandbox": stop_sandbox,
        "offense_verify_finding": verify_finding,
        "offense_retest_finding": retest_finding,
        "offense_list_swarms": list_swarms,
        "offense_summon_swarm": summon_swarm,
        "offense_get_swarm": get_swarm,
        "offense_wait_swarm": wait_swarm,
        "offense_stop_swarm": stop_swarm,
    }


class ActivityReporter:
    """Cheap, rate-limited active-work summary for the pre_llm_call hook."""

    def __init__(self, client: OffenseClient, *, ttl_seconds: int = 45) -> None:
        self.client = client
        self.ttl_seconds = ttl_seconds
        self._cached_at = 0.0
        self._cached: dict[str, int] | None = None

    def line(self) -> str | None:
        if not self.client.has_key:
            return None
        now = time.monotonic()
        if now - self._cached_at > self.ttl_seconds:
            try:
                self._cached = active_work(self.client)
            except OffenseError:
                self._cached = None
            self._cached_at = now
        counts = self._cached
        if not counts:
            return None
        if not counts["active_sandboxes"] and not counts["active_swarms"]:
            return None
        return (
            "Offense is already running work for this account: "
            f"{counts['active_sandboxes']} active sandbox(es), "
            f"{counts['active_swarms']} active swarm(s). Use offense_status "
            "before launching more."
        )
