#!/usr/bin/env python3
"""Allowlisted Dev Hub deploy runner stub.

Invoked only with an exact argv contract. Refuses arbitrary shell. Live
execution is intentionally non-operational in this control-plane package;
operators use a separately installed runner under /srv/devhub/runners/.
"""
from __future__ import annotations

import argparse
import sys


ALLOWED_VERBS = frozenset(
    {
        "preflight",
        "backup",
        "deploy_code",
        "upgrade_modules",
        "healthcheck",
        "smoke",
        "rollback_code",
        "restore_db",
        "reconcile_status",
        "emergency_stop",
    }
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="devhub_deploy_runner")
    parser.add_argument("--verb", required=True, choices=sorted(ALLOWED_VERBS))
    parser.add_argument("--merge-sha", required=True)
    parser.add_argument("--database", required=True)
    parser.add_argument("--modules", required=True, help="comma-separated allowlist")
    parser.add_argument("--lease-token", required=True)
    parser.add_argument("--simulate", action="store_true")
    args = parser.parse_args(argv)

    if not args.simulate:
        print(
            "refusing live execution: install the operator runner under "
            "/srv/devhub/runners/ and pass --simulate only for control-plane tests",
            file=sys.stderr,
        )
        return 2

    print(
        "simulate ok verb=%s sha=%s db=%s modules=%s lease=%s"
        % (args.verb, args.merge_sha, args.database, args.modules, args.lease_token)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
