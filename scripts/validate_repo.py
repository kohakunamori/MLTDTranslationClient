#!/usr/bin/env python3
"""CLI entrypoint for validating the APK built-in localization repository."""
from __future__ import annotations

import sys
from pathlib import Path

try:
    from scripts.repository_validation import RepositoryValidator, ValidationError
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from repository_validation import RepositoryValidator, ValidationError

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    print(f"Validating APK built-in repository at: {ROOT}")
    try:
        summary = RepositoryValidator(ROOT).validate()
    except ValidationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print("\nRepository validation SUCCESSFUL!")
    print(f"Bottom-bar slots: {summary['bottom_bar']['slots']}")
    print(f"Built-in surfaces: {summary['builtin']['surfaces']}")
    print(f"Client version: {summary['builtin']['client_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
