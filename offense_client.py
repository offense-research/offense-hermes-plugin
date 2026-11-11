"""Standard-library client for the Offense agent API.

The client is intentionally small: one HTTP helper and one credential
resolution rule. It has no third-party dependencies so the plugin can run in
any Hermes install, including ones that do not manage Python packages.

Credentials come through Hermes: the plugin declares ``OFFENSE_API_KEY`` in
``plugin.yaml`` and reads it with :func:`agent.secret_scope.get_secret`, which
honors the active profile. There is no plugin-owned key file.

API shape is documented at https://app.offense.sh/api/openapi.json.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Callable
from typing import Any

DEFAULT_BASE_URL = "https://app.offense.sh"
API_KEY_ENV = "OFFENSE_API_KEY"

try:  # Hermes' profile-scoped secret route; absent outside a Hermes process.
    from agent.secret_scope import get_secret as _hermes_get_secret
except ImportError:  # pragma: no cover - exercised only outside Hermes
    _hermes_get_secret = None

# Sandbox states after which no further progress is possible.
TERMINAL_SANDBOX_STATES = frozenset(
    {"completed", "failed", "cancelled", "budget_exhausted", "blocked"}
)
# A swarm is active while any member is queued or running.
ACTIVE_SWARM_STATES = frozenset({"queued", "running"})

Payload = dict[str, Any]
Transport = Callable[[str, str, dict[str, str], bytes | None, float], tuple[int, dict[str, str], bytes]]


class OffenseError(Exception):
    """Base error for the plugin."""


class OffenseAuthError(OffenseError):
    """No usable API key is configured."""


class OffenseConnectionError(OffenseError):
    """The Offense API could not be reached."""


class OffenseApiError(OffenseError):
    """The API answered with an error status."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 0,
        code: str = "",
        data: Payload | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.data = data or {}


def clean_base_url(value: str | None) -> str:
    """Return a base URL without a trailing slash."""
    return (value or DEFAULT_BASE_URL).strip().rstrip("/")


def resolve_api_key() -> str:
    """Return the Offense API key through Hermes' credential route.

    Under Hermes, the profile-scoped secret is authoritative and a read failure
    fails closed rather than picking up another profile's environment. Outside
    Hermes (tests, a standalone import) the process environment is the only
    source available.
    """
    if _hermes_get_secret is not None:
        try:
            return str(_hermes_get_secret(API_KEY_ENV) or "").strip()
        except Exception:
            return ""
    return str(os.environ.get(API_KEY_ENV) or "").strip()


def _urllib_transport(
    method: str,
    url: str,
    headers: dict[str, str],
    data: bytes | None,
    timeout: float,
) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.code, dict(error.headers or {}), error.read()
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        reason = getattr(error, "reason", error)
        raise OffenseConnectionError(f"Could not reach Offense: {reason}") from error


class OffenseClient:
    """Small Offense API client with lazy, Hermes-scoped credential lookup."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
        timeout: float = 30.0,
    ) -> None:
        env_base = os.environ.get("OFFENSE_BASE_URL")
        self.base_url = clean_base_url(base_url or env_base)
        self._api_key_override = api_key
        self._transport = transport or _urllib_transport
        self._sleep = sleep
        self._now = now
        self.timeout = timeout

    # -- credentials ---------------------------------------------------

    @property
    def api_key(self) -> str:
        """Resolve the key on every read, so a session's scope always applies."""
        if self._api_key_override is not None:
            return self._api_key_override.strip()
        return resolve_api_key()

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    def not_configured_message(self) -> str:
        return (
            "Offense is not configured. Create an API key at "
            f"{self.keys_url()} and set {API_KEY_ENV} for this plugin "
            "(Hermes prompts for it at install; the Desktop plugin settings "
            "page has a masked field)."
        )

    # -- HTTP ----------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"{self.base_url}/{path.lstrip('/')}"

    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        body: Payload | None = None,
        auth: bool = True,
        headers: dict[str, str] | None = None,
    ) -> Payload:
        """Call the API and return the decoded JSON object."""
        api_key = self.api_key
        if auth and not api_key:
            raise OffenseAuthError(self.not_configured_message())

        request_headers: dict[str, str] = {"accept": "application/json"}
        if headers:
            request_headers.update(headers)
        if auth:
            request_headers["authorization"] = f"Bearer {api_key}"
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            request_headers["content-type"] = "application/json"

        status, _response_headers, raw = self._transport(
            method, self._url(path), request_headers, data, self.timeout
        )
        try:
            decoded = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, ValueError):
            decoded = {}
        if not isinstance(decoded, dict):
            decoded = {"data": decoded}

        if not 200 <= status < 300:
            code = str(decoded.get("error") or "")
            message = str(
                decoded.get("message")
                or decoded.get("reason")
                or code
                or f"Offense API returned HTTP {status}"
            )
            raise OffenseApiError(message, status=status, code=code, data=decoded)
        return decoded

    # -- account -------------------------------------------------------

    def whoami(self) -> Payload:
        return self.request("/api/v1/whoami")

    # -- targets -------------------------------------------------------

    def targets(self) -> Payload:
        return self.request("/api/v1/targets")

    def current_target(self) -> Payload | None:
        targets = self.targets().get("targets") or []
        return targets[0] if targets else None

    def register_target(self, target: str, project: str = "") -> Payload:
        return self.request(
            "/api/v1/targets",
            method="POST",
            body={"target": target, "project": (project or "")[:120]},
        )

    def verify_target(self, target_id: str | None = None) -> Payload:
        if not target_id:
            target = self.current_target()
            target_id = (target or {}).get("id")
        if not target_id:
            raise OffenseError("No target registered. Call offense_register_target first.")
        return self.request(
            f"/api/v1/targets/{urllib.parse.quote(str(target_id), safe='')}/verify",
            method="POST",
        )

    # -- sandboxes -----------------------------------------------------

    def launch_sandboxes(
        self,
        *,
        budget_micros: int,
        instruction: str = "",
        count: int = 1,
        model: str = "",
        idempotency_key: str | None = None,
    ) -> Payload:
        key = (idempotency_key or f"hermes-{uuid.uuid4().hex}")[:90]
        return self.request(
            "/api/v1/sandboxes",
            method="POST",
            headers={"idempotency-key": key},
            body={
                "count": count,
                "budgetMicros": int(budget_micros),
                "instruction": (instruction or "")[:2000],
                "model": (model or "")[:120],
                "idempotencyKey": key,
            },
        )

    def list_sandboxes(self) -> Payload:
        return self.request("/api/v1/sandboxes")

    def get_sandbox(self, sandbox_id: str) -> Payload:
        return self.request(
            f"/api/v1/sandboxes/{urllib.parse.quote(sandbox_id, safe='')}"
        )

    def stop_sandbox(self, sandbox_id: str) -> Payload:
        return self.request(
            f"/api/v1/sandboxes/{urllib.parse.quote(sandbox_id, safe='')}/stop",
            method="POST",
        )

    def sandbox_findings(self, sandbox_id: str) -> Payload:
        return self.request(
            f"/api/v1/sandboxes/{urllib.parse.quote(sandbox_id, safe='')}/findings"
        )

    def sandbox_evidence(self, sandbox_id: str) -> Payload:
        return self.request(
            f"/api/v1/assessments/{urllib.parse.quote(sandbox_id, safe='')}/evidence"
        )

    def sandbox_usage(self, sandbox_id: str) -> Payload:
        return self.request(
            f"/api/v1/assessments/{urllib.parse.quote(sandbox_id, safe='')}/usage"
        )

    def verify_finding(self, sandbox_id: str, finding_id: str) -> Payload:
        return self.request(
            f"/api/v1/assessments/{urllib.parse.quote(sandbox_id, safe='')}"
            f"/findings/{urllib.parse.quote(finding_id, safe='')}/verify",
            method="POST",
        )

    def retest_finding(self, sandbox_id: str, finding_id: str) -> Payload:
        return self.request(
            f"/api/v1/assessments/{urllib.parse.quote(sandbox_id, safe='')}"
            f"/findings/{urllib.parse.quote(finding_id, safe='')}/retest",
            method="POST",
        )

    # -- swarms --------------------------------------------------------

    def summon_swarm(
        self,
        *,
        agents: int,
        budget_micros: int,
        instruction: str = "",
        model: str = "",
        idempotency_key: str | None = None,
    ) -> Payload:
        key = (idempotency_key or f"hermes-{uuid.uuid4().hex}")[:100]
        return self.request(
            "/api/v1/swarms",
            method="POST",
            headers={"idempotency-key": key},
            body={
                "count": int(agents),
                "budgetMicros": int(budget_micros),
                "instruction": (instruction or "")[:2000],
                "model": (model or "")[:120],
                "idempotencyKey": key,
            },
        )

    def list_swarms(self) -> Payload:
        return self.request("/api/v1/swarms")

    def get_swarm(self, swarm_id: str) -> Payload:
        return self.request(f"/api/v1/swarms/{urllib.parse.quote(swarm_id, safe='')}")

    def stop_swarm(self, swarm_id: str) -> Payload:
        return self.request(
            f"/api/v1/swarms/{urllib.parse.quote(swarm_id, safe='')}/stop",
            method="POST",
        )

    # -- waiting -------------------------------------------------------

    def wait_for_sandbox(
        self,
        sandbox_id: str,
        *,
        timeout_seconds: int = 120,
        poll_seconds: int = 5,
    ) -> Payload:
        """Poll a sandbox until it reaches a terminal state or time runs out."""
        deadline = self._now() + max(1, timeout_seconds)
        interval = max(1, poll_seconds)
        sandbox: Payload = {}
        while True:
            sandbox = self.get_sandbox(sandbox_id).get("sandbox") or {}
            status = str(sandbox.get("status") or "")
            if status in TERMINAL_SANDBOX_STATES:
                return {"sandbox": sandbox, "terminal": True, "timed_out": False}
            if self._now() >= deadline:
                return {"sandbox": sandbox, "terminal": False, "timed_out": True}
            self._sleep(min(interval, max(0.0, deadline - self._now())))

    def wait_for_swarm(
        self,
        swarm_id: str,
        *,
        timeout_seconds: int = 300,
        poll_seconds: int = 10,
    ) -> Payload:
        """Poll a swarm until it has no active members or time runs out."""
        deadline = self._now() + max(1, timeout_seconds)
        interval = max(1, poll_seconds)
        payload: Payload = {}
        while True:
            payload = self.get_swarm(swarm_id)
            status = str((payload.get("swarm") or {}).get("status") or "")
            if status not in ACTIVE_SWARM_STATES:
                return {
                    "swarm": payload.get("swarm"),
                    "sandboxes": payload.get("sandboxes") or [],
                    "findings": payload.get("findings") or [],
                    "report_url": payload.get("reportUrl"),
                    "terminal": True,
                    "timed_out": False,
                }
            if self._now() >= deadline:
                return {
                    "swarm": payload.get("swarm"),
                    "sandboxes": payload.get("sandboxes") or [],
                    "findings": payload.get("findings") or [],
                    "report_url": payload.get("reportUrl"),
                    "terminal": False,
                    "timed_out": True,
                }
            self._sleep(min(interval, max(0.0, deadline - self._now())))

    # -- links ---------------------------------------------------------

    def setup_urls(self) -> Payload:
        base = self.base_url
        return {
            "keys": self.keys_url(),
            "target": f"{base}/app/onboarding/target",
            "identities": f"{base}/app/onboarding/accounts?edit=1",
            "billing": f"{base}/app/billing",
            "sandboxes": f"{base}/app/sandboxes",
            "swarms": f"{base}/app/swarms",
        }

    def keys_url(self) -> str:
        return f"{self.base_url}/app/settings"

    def sandbox_url(self, sandbox_id: str) -> str:
        return f"{self.base_url}/app/assessments/{sandbox_id}"

    def swarm_url(self, swarm_id: str) -> str:
        return f"{self.base_url}/app/swarms/{swarm_id}"
