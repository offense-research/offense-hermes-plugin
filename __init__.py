"""Offense for Hermes — give the agent a security team.

Registers the ``offense`` toolset (spin up security sandboxes, summon swarms,
read findings, verify and retest), a bundled skill, a ``/offense`` slash
command, and an optional active-work summary for the model.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .offense_client import OffenseClient, OffenseError
from .offense_schemas import ALL as TOOL_SCHEMAS
from .offense_schemas import TOOLSET
from .offense_tools import ActivityReporter, active_work, build_handlers, dollars

logger = logging.getLogger(__name__)

DEFAULT_SETTINGS: dict[str, Any] = {
    "client_name": "Hermes",
    "inject_active_work": True,
    "active_work_ttl_seconds": 45,
}

HELP_TEXT = (
    "Offense security team for Hermes. Commands: /offense status, "
    "/offense sandboxes, /offense swarms, /offense help. Ask the agent to "
    "'summon a swarm' to run a broad assessment, or 'launch a sandbox' for a "
    "focused question."
)


def _read_settings(ctx: Any) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    for key, default in DEFAULT_SETTINGS.items():
        try:
            settings[key] = ctx.get_config(key, default=default)
        except Exception:  # get_config is best-effort for older Hermes builds
            settings[key] = default
    return settings


def _command(client: OffenseClient, settings: dict[str, Any], raw_args: str) -> str:
    """Handle /offense. Returns chat text, never prints."""
    del settings
    words = (raw_args or "").strip().split()
    command = words[0].lower() if words else "status"

    if command in {"help", "-h", "--help"}:
        return HELP_TEXT

    client.load_config()
    if not client.has_key:
        return (
            "Offense is not connected yet. Ask me to 'connect Offense' so I can "
            "start a device login, or see the plugin README."
        )

    try:
        if command in {"sandboxes", "runs"}:
            sandboxes = client.list_sandboxes().get("sandboxes") or []
            if not sandboxes:
                return "No sandboxes yet. Ask me to 'launch a sandbox'."
            lines = ["Recent sandboxes:"]
            for sandbox in sandboxes[:10]:
                spend = dollars(sandbox.get("spentMicros"))
                lines.append(
                    f"- {sandbox.get('id')}  {sandbox.get('status')}  "
                    f"spent {spend}  {sandbox.get('target')}"
                )
            return "\n".join(lines)

        if command in {"swarms", "swarm"}:
            swarms = client.list_swarms().get("swarms") or []
            if not swarms:
                return "No swarms yet. Ask me to 'summon a swarm'."
            lines = ["Recent swarms:"]
            for swarm in swarms[:10]:
                lines.append(
                    f"- {swarm.get('id')}  {swarm.get('status')}  "
                    f"{swarm.get('memberCount', 0)}/{swarm.get('size', 0)} agents  "
                    f"{swarm.get('findingCount', 0)} findings"
                )
            return "\n".join(lines)

        whoami = client.whoami()
        workspace = whoami.get("workspace") or {}
        target = client.current_target() or {}
        counts = active_work(client)
        target_line = target.get("target") or "none registered"
        if target and not target.get("verified"):
            target_line += " (not verified)"
        if target and len(target.get("identities") or []) != 2:
            target_line += " (needs two test identities)"
        return (
            f"Offense workspace: {workspace.get('name') or 'unknown'}  "
            f"balance {dollars(workspace.get('balanceMicros'))}\n"
            f"Target: {target_line}\n"
            f"Active: {counts['active_sandboxes']} sandbox(es), "
            f"{counts['active_swarms']} swarm(s)\n"
            f"Dashboard: {client.base_url}/app"
        )
    except OffenseError as error:
        return f"Offense error: {error}"


def register(ctx: Any) -> None:
    """Wire tools, the bundled skill, the slash command, and the hook."""
    client = OffenseClient().load_config()
    settings = _read_settings(ctx)
    handlers = build_handlers(client, settings=settings)

    for schema in TOOL_SCHEMAS:
        name = schema["name"]
        ctx.register_tool(
            name=name,
            toolset=TOOLSET,
            schema=schema,
            handler=handlers[name],
        )

    skills_dir = Path(__file__).parent / "skills"
    if skills_dir.is_dir():
        for child in sorted(skills_dir.iterdir()):
            skill_md = child / "SKILL.md"
            if child.is_dir() and skill_md.exists():
                try:
                    ctx.register_skill(child.name, skill_md)
                except Exception:
                    logger.warning("Offense: could not register skill %s", child.name)

    ctx.register_command(
        "offense",
        lambda raw, **kwargs: _command(client, settings, raw),
        description="Offense security team: status, sandboxes, swarms",
        args_hint="[status|sandboxes|swarms|help]",
    )

    reporter = ActivityReporter(
        client, ttl_seconds=int(settings.get("active_work_ttl_seconds") or 45)
    )

    def inject_active_work(**kwargs: Any) -> dict[str, str] | None:
        del kwargs
        if not settings.get("inject_active_work"):
            return None
        line = reporter.line()
        return {"context": line} if line else None

    ctx.register_hook("pre_llm_call", inject_active_work)
