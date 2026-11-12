#!/usr/bin/env python3
"""Live read-only smoke test for the Offense MCP endpoint.

Checks the two things the plugin depends on:

1. the endpoint speaks MCP and identifies itself as ``offense``;
2. the free ``offense.audit_dependencies`` tool is offered (this works
   without an API key).

Sends no credentials, starts no job and spends nothing.

Usage:
    python scripts/smoke_mcp.py [mcp-url]

Exit codes: 0 expected answers, 1 anything else.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

DEFAULT_URL = "https://app.purpleteam.sh/mcp"
USER_AGENT = "offense-hermes-plugin-smoke/0.3.0"


def call(url: str, payload: dict) -> dict:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "user-agent": USER_AGENT,
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        raw = response.read().decode("utf-8", "replace")
    # Streamable HTTP may answer as JSON or as a single SSE data frame.
    for line in raw.splitlines():
        if line.startswith("data:"):
            raw = line[5:].strip()
            break
    return json.loads(raw)


def main(argv: list[str]) -> int:
    url = argv[1] if len(argv) > 1 else DEFAULT_URL
    print(f"POST {url}")
    try:
        initialized = call(
            url,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "offense-hermes-plugin", "version": "0.3.0"},
                },
            },
        )
        server = (initialized.get("result") or {}).get("serverInfo") or {}
        if server.get("name") != "offense":
            print(f"FAIL: unexpected server identity: {server!r}")
            return 1

        listed = call(url, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        tools = [tool.get("name") for tool in (listed.get("result") or {}).get("tools") or []]
        if "offense.audit_dependencies" not in tools:
            print(f"FAIL: free audit tool missing; got {tools!r}")
            return 1
        print(f"OK: server {server.get('name')} {server.get('version', '')}, tools={tools}")
        return 0
    except urllib.error.HTTPError as error:
        print(f"FAIL: HTTP {error.code}: {error.read()[:200]!r}")
        return 1
    except Exception as error:  # noqa: BLE001 - report anything unexpected
        print(f"FAIL: {type(error).__name__}: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
