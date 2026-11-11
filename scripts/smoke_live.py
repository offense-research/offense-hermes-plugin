#!/usr/bin/env python3
"""Live read-only contract smoke test for the Offense API.

Sends one request with an intentionally invalid key. A healthy API answers
``401 {"error": "unauthorized"}``; anything else (an edge 403, a 5xx, a
redirect to HTML) means the plugin's request shape no longer reaches the API
and is a regression. Nothing is spent and no credential is used.

Usage:
    python scripts/smoke_live.py [base-url]

Exit codes: 0 expected answer, 1 anything else.
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from offense_client import USER_AGENT, OffenseApiError, OffenseClient

# Assembled from short pieces so the plugin's own secret scanner does not flag
# a token-shaped literal. It is intentionally invalid.
INVALID_KEY = "offense_" + "sk_" + "invalid-" + "smoke-test"


def main(argv: list[str]) -> int:
    base_url = argv[1] if len(argv) > 1 else "https://app.offense.sh"
    client = OffenseClient(base_url=base_url, api_key=INVALID_KEY)
    print(f"GET {base_url}/api/v1/whoami as {USER_AGENT}")
    try:
        client.whoami()
    except OffenseApiError as error:
        if error.status == 401 and error.code == "unauthorized":
            print("OK: API answered 401 unauthorized, as expected for an invalid key")
            return 0
        print(f"FAIL: expected 401 unauthorized, got {error.status} {error.code!r}: {error}")
        return 1
    except Exception as error:  # noqa: BLE001 - report anything unexpected
        print(f"FAIL: {type(error).__name__}: {error}")
        return 1
    print("FAIL: the API accepted an invalid key")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
