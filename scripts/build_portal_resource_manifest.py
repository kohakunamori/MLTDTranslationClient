#!/usr/bin/env python3
"""CLI adapter for building the immutable Client portal summary."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

try:
    from scripts.portal_manifest import PortalManifestBuilder
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from portal_manifest import PortalManifestBuilder

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("manifests/portal-resource-manifest.json"))
    args = parser.parse_args()
    target, unchanged, output = PortalManifestBuilder(ROOT).write(args.output)
    if unchanged:
        print(json.dumps({"output": str(target), "unchanged": True}))
    else:
        print(json.dumps({
            "output": str(target),
            "client_version": output["release"]["client_version"],
            "total": output["totals"]["total"],
            "translated": output["totals"]["translated"],
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
