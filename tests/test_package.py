"""Validate the portable package against the Hermes Agent Plugins contract.

These checks mirror what ``hermes plugins validate`` enforces plus the
product-specific facts (MCP endpoint, spend policy, no credentials in the
package). The live endpoint is checked separately by ``scripts/smoke_mcp.py``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
MCP_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/mcp.schema.json"
SKIP_PARTS = {".git", "__pycache__", ".pytest_cache", ".ruff_cache", ".venv"}


def package_files():
    for path in ROOT.rglob("*"):
        if path.is_file() and not SKIP_PARTS.intersection(path.parts):
            yield path


def load_json(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_plugin_manifest_is_portable():
    manifest = load_json("plugin.json")
    assert manifest["$schema"] == PLUGIN_SCHEMA
    assert manifest["name"] == "offense"
    assert re.fullmatch(r"\d+\.\d+\.\d+", manifest["version"])
    assert manifest["license"] == "Apache-2.0"
    assert manifest["repository"] == "https://github.com/offense-research/offense-hermes-plugin"
    assert "security" in manifest["keywords"]


def test_no_native_plugin_left_behind():
    """A package is either portable (plugin.json) or native (plugin.yaml), not both."""
    assert not (ROOT / "plugin.yaml").exists()
    assert not (ROOT / "__init__.py").exists()


def test_api_key_uses_hermes_secret_route():
    extension = load_json("plugin.json")["extensions"]["com.nousresearch.hermes"]
    schema = extension["config_schema"]["api_key"]
    assert schema["type"] == "secret"
    assert schema["env"] == "OFFENSE_API_KEY"


def test_mcp_server_policy():
    extension = load_json("plugin.json")["extensions"]["com.nousresearch.hermes"]
    server = extension["servers"]["offense"]
    assert server["trust"] == "untrusted"
    assert server["cost_unit"] == "micros"
    assert server["spend_limit"] == 5_000_000
    assert server["costs"]["offense.audit_dependencies"] == 0
    paid = server["costs"]["offense.security_call"]
    low, high = paid["credits"]
    assert 0 < low <= high
    assert "micros" in paid["note"]


def test_mcp_json_shape_and_secret_placeholder():
    config = load_json("mcp.json")
    assert set(config) == {"$schema", "mcpServers"}
    assert config["$schema"] == MCP_SCHEMA
    server = config["mcpServers"]["offense"]
    assert server["type"] == "streamable-http"
    assert server["url"].startswith("https://")
    assert server["headers"]["Authorization"] == "Bearer ${OFFENSE_API_KEY}"


def test_skill_frontmatter_and_content():
    skill_path = ROOT / "skills" / "offense" / "SKILL.md"
    text = skill_path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    frontmatter = yaml.safe_load(text.split("---", 2)[1])
    assert frontmatter["name"] == "offense"
    assert frontmatter["license"] == "Apache-2.0"
    assert frontmatter["description"]
    # Agent Skills v1: metadata must be a flat string map (nested maps are rejected).
    assert all(isinstance(value, str) for value in frontmatter["metadata"].values())
    for tool in ("offense.audit_dependencies", "offense.security_quote", "offense.security_call"):
        assert tool in text


def test_no_credentials_or_self_updater_in_package():
    banned_names = {"update.mjs", "update.js"}
    secret_re = re.compile(r"offense_sk_[0-9a-fA-F]{16,}")
    for path in package_files():
        if path.name == "LICENSE":
            continue
        assert path.name not in banned_names, f"self-updater must not ship: {path}"
        if path.suffix in {".py", ".json", ".md", ".yaml", ".yml", ".mjs", ".js"}:
            content = path.read_text(encoding="utf-8", errors="replace")
            assert not secret_re.search(content), f"looks like a literal API key: {path}"


def test_no_compiled_payloads():
    banned_suffixes = {".so", ".dll", ".dylib", ".exe", ".node", ".wasm", ".pyc", ".pyo"}
    for path in package_files():
        assert path.suffix not in banned_suffixes, f"unscannable payload: {path}"


def test_readme_documents_key_and_spend():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "OFFENSE_API_KEY" in readme
    assert "spend" in readme.lower()
    assert "app.purpleteam.sh" in readme
