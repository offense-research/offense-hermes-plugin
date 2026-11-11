---
name: security-team
description: Run an Offense security assessment from a Hermes session — connect, prepare the target, choose a sandbox or a swarm, report findings honestly, and retest fixes. Use when the user asks to test, scan, attack, pentest, or check a web app for vulnerabilities, tenant isolation, or broken authorization.
version: 1.0.0
author: Offense Research
license: Apache-2.0
metadata:
  hermes:
    tags: [Security, Testing, Swarm, Web]
    requires_toolsets: [offense]
    related_skills: []
---

# Offense security team

Offense runs prepared security workers against a staging web application and
returns independently reproduced findings. The agent drives it through the
`offense_*` tools; the user keeps credentials, payment, and authorization in
the browser.

## Safety rules

- Only test a target the user owns or is explicitly authorized to test. If
  authorization is unclear, stop and ask before registering a target.
- Never accept credentials, tokens, or session cookies in chat. The browser
  flow (`offense_status` returns setup URLs) collects them directly.
- Never test production without a separate, explicit instruction. Staging is
  the default and the supported contract.
- Never describe an assessment as complete, clean, or all tests passed. A
  finished run can have partial coverage; report coverage honestly.
- Candidate findings are not confirmed. A finding is real for reporting
  purposes only after an independent verification reproduces it.

## Workflow

1. **Check state** — call `offense_status`. It returns connection, workspace
   balance, target verification, identity count, and active work.
2. **Configure if needed** — if `code=not_configured`, give the user the
   `keys_url` from the result so they can create an Offense API key, then tell
   them to set `OFFENSE_API_KEY` for the plugin (Hermes prompts for it at
   install; the Desktop plugin settings page has a masked field). Never ask
   for the key in chat.
3. **Prepare the target** — register with `offense_register_target` (http(s)
   staging URL). Show the user `verification.url` and `verification.token`
   from the result and ask them to publish the token at that well-known path.
   Then call `offense_verify_target`. Two test identities in separate
   organizations must be added at the identities URL before launching.
4. **Choose the engine**:
   - `offense_launch_sandbox` — one focused question, a specific endpoint, a
     suspected bug, or a retest. Use `count` up to 5 for parallel hypotheses.
   - `offense_summon_swarm` — broad coverage of a staging app: auth, object
     authorization, tenant isolation, injection, uploads, business logic. Each
     member gets a different focus area and approach; duplicates merge into one
     report. Default 3 agents; 8-20 agents for a full pass when budget allows.
5. **Add the task** — pass a concrete plain-language `task`. Name the boundary
   (for example "can org A read org B's invoices") and the endpoints if known.
6. **Wait** — `offense_wait_sandbox` or `offense_wait_swarm`. A wait that
   returns `timed_out=true` is normal; call again to continue. Report progress
   to the user between waits instead of blocking silently for many minutes.
7. **Read results** — `offense_sandbox_findings` for one sandbox,
   `offense_get_swarm` for the combined report (deduplicated findings plus the
   agents that reproduced each one and a `report_url`).
8. **Verify before reporting** — `offense_verify_finding` re-runs a candidate
   in a fresh sandbox. Do this for anything important before calling it a
   vulnerability.
9. **Retest after a fix** — when the user says a fix shipped, call
   `offense_retest_finding`. The new assessment reports fixed or still
   reproducible; follow it with `offense_wait_sandbox` and
   `offense_sandbox_findings`.
10. **Stop when done or when the user asks** — `offense_stop_sandbox` or
    `offense_stop_swarm`. Unused reserved budget is refunded.

## Budgets

Budgets are micro-dollars: `1000000` = $1.00. The default is $1 per sandbox.
A swarm reserves `agents x budget_micros`, so a 10-agent swarm at the default
is $10. Check `offense_status` for balance before launching anything large, and
tell the user the reservation before a swarm larger than a few agents.

## Reporting

- Lead with the verified finding, its severity, and the exact reproduction.
- Separate verified findings from candidates and from "not tested" areas.
- Include the `report_url` so the user can read the full report and evidence.
- State limitations: identities used, coverage gaps, actions not attempted.
- Never paste session tokens, API keys, or raw credential material into chat.
