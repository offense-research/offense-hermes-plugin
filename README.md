# Offense for Hermes

Give any Hermes agent a security team. This plugin connects Hermes to
[Offense](https://github.com/offense-research/offense): the agent can **spin up
isolated security sandboxes** and **summon swarms of independent investigators**
against a verified staging target, read findings and evidence, verify
candidates, and retest fixes.

The agent never holds target credentials, a shell on a worker, or scanner
controls. It selects from registered targets and policy-bounded budgets; the
browser flow keeps credentials, authorization, and payment with the user.

- 17 tools in the `offense` toolset
- A bundled `security-team` skill with the workflow and safety rules
- A `/offense` slash command for status, sandboxes, and swarms
- Optional per-turn awareness of work already running (on by default)
- No third-party Python packages: one standard-library HTTP client

## Install

From GitHub:

```sh
hermes plugins install offense-research/offense-hermes-plugin --enable
```

Or from the plugin catalog, once listed:

```sh
hermes plugins install offense
```

From a local checkout:

```sh
git clone https://github.com/offense-research/offense-hermes-plugin ~/.hermes/plugins/offense-hermes-plugin
hermes plugins enable offense
```

Restart Hermes (or start a new session) and ask: *"check Offense status."* The
plugin appears in `hermes plugins list` as `offense`.

## Configure

The plugin needs an Offense API key:

1. Create one in the Offense dashboard under **Settings**:
   <https://app.offense.sh/app/settings>. Pick the narrowest scope preset that
   covers what the agent should do.
2. Set it for the plugin as `OFFENSE_API_KEY` — Hermes prompts for it during
   install, and the Desktop plugin settings page has a masked field. It is
   stored in the active profile through Hermes' normal credential route.

The plugin never writes or reads a key file of its own, and it never reads
another tool's credential store. `offense_status` returns the keys URL when the
key is missing. Never paste an API key into chat.

Self-hosted Offense: set the **Offense base URL** in the plugin settings (or
`OFFENSE_BASE_URL` in the environment).

## Use

```text
"Summon a swarm against our staging app and tell me if org A can read org B's data."
"Launch a focused sandbox on /api/invoices/42 — I think it's missing an ownership check."
"Verify that finding, then retest it now that the fix shipped."
"How much has this swarm spent so far? Stop it if it's over five dollars."
```

Typical flow the agent follows (the `security-team` skill spells this out):

1. `offense_status` — connection, balance, target state, active work.
2. `offense_register_target` + `offense_verify_target` — publish the
   `/.well-known/offense-verify.txt` token, then verify.
3. Add two test identities in separate organizations at the identities URL
   `offense_status` returns.
4. `offense_launch_sandbox` for a narrow question, or `offense_summon_swarm`
   for broad coverage.
5. `offense_wait_sandbox` / `offense_wait_swarm`, then
   `offense_sandbox_findings` / `offense_get_swarm`.
6. `offense_verify_finding` before calling a candidate a vulnerability;
   `offense_retest_finding` after a fix.
7. `offense_stop_sandbox` / `offense_stop_swarm` to stop and refund unused
   budget.

## Tools

| Tool | Purpose |
|---|---|
| `offense_status` | Workspace, balance, target state, active sandboxes and swarms |
| `offense_register_target` | Register or replace the staging target |
| `offense_verify_target` | Verify control via the well-known token file |
| `offense_launch_sandbox` | Spin up 1-5 isolated sandboxes with a budget and task |
| `offense_list_sandboxes` | Recent sandboxes with status and spend |
| `offense_get_sandbox` | One sandbox in detail |
| `offense_wait_sandbox` | Poll until terminal or timeout |
| `offense_sandbox_findings` | Findings with verification status |
| `offense_sandbox_evidence` | Checksummed evidence bundles |
| `offense_stop_sandbox` | Stop and refund unused budget |
| `offense_verify_finding` | Reproduce a candidate in a fresh sandbox |
| `offense_retest_finding` | Replay a finding after a fix |
| `offense_list_swarms` | Recent swarms |
| `offense_summon_swarm` | Summon independent agents with distinct focus areas |
| `offense_get_swarm` | Combined report, deduplicated findings, member assignments |
| `offense_wait_swarm` | Poll until no member is queued or running |
| `offense_stop_swarm` | Stop every active member and refund unused budget |

## Budgets

Budgets are micro-dollars: `1000000` = $1.00. The plugin defaults every launch
to $1 per sandbox. A swarm reserves `agents x budget_micros`; a 3-agent swarm
at the default reserves $3.00. Sandbox batches of up to 5 are supported.
Unused reservation is refunded on stop or completion.

Check `offense_status` for the workspace balance before launching. Spend a
user's budget only on work they asked for.

## Authorization model

Offense enforces its own boundaries; the plugin cannot widen them:

- Only the workspace's registered target can be tested, and it must pass
  control verification.
- Two test identities in separate organizations are required before launch.
- The API key's scopes bound what the agent may do.
- Workers are disposable sandboxes with job-scoped secrets, no control-plane
  access, and no access to payment.
- Findings are candidate until an independent verifier reproduces them.

Treat the target as staging. Ask before testing anything else.

## Disclosure

What a user should know before enabling this plugin:

- **Network.** It talks only to the configured Offense API
  (`https://app.offense.sh` by default, override for self-hosted).
- **Data.** Assessment tasks, the registered target URL, and (during a run)
  task instructions and findings travel to that API. The plugin does not read
  or upload the user's files or repositories.
- **Credentials.** The API key is read through Hermes'
  `agent.secret_scope.get_secret`. The plugin never reads `.env`, `auth.json`,
  an MCP client's config, or any other credential store, and it spawns no
  shell commands.
- **Spend.** Launches reserve real money on the user's Offense account; the
  default is $1 per sandbox and `agents x $1` per swarm. The plugin states the
  reservation before launching and stops/refunds on request.
- **Telemetry.** None. No usage reporting beyond the Offense API calls the
  tools make.
- **Long-running work.** Waits are bounded by their `timeout_seconds`; nothing
  runs in the background after the tool call returns.

## Configuration

Settings live under `plugins.entries.offense.settings` (the Desktop plugin
settings page renders the same fields):

```yaml
plugins:
  enabled:
    - offense
  entries:
    offense:
      settings:
        base_url: https://app.offense.sh   # self-hosted API origin
        inject_active_work: true           # short active-work note per turn
        active_work_ttl_seconds: 45        # how long that note is cached
```

Set `inject_active_work: false` to stop the `pre_llm_call` note entirely; the
agent can still call `offense_status` at any time.

## Development

The plugin has no runtime dependencies. Tests use pytest only:

```sh
uv run --with pytest python -m pytest tests -q
# or
python -m pip install pytest && python -m pytest tests -q
```

Run the tests from the repository root. `tests/pytest.ini` keeps pytest's
rootdir inside `tests/` so pytest does not collect the plugin root, which is
itself a Python package.

Admission check (requires a Hermes checkout):

```sh
hermes plugins validate /path/to/offense-hermes-plugin
```

Live read-only API contract check (invalid key, spends nothing):

```sh
python scripts/smoke_live.py
```

Layout:

```
__init__.py          register(ctx): tools, skill, command, hook
offense_client.py    standard-library HTTP client and credential resolution
offense_schemas.py   tool schemas the model sees
offense_tools.py     tool handlers and the active-work reporter
skills/security-team/SKILL.md
tests/
```

Compatibility: `requires_hermes: ">=0.19.0"`. Validated with
`hermes plugins validate` (all checks pass, security scan safe) and loaded
through the Hermes plugin manager with all 17 tools, the skill, the slash
command, and the `pre_llm_call` hook. The Offense API contract is `/api/v1` at
`https://app.offense.sh/api/openapi.json`.

## License

Apache-2.0. See [LICENSE](LICENSE).
