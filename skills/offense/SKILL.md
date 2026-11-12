---
name: offense
description: Use Offense security tools from Hermes — free npm/pnpm advisory audits and prepaid hosted security tools (source, infrastructure, target, TLS, API) through the official Offense MCP server, with a quote and explicit approval before any paid call.
license: Apache-2.0
metadata:
  author: Offense Research
  version: "0.3.0"
  category: security
  tags: security, dependencies, mcp, offense
---

# Offense

Offense supplies security evidence; the agent keeps source review, edits, tests
and verification. This plugin connects Hermes to the official Offense MCP
server. The server's tools are exposed here as `mcp__offense__<tool>` (for
example `offense.security_quote` is `mcp__offense__offense_security_quote`).

For the full guided assessment workflow, install the upstream skill once:
`hermes skills install offense-research/offense/.agents/skills/scanning-with-offense`.

## Safety rules

- Test only repositories and targets the user owns or is authorized to test.
- Audit-only requests do not authorize fixes, purchases or publication.
- A quote is not spending approval. Before `offense.security_call`, confirm the
  selected inputs, any source upload or active testing, and the maximum USD
  charge with the user. Never buy credit automatically.
- Never ask for or print API keys, connector tokens or credentials. The API key
  lives in Hermes' secret store; the model only sees tool results.
- Partial, failed, queued or unsupported checks are not clean passes. Advisory
  matches and scanner signals are evidence to review, not confirmed
  vulnerabilities. Report coverage gaps and the actual settled charge.
- Evidence and source can contain credentials. Redact values locally before
  quoting excerpts into tool output or chat.

## Tools

| Server tool | Use |
| --- | --- |
| `offense.account` | Balance, billing and account links. Read-only. |
| `offense.security_tools` | Available hosted tools, coverage and per-tool prices. Read-only. |
| `offense.security_quote` | Maximum price for one call. Does not charge. |
| `offense.security_call` | Submit one paid job. Needs a reviewed quote (`maxChargeMicros`) and an idempotency key. |
| `offense.security_result` | Job status, findings and settled charge. |
| `offense.audit_dependencies` | Free npm/pnpm advisory audit of sanitized lockfile content. No account needed. |
| `offense.topup` | Create a Whop top-up link. The user completes payment; the link does not grant credit. |

## Free dependency audit

1. Identify the exact project and its supported lockfiles (npm v2/v3, pnpm
   v6/v9). Do not install target dependencies or generate lockfiles.
2. Prepare sanitized metadata locally with the official helper (Node 20+):
   `node offense.mjs metadata /absolute/path/to/project`. Reuse a reviewed
   Offense checkout (`public/skills/offense/scripts/offense.mjs`) or download
   the helper from the official origin (`/skills/offense/scripts/offense.mjs`
   on the API host). Never send raw lockfiles, `.env` files or credentials.
3. Pass the helper's JSON object as the arguments to
   `offense.audit_dependencies` (`{"files": [...]}`). Package names and exact
   versions still leave the machine; say so before sending.
4. Keep `audit.json` / `remediation.md` outside the checkout. Preserve coverage
   warnings, unsupported inputs and planning blockers; they are not a pass.

## Paid hosted tool

1. `offense.security_tools` to see what is available and its price.
2. `offense.security_quote` with the tool and the input size
   (`inputBytes`, `fileCount`) for a maximum price. A quote does not charge.
3. Tell the user the tool, the input or target, any upload, and the maximum USD
   charge. Stop and ask if no budget was approved.
4. `offense.security_call` with the tool's input contract, the reviewed
   `maxChargeMicros`, and one stable idempotency key per job. Reuse the exact
   key and input if submission is uncertain instead of creating a second job.
5. `offense.security_result` until the job settles. Report the actual charge,
   findings and coverage. A failed or partial job releases its reservation.

Target-based tools (`nuclei`, `sslyze`, `schemathesis`, `zap-api`, `katana`,
`httpx`) need workspace-bound target ownership verification first; the server
returns the challenge and verification calls. Never bypass it. Active testing
needs the explicit confirmation the server asks for.

## Setup

- The free audit works without an account. Hosted tools need an Offense API
  key with prepaid balance.
- Create a key at <https://app.purpleteam.sh/account>, then set it in Hermes
  under Settings → Plugins → Offense (masked field) or as `OFFENSE_API_KEY` in
  the active profile's `.env`. The plugin never writes or reads key files of
  its own.
- The hosted origin is currently `https://app.purpleteam.sh` and moves to
  `https://offense.sh`. Override the MCP URL with a same-name `mcp_servers`
  entry in `config.yaml` if you self-host.
