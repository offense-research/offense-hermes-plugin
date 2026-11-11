"""Tool schemas the model sees.

Descriptions are written for a model that has not used Offense before: they
say when to use a tool, what it costs, and which other tool to call next.
"""

from __future__ import annotations

TOOLSET = "offense"

BUDGET_NOTE = (
    "Budgets are micro-dollars: 1,000,000 = $1.00. The amount is reserved when "
    "work starts and unused budget is refunded when it stops."
)

STATUS = {
    "name": "offense_status",
    "description": (
        "Show the Offense connection: workspace, balance, key scopes, the "
        "registered target and its verification state, and active sandboxes "
        "and swarms. Call this first to decide whether the user needs to "
        "connect, register a target, or approve identities."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

LOGIN = {
    "name": "offense_login",
    "description": (
        "Connect Hermes to Offense with a device login. Without finish, start "
        "the flow and show the user the returned verification URL and code. "
        "After the user approves it in the browser, call again with "
        "finish=true to save the API key. Never ask the user to paste a key "
        "into chat."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "finish": {
                "type": "boolean",
                "description": "True to poll for an already-started login.",
            },
            "timeout_seconds": {
                "type": "integer",
                "description": "How long to wait for approval when finishing (default 45, max 300).",
            },
        },
        "required": [],
    },
}

LOGOUT = {
    "name": "offense_logout",
    "description": "Remove the locally stored Offense API key and pending login.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

REGISTER_TARGET = {
    "name": "offense_register_target",
    "description": (
        "Register or replace the staging application Offense may test. Only a "
        "target the user owns or is authorized to test. Registration is not "
        "authorization: it must be verified next with offense_verify_target, "
        "and two test identities in separate organizations must be added in "
        "the browser before any sandbox can start."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Base URL of the staging application, e.g. https://staging.example.com",
            },
            "project": {
                "type": "string",
                "description": "Optional project label for reports.",
            },
        },
        "required": ["target"],
    },
}

VERIFY_TARGET = {
    "name": "offense_verify_target",
    "description": (
        "Verify control of the registered target by fetching its "
        "/.well-known/offense-verify.txt file. Show the user the exact URL and "
        "token from offense_register_target first; verification fails until "
        "that file exists."
    ),
    "parameters": {"type": "object", "properties": {}, "required": []},
}

LAUNCH_SANDBOX = {
    "name": "offense_launch_sandbox",
    "description": (
        "Spin up one or more isolated security sandboxes against the verified "
        "target. Each sandbox is an independent investigator with its own "
        "browser, tools, and budget. Use one sandbox for a focused question "
        "(for example a suspected BOLA on an endpoint) or a retest; use "
        "offense_summon_swarm for broad coverage. Returns sandbox IDs "
        "immediately; follow with offense_wait_sandbox and "
        "offense_sandbox_findings. " + BUDGET_NOTE
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "What to investigate, in plain language. Be specific about the boundary and endpoints.",
            },
            "budget_micros": {
                "type": "integer",
                "description": "Budget per sandbox in micro-dollars (default 1000000 = $1.00).",
            },
            "count": {
                "type": "integer",
                "description": "Number of sandboxes, 1-5 (default 1).",
            },
            "model": {
                "type": "string",
                "description": "Optional Offense model id; omit for the workspace default.",
            },
            "idempotency_key": {
                "type": "string",
                "description": "Optional key so a retried call does not launch twice.",
            },
        },
        "required": [],
    },
}

LIST_SANDBOXES = {
    "name": "offense_list_sandboxes",
    "description": "List recent sandboxes with status, spend, and swarm membership.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum sandboxes to return (default 10, max 50).",
            }
        },
        "required": [],
    },
}

GET_SANDBOX = {
    "name": "offense_get_sandbox",
    "description": "Get one sandbox: status, spend, budget, model, summary, timestamps.",
    "parameters": {
        "type": "object",
        "properties": {
            "sandbox_id": {"type": "string", "description": "Sandbox id."}
        },
        "required": ["sandbox_id"],
    },
}

WAIT_SANDBOX = {
    "name": "offense_wait_sandbox",
    "description": (
        "Block until a sandbox reaches a terminal state or the timeout passes. "
        "Returns the last known state and timed_out=true when still running. "
        "Long investigations can exceed one wait; call again to continue."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sandbox_id": {"type": "string", "description": "Sandbox id."},
            "timeout_seconds": {
                "type": "integer",
                "description": "Maximum seconds to wait (default 120, max 600).",
            },
            "poll_seconds": {
                "type": "integer",
                "description": "Seconds between status checks (default 5).",
            },
        },
        "required": ["sandbox_id"],
    },
}

SANDBOX_FINDINGS = {
    "name": "offense_sandbox_findings",
    "description": (
        "Read normalized findings for a sandbox. Findings are candidate or "
        "verified; never describe a candidate as confirmed. Evidence is "
        "redacted and may be partial."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sandbox_id": {"type": "string", "description": "Sandbox id."}
        },
        "required": ["sandbox_id"],
    },
}

SANDBOX_EVIDENCE = {
    "name": "offense_sandbox_evidence",
    "description": (
        "List checksummed evidence bundles for a sandbox, including manifests "
        "and artifact sizes. Use offense_sandbox_findings for the finding text."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sandbox_id": {"type": "string", "description": "Sandbox id."}
        },
        "required": ["sandbox_id"],
    },
}

STOP_SANDBOX = {
    "name": "offense_stop_sandbox",
    "description": (
        "Stop a sandbox and release its resources. Unused reserved budget is "
        "refunded. Safe to call more than once."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sandbox_id": {"type": "string", "description": "Sandbox id."}
        },
        "required": ["sandbox_id"],
    },
}

VERIFY_FINDING = {
    "name": "offense_verify_finding",
    "description": (
        "Re-run a candidate finding in a fresh sandbox so an independent "
        "session reproduces it. Verification can spend budget. Use it before "
        "reporting a candidate as a real vulnerability."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sandbox_id": {"type": "string", "description": "Sandbox that produced the finding."},
            "finding_id": {"type": "string", "description": "Finding id."},
        },
        "required": ["sandbox_id", "finding_id"],
    },
}

RETEST_FINDING = {
    "name": "offense_retest_finding",
    "description": (
        "Replay a retained finding against the current deployment after the "
        "user says a fix shipped. Returns the new assessment, which reports "
        "fixed or still reproducible. Retesting can spend budget."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "sandbox_id": {"type": "string", "description": "Sandbox that produced the finding."},
            "finding_id": {"type": "string", "description": "Finding id."},
        },
        "required": ["sandbox_id", "finding_id"],
    },
}

LIST_SWARMS = {
    "name": "offense_list_swarms",
    "description": "List recent swarms with member counts, spend, and finding counts.",
    "parameters": {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum swarms to return (default 10, max 50).",
            }
        },
        "required": [],
    },
}

SUMMON_SWARM = {
    "name": "offense_summon_swarm",
    "description": (
        "Summon a swarm of independent security agents against the verified "
        "target. Offense gives each member a different focus area (auth, "
        "object authorization, tenant isolation, injection, and so on) and a "
        "different approach, then merges duplicate findings into one report. "
        "Use this for a broad assessment of a staging app; use "
        "offense_launch_sandbox for a narrow question. Returns immediately "
        "with a swarm id, member sandboxes, and a report URL. The budget is "
        "per agent, so total reservation is agents x budget_micros. "
        + BUDGET_NOTE
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "agents": {
                "type": "integer",
                "description": "Number of swarm members, minimum 2 (default 3).",
            },
            "budget_micros": {
                "type": "integer",
                "description": "Budget per agent in micro-dollars (default 1000000 = $1.00 each).",
            },
            "task": {
                "type": "string",
                "description": "Operator task shared by every member; each member adds its own focus.",
            },
            "model": {
                "type": "string",
                "description": "Optional Offense model id; omit for the workspace default.",
            },
            "idempotency_key": {
                "type": "string",
                "description": "Optional key so a retried call does not summon twice.",
            },
        },
        "required": [],
    },
}

GET_SWARM = {
    "name": "offense_get_swarm",
    "description": (
        "Get a swarm: combined status, per-member assignments and states, "
        "deduplicated findings with the agents that reproduced them, spend, "
        "and the report URL."
    ),
    "parameters": {
        "type": "object",
        "properties": {"swarm_id": {"type": "string", "description": "Swarm id."}},
        "required": ["swarm_id"],
    },
}

WAIT_SWARM = {
    "name": "offense_wait_swarm",
    "description": (
        "Block until a swarm has no queued or running members, or the timeout "
        "passes. Swarms are slower than single sandboxes; a first wait of "
        "300-600 seconds is normal. Returns timed_out=true when work remains."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "swarm_id": {"type": "string", "description": "Swarm id."},
            "timeout_seconds": {
                "type": "integer",
                "description": "Maximum seconds to wait (default 300, max 3600).",
            },
            "poll_seconds": {
                "type": "integer",
                "description": "Seconds between status checks (default 10).",
            },
        },
        "required": ["swarm_id"],
    },
}

STOP_SWARM = {
    "name": "offense_stop_swarm",
    "description": (
        "Stop every active member of a swarm and release their resources. "
        "Unused budget is refunded. Safe to call more than once."
    ),
    "parameters": {
        "type": "object",
        "properties": {"swarm_id": {"type": "string", "description": "Swarm id."}},
        "required": ["swarm_id"],
    },
}

ALL = [
    STATUS,
    LOGIN,
    LOGOUT,
    REGISTER_TARGET,
    VERIFY_TARGET,
    LAUNCH_SANDBOX,
    LIST_SANDBOXES,
    GET_SANDBOX,
    WAIT_SANDBOX,
    SANDBOX_FINDINGS,
    SANDBOX_EVIDENCE,
    STOP_SANDBOX,
    VERIFY_FINDING,
    RETEST_FINDING,
    LIST_SWARMS,
    SUMMON_SWARM,
    GET_SWARM,
    WAIT_SWARM,
    STOP_SWARM,
]
