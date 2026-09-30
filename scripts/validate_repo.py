#!/usr/bin/env python3
"""Validate the APK built-in localization repository.

Checks:
1. manifests/bottom-bar.manifest.json is valid and carries 7 slots.
2. manifests/apk-builtin.manifest.json is valid, lists the known surfaces,
   names the client version, and never claims a reviewed/released status it
   cannot prove.
3. Every declared client translation source exists and matches its hash/size.
4. The client manifest contains no Assets-axis version field.
5. schema/apk-builtin.schema.json is valid JSON.

Nothing here reads a binary: the repository is metadata-only by design.
"""
from __future__ import annotations

import json
import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWN_SURFACES = {"bottom-bar-atlas", "runtime-bi", "cjk-font"}
VALID_STATUS = {"unrecorded", "unreviewed_candidate", "recorded", "reviewed"}


def load(path: Path, label: str) -> dict:
    if not path.is_file():
        print(f"ERROR: Missing {label} at {path}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: {path} invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reject_assets_axis(node: object, path: str = "<root>") -> None:
    """The Client repository must not grow a hidden Client+Assets identity."""
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in {"asset_version", "assets_version", "base_version"}:
                print(f"ERROR: Assets-axis field {path}.{key} is forbidden", file=sys.stderr)
                sys.exit(1)
            reject_assets_axis(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            reject_assets_axis(value, f"{path}[{index}]")
def validate_bottom_bar(root: Path) -> dict[str, int]:
    doc = load(root / "manifests" / "bottom-bar.manifest.json", "bottom-bar manifest")
    if doc.get("kind") != "mltd-bottom-bar-manifest":
        print(f"ERROR: unexpected bottom-bar kind {doc.get('kind')!r}", file=sys.stderr)
        sys.exit(1)

    slots = doc.get("slots", [])
    if len(slots) != 7:
        print(f"ERROR: bottom-bar slot count {len(slots)} != 7", file=sys.stderr)
        sys.exit(1)
    for slot in slots:
        for key in ("index", "ja", "zh", "provenance"):
            if key not in slot:
                print(f"ERROR: bottom-bar slot {slot.get('index')} lacks {key}", file=sys.stderr)
                sys.exit(1)

    atlas = doc.get("atlas_target", {})
    if atlas.get("slot_count") != len(slots):
        print("ERROR: atlas_target.slot_count disagrees with slots", file=sys.stderr)
        sys.exit(1)
    return {"slots": len(slots)}


def validate_builtin(root: Path) -> dict[str, int]:
    doc = load(root / "manifests" / "apk-builtin.manifest.json", "apk-builtin manifest")
    if doc.get("kind") != "mltd-apk-builtin-manifest":
        print(f"ERROR: unexpected apk-builtin kind {doc.get('kind')!r}", file=sys.stderr)
        sys.exit(1)

    surfaces = doc.get("surfaces", [])
    if not surfaces:
        print("ERROR: apk-builtin manifest lists no surfaces", file=sys.stderr)
        sys.exit(1)

    names = [s.get("name") for s in surfaces]
    unknown = [n for n in names if n not in KNOWN_SURFACES]
    if unknown:
        print(f"ERROR: unknown apk-builtin surface(s): {unknown}", file=sys.stderr)
        sys.exit(1)
    if len(set(names)) != len(names):
        print("ERROR: duplicate surface names", file=sys.stderr)
        sys.exit(1)

    if doc.get("counts", {}).get("surfaces") != len(surfaces):
        print("ERROR: counts.surfaces disagrees with surfaces", file=sys.stderr)
        sys.exit(1)

    provenance = doc.get("provenance", {})
    client_version = provenance.get("client_version")
    if not isinstance(client_version, str) or not client_version.replace(".", "").isdigit():
        print(f"ERROR: invalid client_version {client_version!r}", file=sys.stderr)
        sys.exit(1)
    if provenance.get("axis") != "client":
        print("ERROR: apk-builtin provenance must declare axis=client", file=sys.stderr)
        sys.exit(1)
    status = provenance.get("artifact_status")
    if status not in VALID_STATUS:
        print(f"ERROR: artifact_status {status!r} is not one of {sorted(VALID_STATUS)}", file=sys.stderr)
        sys.exit(1)
    if status == "unreviewed_candidate" and provenance.get("reviewed") is not False:
        print("ERROR: an unreviewed candidate must declare reviewed=false", file=sys.stderr)
        sys.exit(1)
    for surface in surfaces:
        source = surface.get("translation_source")
        if source is None:
            continue
        relative = source.get("relative_path") if isinstance(source, dict) else None
        if not isinstance(relative, str) or not relative or relative.startswith("/") or ".." in Path(relative).parts:
            print(f"ERROR: invalid translation_source path on {surface.get('name')!r}", file=sys.stderr)
            sys.exit(1)
        path = root / relative
        if not path.is_file():
            print(f"ERROR: missing translation source {relative}", file=sys.stderr)
            sys.exit(1)
        if source.get("sha256") != sha256(path):
            print(f"ERROR: translation source hash mismatch for {relative}", file=sys.stderr)
            sys.exit(1)
        if source.get("bytes") != path.stat().st_size:
            print(f"ERROR: translation source size mismatch for {relative}", file=sys.stderr)
            sys.exit(1)
    return {"surfaces": len(surfaces), "client_version": client_version}


def validate_schema(root: Path) -> None:
    schema = load(root / "schema" / "apk-builtin.schema.json", "apk-builtin schema")
    if schema.get("properties", {}).get("kind", {}).get("const") != "mltd-apk-builtin-manifest":
        print("ERROR: schema does not pin kind=mltd-apk-builtin-manifest", file=sys.stderr)
        sys.exit(1)
    if schema.get("properties", {}).get("schema_version", {}).get("const") != 2:
        print("ERROR: schema must be version 2 for the independent Client axis", file=sys.stderr)
        sys.exit(1)


def main() -> int:
    print(f"Validating APK built-in repository at: {ROOT}")
    bottom_bar = validate_bottom_bar(ROOT)
    builtin = validate_builtin(ROOT)
    reject_assets_axis(load(ROOT / "manifests" / "apk-builtin.manifest.json", "apk-builtin manifest"))
    validate_schema(ROOT)

    print("\nRepository validation SUCCESSFUL!")
    print(f"Bottom-bar slots: {bottom_bar['slots']}")
    print(f"Built-in surfaces: {builtin['surfaces']}")
    print(f"Client version: {builtin['client_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
