# Changelog

## 0.2.1

- Send an explicit `User-Agent`. The production edge answers urllib's default
  agent with 403, so the plugin could not reach the API.
- Added `scripts/smoke_live.py`, a read-only live contract check that an
  invalid key gets `401 unauthorized` from the real API.

## 0.2.0

- Credentials now go through Hermes: `OFFENSE_API_KEY` is declared in
  `plugin.yaml`, prompted at install, and read with
  `agent.secret_scope.get_secret`. The plugin no longer writes a key file or
  reads an MCP client's config.
- Removed the device-login tools; create an API key in the Offense dashboard
  and set it for the plugin.
- Added `requires_hermes`, a `config_schema` (`base_url`,
  `inject_active_work`, `active_work_ttl_seconds`), and disclosure notes.
- Passes `hermes plugins validate` on Hermes v0.23.1 (all checks, security
  scan safe).

## 0.1.0

- First release: `offense` toolset for Hermes.
- Device login, target registration and verification, sandbox launch and
  polling, swarm summon and polling, findings, evidence, verify, retest, stop.
- Bundled `security-team` skill and `/offense` slash command.
- `pre_llm_call` active-work summary, cached and config-gated.
