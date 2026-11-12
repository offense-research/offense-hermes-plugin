# Offense for Hermes

Security tools your Hermes agent can discover, call and verify. This plugin
connects Hermes to the official [Offense](https://github.com/offense-research/offense)
MCP server: **free npm/pnpm advisory audits** and **prepaid hosted security
tools** (source, infrastructure, target, TLS, API), with a quote and an
explicit approval before any paid call.

The agent keeps source review, edits, tests and verification. Offense returns
structured security evidence; it does not run your app, edit your code or
confirm exploitability.

- Portable Hermes package: no Python, no vendored upstream code, nothing to
  build
- Official MCP tools, exposed as `mcp__offense__*`
- Paid calls are gated twice: the server's `untrusted` trust tier asks before
  every write-capable call, and a per-chat spend limit is declared
- The API key goes through Hermes' secret route (`OFFENSE_API_KEY`), never a
  key file inside the package
- Free dependency audit needs no account

## Install

From GitHub:

```sh
hermes plugins install offense-research/offense-hermes-plugin --enable
```

Or from the plugin catalog, once listed:

```sh
hermes plugins install offense
```

Restart Hermes (or start a new session), then ask *"what Offense tools do you
have?"* or run `/offense`.

For the full guided assessment workflow, install the upstream skill as well:

```sh
hermes skills install offense-research/offense/.agents/skills/scanning-with-offense
```

## Configure

The free dependency audit works immediately. Hosted tools need an Offense API
key with prepaid balance:

1. Create a key at <https://app.purpleteam.sh/account>.
2. Set it in Hermes → **Settings → Plugins → Offense** (masked field), or add
   `OFFENSE_API_KEY=...` to the active profile's `.env`. Hermes stores it
   through its normal credential route; the plugin never writes or reads a key
   file of its own.

The hosted origin is currently `https://app.purpleteam.sh` and moves to
`https://offense.sh`. To self-host, override the server with a same-name
`mcp_servers` entry in `config.yaml`:

```yaml
mcp_servers:
  offense:
    url: https://offense.example.com/mcp
    headers:
      Authorization: "Bearer ${OFFENSE_API_KEY}"
```

## Use

```text
"Audit this project's dependencies and explain anything critical."
"Quote and run the source scan on these files; do not exceed $0.50."
"Check the TLS configuration of our staging origin."
"What does Offense say about our balance and available tools?"
```

Typical flow (the bundled skill and the upstream guided skill spell this out):

1. `offense.security_tools` — what is available, coverage, prices.
2. `offense.security_quote` — maximum price for the selected tool and input
   size. A quote does not charge.
3. The user approves the tool, input and maximum charge.
4. `offense.security_call` — one job with the reviewed `maxChargeMicros` and a
   stable idempotency key.
5. `offense.security_result` — status, findings and the settled charge.

For dependencies, the agent prepares sanitized metadata locally with the
official helper (`node offense.mjs metadata PROJECT`) and passes it to
`offense.audit_dependencies`. Raw lockfiles, `.env` files and credentials are
never sent.

## MCP tools

| Tool | Purpose |
| --- | --- |
| `offense.account` | Balance, billing and account links |
| `offense.security_tools` | Tool catalog, coverage and per-tool prices |
| `offense.security_quote` | Maximum price for one call; does not charge |
| `offense.security_call` | Submit one paid job (reviewed quote + idempotency key) |
| `offense.security_result` | Job status, findings and settled charge |
| `offense.audit_dependencies` | Free npm/pnpm advisory audit of sanitized lockfile content |
| `offense.topup` | Create a Whop top-up link; the user completes payment |

## Spend safety

- Every write-capable call asks first (`trust: untrusted`).
- The package declares a per-chat spend limit of 5,000,000 micros ($5.00) and
  per-call cost range $0.05–$1.00 in the same unit; a call past the limit asks
  even if the server is trusted.
- The server itself validates a previously reviewed `maxChargeMicros` and
  settles only on completion; failed or partial jobs release their
  reservation.
- The agent is told a quote is not spending approval, and never to buy credit
  automatically. `offense.topup` only creates a checkout link.

## Disclosure

- **Network:** talks only to the configured Offense origin
  (`https://app.purpleteam.sh` by default) over HTTPS.
- **Data:** dependency names, exact versions and relative paths are sent for
  the free audit; selected source, artifacts, targets or infrastructure for
  hosted tools. Nothing is uploaded before a reviewed quote and an explicit
  run. The plugin reads no local files itself.
- **Credentials:** `OFFENSE_API_KEY` is read through Hermes'
  `agent.secret_scope`; the package contains no key material, spawns no shell
  commands and has no self-updater.
- **Spend:** hosted tools consume prepaid Offense credit on the user's account;
  the agent must state the maximum charge before calling.
- **Telemetry:** none.

## Development

```sh
uv run --with pytest --with pyyaml python -m pytest tests -q
python scripts/smoke_mcp.py        # live read-only check, no credentials
hermes plugins validate .          # admission check, needs a Hermes checkout
```

Layout:

```
plugin.json          portable Agent Plugins v1 manifest + Hermes trust/cost policy
mcp.json             the official Offense MCP server and the ${OFFENSE_API_KEY} header
skills/offense/      bundled skill (original, Apache-2.0)
scripts/smoke_mcp.py live endpoint check
tests/               package contract tests
```

Compatibility: tested on Hermes v0.23.1 (portable package, secret
interpolation, trust/cost policy, MCP connection). The catalog entry declares
`requires_hermes: ">=0.23.1"`. Upstream Offense is the source of truth for the
MCP tool contracts; this plugin pins the endpoint and the policy, not a copy of
the tools.

## License

Apache-2.0. See [LICENSE](LICENSE).
