# Changelog

## 0.3.0

- Adapted to the current Offense product. The old sandbox/swarm REST API no
  longer exists in `offense` main; this release replaces the native Python
  tools with a portable Hermes package that connects the official Offense MCP
  server.
- `mcp.json` wires `https://app.purpleteam.sh/mcp` with
  `Authorization: Bearer ${OFFENSE_API_KEY}` (profile-scoped secret
  interpolation).
- Paid calls are gated: `trust: untrusted`, a cost table for
  `offense.security_call` ($0.05–$1.00 per reviewed quote) and a $5.00 per-chat
  spend limit.
- Bundled skill rewritten for the MCP tools: free dependency audit, quote →
  approval → call → result, target ownership, coverage honesty.
- Removed the Python client, schemas, handlers, native manifest and the
  device-login/key-file code.
- Validated with `hermes plugins validate` on v0.23.1 (portable manifest,
  trust, costs, security scan safe) and a live MCP smoke check.

## 0.2.1

- Send an explicit `User-Agent`. The production edge answers urllib's default
  agent with 403, so the plugin could not reach the API.
- Added `scripts/smoke_live.py`, a read-only live contract check.

## 0.2.0

- Credentials moved to Hermes' secret route: `OFFENSE_API_KEY` declared in
  `plugin.yaml`, read with `agent.secret_scope.get_secret`. No key file, no
  MCP-config read, device-login tools removed.
- Added `requires_hermes` and `config_schema`; passed catalog validation.

## 0.1.0

- First release: sandbox and swarm tools for the Offense security-team MVP.
