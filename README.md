# Offense for Hermes

Give any Hermes agent a security team. This plugin connects Hermes to
[Offense](https://github.com/offense-research/offense): the agent can **spin up
isolated security sandboxes** and **summon swarms of independent investigators**
against a verified staging target, read findings and evidence, verify
candidates, and retest fixes.

The agent never holds target credentials, a shell on a worker, or scanner
controls. It selects from registered targets and policy-bounded budgets; the
browser flow keeps credentials, authorization, and payment with the user.

- 19 tools in the `offense` toolset
- A bundled `security-team` skill with the workflow and safety rules
- A `/offense` slash command for status, sandboxes, and swarms
- Optional per-turn awareness of work already running (on by default)
- No third-party Python packages: one standard-library HTTP client

## Install

From GitHub:

```sh
hermes plugins install offense-research/offense-hermes-plugin --enable
```

From a local checkout:

```sh
git clone https://github.com/offense-research/offense-hermes-plugin ~/.hermes/plugins/offense-hermes-plugin
hermes plugins enable offense
```

Restart Hermes (or start a new session) and ask: *"connect Offense and check
its status."* The plugin appears in `hermes plugins list` as `offense`.

## Connect

The agent calls `offense_login`, shows you a verification URL and code, and you
approve it in the browser. The API key is written to
`~/.config/offense/hermes.json` with mode `0600`.

Already connected an Offense MCP client? The plugin reads the key from
`~/.config/offense/mcp.json` too, so you do not have to approve twice. It never
writes to that file.

Environment overrides (useful for self-hosted Offense):

| Variable | Meaning |
|---|---|
| `OFFENSE_API_KEY` | Use this key instead of the stored one |
| `OFFENSE_BASE_URL` | API origin (default `https://app.offense.sh`) |
| `OFFENSE_CONFIG` | Exact config file to read and write |
| `OFFENSE_CONFIG_DIR` | Config directory (default `~/.config/offense`) |

Never ask the user to paste an API key into chat.

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
| `offense_login` | Start or finish a device login |
| `offense_logout` | Remove the local API key |
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

## Configuration

Plugin settings live under `plugins.entries.offense.settings`:

```yaml
plugins:
  enabled:
    - offense
  entries:
    offense:
      settings:
        client_name: Hermes          # name shown in the Offense device list
        inject_active_work: true     # add a short active-work note to each turn
        active_work_ttl_seconds: 45  # how long that note is cached
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

Layout:

```
__init__.py          register(ctx): tools, skill, command, hook
offense_client.py    standard-library HTTP client and device login
offense_schemas.py   tool schemas the model sees
offense_tools.py     tool handlers and the active-work reporter
skills/security-team/SKILL.md
tests/
```

Compatibility: validated against Hermes `0.19.0` — all 19 tools, the skill,
the slash command, and the `pre_llm_call` hook load through the real plugin
manager. The Offense API contract is `/api/v1` at
`https://app.offense.sh/api/openapi.json`.

## License

Apache-2.0. See [LICENSE](LICENSE).
