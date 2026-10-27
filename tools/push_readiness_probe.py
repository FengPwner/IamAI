#!/usr/bin/env python3
"""CLI: push_readiness_probe — pre-flight check before git push.

Usage:
    python3 tools/push_readiness_probe.py
    python3 tools/push_readiness_probe.py --json
    python3 tools/push_readiness_probe.py --key ~/.ssh/id_rsa
    python3 tools/push_readiness_probe.py --skip-network   # offline check only

Exit codes:
    0  ready — all checks passed
    1  not ready — at least one check failed
    2  usage error
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from iamai.push_readiness_probe import probe  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="pre-flight check: is git push likely to succeed?",
    )
    parser.add_argument(
        "--key", default="~/.ssh/id_ed25519",
        help="path to SSH private key (default: ~/.ssh/id_ed25519)",
    )
    parser.add_argument(
        "--skip-agent", action="store_true",
        help="skip ssh-agent check",
    )
    parser.add_argument(
        "--skip-network", action="store_true",
        help="skip github auth test (offline mode)",
    )
    parser.add_argument(
        "--timeout", type=int, default=10,
        help="seconds for github auth timeout (default: 10)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="output machine-readable JSON",
    )
    args = parser.parse_args()

    result = probe(
        key_path=args.key,
        skip_agent=args.skip_agent,
        skip_network=args.skip_network,
        network_timeout=args.timeout,
    )

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        status = "READY" if result["ready"] else "NOT READY"
        print(f"push readiness: {status}")
        print()
        for check in result["checks"]:
            icon = {"pass": "✓", "fail": "✗", "skip": "○"}.get(
                check["verdict"], "?"
            )
            print(f"  {icon} {check['name']}: {check['detail']}")
        print()
        print(f"diagnosis: {result['diagnosis']}")

    return 0 if result["ready"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
