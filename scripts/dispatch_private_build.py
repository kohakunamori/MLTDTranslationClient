#!/usr/bin/env python3
"""CLI adapter for notifying the private APK build repository."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

try:
    from scripts.private_build import payload, recovery_payload
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from private_build import payload, recovery_payload

ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DISPATCH_ENDPOINT = "repos/kohakunamori/MLTDModifiedAPK/dispatches"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--require-ready", action="store_true")
    parser.add_argument("--recover-unsupported", action="store_true")
    args = parser.parse_args()
    event = (
        recovery_payload(ROOT, args.repository, args.commit)
        if args.recover_unsupported
        else payload(ROOT, args.repository, args.commit)
    )
    if event is None:
        return 1 if args.require_ready else 0
    subprocess.run(
        ["gh", "api", "--method", "POST", PRIVATE_DISPATCH_ENDPOINT, "--input", "-"],
        input=json.dumps(event), text=True, check=True,
    )
    print(f"Dispatched Client {args.commit} ({event['client_payload']['client_version']}).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
