#!/usr/bin/env python3
"""CLI adapter for comparing the bytes delivered into the built APK."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

try:  # Keep Git-tree paths shared with the rest of the repository tooling.
    from scripts.artifact_inputs import decide, write_github_output
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from artifact_inputs import decide, write_github_output

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--before", default=os.environ.get("BEFORE_SHA", ""),
                        help="the commit this push supersedes (github.event.before)")
    parser.add_argument("--after", default=os.environ.get("AFTER_SHA", "HEAD"),
                        help="the pushed commit (github.sha)")
    parser.add_argument("--github-output", action="store_true",
                        help="append dispatch/reason to $GITHUB_OUTPUT")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()

    try:
        report = decide(args.root, args.before, args.after)
    except Exception as exc:  # never turn an unreadable input into a skip
        report = {"changed": True, "reason": "decision_failed", "detail": str(exc),
                  "changed_paths": []}

    if args.github_output:
        target = os.environ.get("GITHUB_OUTPUT", "")
        if target:
            with open(target, "a", encoding="utf-8") as stream:
                write_github_output(report, stream)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"dispatch={report['changed']} reason={report['reason']}")
        if report.get("changed_paths"):
            print("changed artifact inputs: " + ", ".join(report["changed_paths"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
