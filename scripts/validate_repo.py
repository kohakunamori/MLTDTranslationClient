#!/usr/bin/env python3
"""Validate the APK built-in localization repository.

Checks:
1. manifests/bottom-bar.manifest.json is valid and carries 7 slots.
2. manifests/apk-builtin.manifest.json is valid, lists the known surfaces, and
   names the client version.
3. Every declared client translation source exists and matches its hash/size.
4. The client manifest contains no Assets-axis version field.
5. schema/apk-builtin.schema.json is valid JSON.
6. Optional bottom-bar visual sources are real PNGs with the declared geometry,
   hash, and byte count.
"""
from __future__ import annotations

import json
import hashlib
import sys
import struct
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KNOWN_SURFACES = {"bottom-bar-atlas", "runtime-bi", "cjk-font"}


def load(path: Path, label: str) -> dict:
    if not path.is_file():
        print(f"ERROR: Missing {label} at {path}", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERROR: {path} invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)


def canonical_bytes(path: Path) -> bytes:
    """Hash text sources as Git stores them, regardless of local checkout EOLs."""
    data = path.read_bytes()
    if path.suffix.lower() in {".json", ".md", ".py", ".txt"}:
        return data.replace(b"\r\n", b"\n")
    return data


def sha256(path: Path) -> str:
    return hashlib.sha256(canonical_bytes(path)).hexdigest()


def png_size(path: Path) -> tuple[int, int]:
    raw = path.read_bytes()
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise ValueError("not a PNG with an IHDR header")
    return struct.unpack(">II", raw[16:24])


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
    visuals = doc.get("visual_assets")
    if visuals is not None:
        canvas = visuals.get("canvas_size")
        segments = visuals.get("segment_x")
        if (not isinstance(canvas, list) or len(canvas) != 2
                or any(isinstance(part, bool) or int(part) <= 0 for part in canvas)):
            print("ERROR: bottom-bar visual_assets.canvas_size is invalid", file=sys.stderr)
            sys.exit(1)
        if (not isinstance(segments, list) or len(segments) != len(slots) + 1
                or [int(part) for part in segments] != sorted(set(int(part) for part in segments))
                or int(segments[0]) != 0 or int(segments[-1]) != int(canvas[0])):
            print("ERROR: bottom-bar visual_assets.segment_x is invalid", file=sys.stderr)
            sys.exit(1)
        for state in ("off", "on"):
            source = visuals.get(state)
            if not isinstance(source, dict):
                print(f"ERROR: bottom-bar visual_assets.{state} is missing", file=sys.stderr)
                sys.exit(1)
            relative = source.get("path")
            path = root / str(relative or "")
            if (not isinstance(relative, str) or not relative
                    or Path(relative).is_absolute() or ".." in Path(relative).parts
                    or not path.is_file()):
                print(f"ERROR: missing bottom-bar visual source {relative}", file=sys.stderr)
                sys.exit(1)
            if source.get("sha256") != sha256(path) or source.get("bytes") != path.stat().st_size:
                print(f"ERROR: bottom-bar visual source hash/size mismatch for {relative}", file=sys.stderr)
                sys.exit(1)
            try:
                size = list(png_size(path))
            except Exception as exc:
                print(f"ERROR: bottom-bar visual source is not readable: {relative}: {exc}", file=sys.stderr)
                sys.exit(1)
            if size != [int(canvas[0]), int(canvas[1])] or source.get("size") != size:
                print(f"ERROR: bottom-bar visual source dimensions mismatch for {relative}", file=sys.stderr)
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
        if source.get("bytes") != len(canonical_bytes(path)):
            print(f"ERROR: translation source size mismatch for {relative}", file=sys.stderr)
            sys.exit(1)
        for visual in surface.get("visual_sources", []) or []:
            relative = visual.get("relative_path") if isinstance(visual, dict) else None
            if (not isinstance(relative, str) or not relative or relative.startswith("/")
                    or ".." in Path(relative).parts):
                print(f"ERROR: invalid visual source path on {surface.get('name')!r}", file=sys.stderr)
                sys.exit(1)
            path = root / relative
            if not path.is_file():
                print(f"ERROR: missing visual source {relative}", file=sys.stderr)
                sys.exit(1)
            if visual.get("sha256") != sha256(path) or visual.get("bytes") != path.stat().st_size:
                print(f"ERROR: visual source hash/size mismatch for {relative}", file=sys.stderr)
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


def validate_runtime_sources(root: Path) -> None:
    from llm_translate_untranslated import source_id, validate_translation
    for path in sorted((root / 'localization').glob('*/runtime-bi-zhcn.json')):
        doc = load(path, 'runtime BI catalogue')
        if (doc.get('kind') != 'mltd-apk-runtime-bi-source'
                or doc.get('client_version') != path.parent.name
                or doc.get('apk_entry') != 'assets/bin/Data/data.unity3d'
                or not isinstance(doc.get('rows'), list) or not doc['rows']):
            raise ValueError(f'Invalid runtime BI catalogue: {path}')
        for field in ('source_apk_sha256', 'source_entry_sha256'):
            if not re.fullmatch(r'[0-9a-f]{64}', str(doc.get(field, ''))):
                raise ValueError(f'Invalid {field}: {path}')
        for index, row in enumerate(doc['rows']):
            source, zh = row.get('ja'), row.get('zh')
            if (row.get('record_index') != index or not isinstance(row.get('key'), str)
                    or not isinstance(source, str) or not isinstance(zh, str)
                    or row.get('source_sha256') != source_id(source)):
                raise ValueError(f'Invalid BI source identity/order: {path}:{index}')
            if row.get('translatable') is True:
                if row.get('status') not in ('accepted', 'untranslated'):
                    raise ValueError(f'Invalid BI translation status: {path}:{index}')
                if row['status'] == 'accepted':
                    if not zh.strip():
                        raise ValueError(f'Empty accepted BI translation: {path}:{index}')
                    validate_translation(source, zh)
            elif row.get('translatable') is not False or zh != source or row.get('status') != 'passthrough':
                raise ValueError(f'Invalid BI passthrough record: {path}:{index}')


def main() -> int:
    print(f"Validating APK built-in repository at: {ROOT}")
    bottom_bar = validate_bottom_bar(ROOT)
    builtin = validate_builtin(ROOT)
    reject_assets_axis(load(ROOT / "manifests" / "apk-builtin.manifest.json", "apk-builtin manifest"))
    validate_schema(ROOT)
    validate_runtime_sources(ROOT)

    print("\nRepository validation SUCCESSFUL!")
    print(f"Bottom-bar slots: {bottom_bar['slots']}")
    print(f"Built-in surfaces: {builtin['surfaces']}")
    print(f"Client version: {builtin['client_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
