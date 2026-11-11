"""Standard-library client for the Offense agent API.

The client is intentionally small: one HTTP helper, one config file, and a
device-login flow. It has no third-party dependencies so the plugin can run in
any Hermes install, including ones that do not manage Python packages.

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
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "https://app.offense.sh"

# Sandbox states after which no further progress is possible.
TERMINAL_SANDBOX_STATES = frozenset(
    {"completed", "failed", "cancelled", "budget_exhausted", "blocked"}
)
# A swarm is active while any member is queued or running.
ACTIVE_SWARM_STATES = frozenset({"queued", "running"})

CONFIG_FILENAME = "hermes.json"
SHARED_CONFIG_FILENAME = "mcp.json"

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


def config_dir() -> Path:
    """Return the Offense config directory, honoring OFFENSE_CONFIG_DIR."""
    return Path(
        os.environ.get("OFFENSE_CONFIG_DIR") or Path.home() / ".config" / "offense"
    ).expanduser()


def default_config_path() -> Path:
    """Return the path this plugin reads and writes."""
    override = os.environ.get("OFFENSE_CONFIG")
    if override:
        return Path(override).expanduser()
    return config_dir() / CONFIG_FILENAME


def shared_config_paths() -> list[Path]:
    """Return read-only config paths written by other Offense clients.

    The MCP server stores its key in ``mcp.json``. Reading it means a user who
    already connected an MCP client does not have to approve a second device
    code; the plugin still writes only its own file.
    """
    paths = [config_dir() / SHARED_CONFIG_FILENAME]
    return [path for path in paths if path != default_config_path()]


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


def _read_json(path: Path) -> Payload:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


class OffenseClient:
    """Small Offense API client with device login and config persistence."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        config_path: str | Path | None = None,
        transport: Transport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], float] = time.time,
        timeout: float = 30.0,
    ) -> None:
        env_base = os.environ.get("OFFENSE_BASE_URL")
        env_key = os.environ.get("OFFENSE_API_KEY")
        self.base_url = clean_base_url(base_url or env_base)
        self.api_key = (api_key if api_key is not None else (env_key or "")).strip()
        self.config_path = (
            Path(config_path).expanduser() if config_path else default_config_path()
        )
        self._read_shared_config = api_key is None and config_path is None
        self._explicit_base_url = bool(base_url or env_base)
        self._transport = transport or _urllib_transport
        self._sleep = sleep
        self._now = now
        self.timeout = timeout
        self.pending_login: Payload | None = None

    # -- configuration -------------------------------------------------

    @property
    def has_key(self) -> bool:
        return bool(self.api_key)

    def load_config(self) -> OffenseClient:
        """Fill an unset key or base URL from disk. Never raises."""
        data = _read_json(self.config_path)
        if not data and self._read_shared_config:
            for path in shared_config_paths():
                data = _read_json(path)
                if data:
                    break
        if not self.api_key and data.get("apiKey"):
            self.api_key = str(data["apiKey"]).strip()
        if not self._explicit_base_url and data.get("baseUrl"):
            self.base_url = clean_base_url(str(data["baseUrl"]))
        return self

    def save_config(self) -> None:
        """Write the key and base URL with owner-only permissions."""
        directory = self.config_path.parent
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        payload = json.dumps(
            {"baseUrl": self.base_url, "apiKey": self.api_key}, indent=2
        ) + "\n"
        fd = os.open(self.config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
        finally:
            try:
                os.chmod(self.config_path, 0o600)
            except OSError:
                pass

    def logout(self) -> None:
        """Drop the in-memory key, pending login, and the saved config file.

        A key read from another client's config (``mcp.json``) stays in that
        file; only this process stops using it, so logout does not silently
        disconnect the other client or delete a file this plugin does not own.
        """
        self.api_key = ""
        self.pending_login = None
        self._read_shared_config = False
        try:
            self.config_path.unlink()
        except FileNotFoundError:
            pass

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
        if auth and not self.api_key:
            raise OffenseAuthError(
                "Not connected to Offense. Call offense_login, show the user the "
                "verification URL and code, then call offense_login again with "
                'finish=true after they approve.'
            )

        request_headers: dict[str, str] = {"accept": "application/json"}
        if headers:
            request_headers.update(headers)
        if auth:
            request_headers["authorization"] = f"Bearer {self.api_key}"
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

    def start_login(self, name: str = "Hermes") -> Payload:
        data = self.request(
            "/api/device/code",
            method="POST",
            body={"name": (name or "Hermes")[:120]},
            auth=False,
        )
        interval = max(1, int(data.get("interval") or 5))
        self.pending_login = {
            "device_code": data.get("device_code"),
            "interval": interval,
            "expires_at": self._now() + max(30, int(data.get("expires_in") or 600)),
            "base_url": self.base_url,
        }
        return {
            "verification_uri": data.get("verification_uri"),
            "user_code": data.get("user_code"),
            "expires_in": data.get("expires_in", 600),
            "interval": interval,
            "message": (
                f"Open {data.get('verification_uri')} and approve code "
                f"{data.get('user_code')}. Then call offense_login with finish=true."
            ),
        }

    def finish_login(self, timeout_seconds: int = 45) -> Payload:
        pending = self.pending_login
        if not pending:
            raise OffenseAuthError(
                "No pending login. Call offense_login first, then approve the "
                "device code in the browser."
            )
        if pending.get("base_url") != self.base_url:
            self.pending_login = None
            raise OffenseAuthError(
                "The login was started against a different Offense server. "
                "Start again with offense_login."
            )

        deadline = min(
            self._now() + max(1, timeout_seconds), float(pending["expires_at"])
        )
        interval = max(1, int(pending["interval"]))
        while self._now() < deadline:
            try:
                data = self.request(
                    "/api/device/token",
                    method="POST",
                    body={"device_code": pending["device_code"]},
                    auth=False,
                )
            except OffenseApiError as error:
                if error.status == 428 or error.code == "authorization_pending":
                    self._sleep(interval)
                    continue
                if error.code in {"expired_token", "access_denied", "invalid_grant"}:
                    self.pending_login = None
                    friendly = {
                        "expired_token": "The device code expired. Call offense_login to start again.",
                        "access_denied": "The device login was denied in the browser.",
                        "invalid_grant": "The device code is no longer valid. Call offense_login to start again.",
                    }[error.code]
                    raise OffenseAuthError(friendly) from error
                raise

            token = str(data.get("access_token") or "")
            if not token:
                raise OffenseAuthError("Offense returned no access token.")
            self.api_key = token
            self.pending_login = None
            self.save_config()
            return {
                "connected": True,
                "workspace_id": data.get("workspace_id"),
                "scopes": data.get("scopes") or [],
                "message": "Offense connected. The API key is stored with mode 0600.",
            }

        return {
            "connected": False,
            "pending": True,
            "message": (
                "Still waiting for browser approval. Ask the user to approve the "
                "code, then call offense_login with finish=true again."
            ),
        }

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
            "target": f"{base}/app/onboarding/target",
            "identities": f"{base}/app/onboarding/accounts?edit=1",
            "billing": f"{base}/app/billing",
            "sandboxes": f"{base}/app/sandboxes",
            "swarms": f"{base}/app/swarms",
        }

    def sandbox_url(self, sandbox_id: str) -> str:
        return f"{self.base_url}/app/assessments/{sandbox_id}"

    def swarm_url(self, swarm_id: str) -> str:
        return f"{self.base_url}/app/swarms/{swarm_id}"

