"""Registration test: load the plugin like Hermes does and check the wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_plugin():
    import offense_plugin

    return offense_plugin


class FakeContext:
    def __init__(self, config: dict | None = None):
        self.tools: dict[str, dict] = {}
        self.hooks: dict[str, list] = {}
        self.skills: list[tuple[str, Path]] = []
        self.commands: list[tuple[str, object, str]] = []
        self.config = config or {}

    def get_config(self, key, default=None):
        return self.config.get(key, default)

    def register_tool(self, *, name, toolset, schema, handler):
        self.tools[name] = {
            "toolset": toolset,
            "schema": schema,
            "handler": handler,
        }

    def register_hook(self, name, callback, **kwargs):
        self.hooks.setdefault(name, []).append(callback)

    def register_skill(self, name, path):
        self.skills.append((name, Path(path)))

    def register_command(self, name, handler, description="", args_hint=""):
        self.commands.append((name, handler, description))


@pytest.fixture(autouse=True)
def isolated_home(monkeypatch, tmp_path):
    """Never read the developer's real ~/.config/offense during tests."""
    monkeypatch.delenv("OFFENSE_API_KEY", raising=False)
    monkeypatch.delenv("OFFENSE_BASE_URL", raising=False)


def test_register_wires_everything():
    plugin = load_plugin()
    ctx = FakeContext()
    plugin.register(ctx)

    assert len(ctx.tools) == 17
    assert set(ctx.tools) == {
        "offense_status",
        "offense_register_target",
        "offense_verify_target",
        "offense_launch_sandbox",
        "offense_list_sandboxes",
        "offense_get_sandbox",
        "offense_wait_sandbox",
        "offense_sandbox_findings",
        "offense_sandbox_evidence",
        "offense_stop_sandbox",
        "offense_verify_finding",
        "offense_retest_finding",
        "offense_list_swarms",
        "offense_summon_swarm",
        "offense_get_swarm",
        "offense_wait_swarm",
        "offense_stop_swarm",
    }
    for entry in ctx.tools.values():
        assert entry["toolset"] == "offense"
        assert entry["schema"]["parameters"]["type"] == "object"
        assert callable(entry["handler"])

    assert [name for name, _path in ctx.skills] == ["security-team"]
    assert ctx.skills[0][1].name == "SKILL.md"
    assert ctx.commands[0][0] == "offense"
    assert len(ctx.hooks["pre_llm_call"]) == 1


def test_manifest_declares_registered_surface():
    plugin = load_plugin()
    ctx = FakeContext()
    plugin.register(ctx)

    manifest = (ROOT / "plugin.yaml").read_text(encoding="utf-8")
    for name in ctx.tools:
        assert name in manifest, f"{name} missing from provides_tools"
    assert "pre_llm_call" in manifest
    assert "name: offense" in manifest
    assert "requires_hermes: \">=0.19.0\"" in manifest
    assert "requires_env:" in manifest and "OFFENSE_API_KEY" in manifest
    assert "config_schema:" in manifest


def test_slash_command_help_and_unconfigured():
    plugin = load_plugin()
    ctx = FakeContext()
    plugin.register(ctx)
    _name, handler, _description = ctx.commands[0]

    assert "Offense security team" in handler("help")
    text = handler("status").lower()
    assert "not configured" in text
    assert "offense_api_key" in text


def test_base_url_setting_is_honored():
    plugin = load_plugin()
    ctx = FakeContext(config={"base_url": "https://self.example.test"})
    plugin.register(ctx)
    _name, handler, _description = ctx.commands[0]
    assert "https://self.example.test/app/settings" in handler("status")


def test_active_work_hook_is_gated_by_setting():
    plugin = load_plugin()
    ctx = FakeContext(config={"inject_active_work": False})
    plugin.register(ctx)
    hook = ctx.hooks["pre_llm_call"][0]
    assert hook() is None
