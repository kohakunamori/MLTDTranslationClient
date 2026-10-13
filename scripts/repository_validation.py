"""Reusable validation rules for the Client source repository.

The command-line entrypoint only formats the result.  Keeping validation here
allows other automation to gate a build without invoking a subprocess or
depending on CLI output.
"""
from __future__ import annotations

import json
import re
import struct
from pathlib import Path
from typing import Any

try:
    from scripts.repo_utils import (
        RepositoryLayout,
        canonical_bytes,
        sha256,
        valid_sha256,
    )
    from scripts.translation_pipeline import source_id, validate_translation
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from repo_utils import RepositoryLayout, canonical_bytes, sha256, valid_sha256
    from translation_pipeline import source_id, validate_translation

KNOWN_SURFACES = {"bottom-bar-atlas", "runtime-bi", "cjk-font", "component-text"}


class ValidationError(ValueError):
    """A source repository violates a build invariant."""


def load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ValidationError(f"Missing {label} at {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"{path} invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{path} must contain a JSON object")
    return value


def png_size(path: Path) -> tuple[int, int]:
    raw = path.read_bytes()
    if len(raw) < 24 or raw[:8] != b"\x89PNG\r\n\x1a\n" or raw[12:16] != b"IHDR":
        raise ValidationError(f"not a PNG with an IHDR header: {path}")
    return struct.unpack(">II", raw[16:24])


def reject_assets_axis(node: object, path: str = "<root>") -> None:
    """The Client repository must not grow a hidden Client+Assets identity."""
    if isinstance(node, dict):
        for key, value in node.items():
            if str(key).lower() in {"asset_version", "assets_version", "base_version"}:
                raise ValidationError(f"Assets-axis field {path}.{key} is forbidden")
            reject_assets_axis(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            reject_assets_axis(value, f"{path}[{index}]")


class RepositoryValidator:
    """Validate all source invariants needed before a Client build."""

    def __init__(self, root: Path):
        self.layout = RepositoryLayout(root)
        self.root = self.layout.root

    def validate(self) -> dict[str, Any]:
        bottom_bar = self.validate_bottom_bar()
        builtin = self.validate_builtin()
        reject_assets_axis(load_json(self.layout.builtin_manifest, "apk-builtin manifest"))
        self.validate_schema()
        self.validate_runtime_sources()
        self.validate_component_sources()
        shared = self.root / 'localization/shared/apk-text-zhcn.json'
        if shared.exists():
            from scripts.apk_text_requests import validate_catalogue
            validate_catalogue(load_json(shared, 'shared APK text catalogue'))
        return {"bottom_bar": bottom_bar, "builtin": builtin}

    def validate_component_sources(self) -> None:
        for path in (self.root / 'localization').glob('*/component-text-zhcn.json'):
            doc = load_json(path, 'component text catalogue')
            if doc.get('kind') != 'mltd-apk-component-text' or doc.get('client_version') != path.parent.name:
                raise ValidationError(f'Invalid component catalogue: {path}')
            seen = set()
            for row in doc.get('rows', []):
                source, zh = row.get('ja'), row.get('zh')
                if (not isinstance(source, str) or not isinstance(zh, str)
                        or row.get('source_sha256') != source_id(source) or source in seen):
                    raise ValidationError(f'Invalid component source: {path}')
                seen.add(source)
                if row.get('status') == 'accepted' and zh.strip() and '\0' not in zh:
                    validate_translation(source, zh)
                elif row.get('status') != 'passthrough' or zh != source:
                    raise ValidationError(f'Invalid component translation: {path}')
            for row in doc.get('android_rows', []):
                source, zh = row.get('ja'), row.get('zh')
                if (not isinstance(source, str) or not isinstance(zh, str) or not zh.strip()
                        or row.get('source_sha256') != source_id(source) or row.get('status') != 'accepted'
                        or '\0' in zh):
                    raise ValidationError(f'Invalid Android text translation: {path}')
                validate_translation(source, zh)
                token = r'%(?:\d+\$)?[-+0 #]*\d*(?:\.\d+)?[a-zA-Z%]'
                if sorted(re.findall(token, source)) != sorted(re.findall(token, zh)):
                    raise ValidationError(f'Invalid Android format token: {path}')
            counts = doc.get('counts', {})
            if counts != {'sources': len(doc['rows']),
                          'accepted': sum(row['status'] == 'accepted' for row in doc['rows']),
                          'excluded': sum(row['status'] == 'passthrough' for row in doc['rows'])}:
                raise ValidationError(f'Invalid component counts: {path}')

    def validate_bottom_bar(self) -> dict[str, int]:
        doc = load_json(self.layout.bottom_bar_manifest, "bottom-bar manifest")
        if doc.get("kind") != "mltd-bottom-bar-manifest":
            raise ValidationError(f"unexpected bottom-bar kind {doc.get('kind')!r}")

        slots = doc.get("slots", [])
        if not isinstance(slots, list) or len(slots) != 7:
            raise ValidationError(f"bottom-bar slot count {len(slots) if isinstance(slots, list) else 0} != 7")
        for slot in slots:
            if not isinstance(slot, dict):
                raise ValidationError("bottom-bar slot must be an object")
            for key in ("index", "ja", "zh", "provenance"):
                if key not in slot:
                    raise ValidationError(f"bottom-bar slot {slot.get('index')} lacks {key}")

        atlas = doc.get("atlas_target", {})
        if not isinstance(atlas, dict) or atlas.get("slot_count") != len(slots):
            raise ValidationError("atlas_target.slot_count disagrees with slots")
        visuals = doc.get("visual_assets")
        if visuals is not None:
            self._validate_visual_assets(visuals, len(slots))
        return {"slots": len(slots)}

    def _validate_visual_assets(self, visuals: object, slot_count: int) -> None:
        if not isinstance(visuals, dict):
            raise ValidationError("bottom-bar visual_assets must be an object")
        canvas = visuals.get("canvas_size")
        segments = visuals.get("segment_x")
        try:
            valid_canvas = (
                isinstance(canvas, list)
                and len(canvas) == 2
                and all(not isinstance(part, bool) and int(part) > 0 for part in canvas)
            )
        except (TypeError, ValueError):
            valid_canvas = False
        if not valid_canvas:
            raise ValidationError("bottom-bar visual_assets.canvas_size is invalid")
        try:
            valid_segments = (
                isinstance(segments, list)
                and len(segments) == slot_count + 1
                and [int(part) for part in segments] == sorted(set(int(part) for part in segments))
                and int(segments[0]) == 0
                and int(segments[-1]) == int(canvas[0])
            )
        except (IndexError, TypeError, ValueError):
            valid_segments = False
        if not valid_segments:
            raise ValidationError("bottom-bar visual_assets.segment_x is invalid")

        for state in ("off", "on"):
            source = visuals.get(state)
            if not isinstance(source, dict):
                raise ValidationError(f"bottom-bar visual_assets.{state} is missing")
            relative = source.get("path")
            path = self._safe_path(relative)
            if path is None or not path.is_file():
                raise ValidationError(f"missing bottom-bar visual source {relative}")
            if source.get("sha256") != sha256(path) or source.get("bytes") != path.stat().st_size:
                raise ValidationError(f"bottom-bar visual source hash/size mismatch for {relative}")
            try:
                size = list(png_size(path))
            except (OSError, ValidationError) as exc:
                raise ValidationError(f"bottom-bar visual source is not readable: {relative}: {exc}") from exc
            if size != [int(canvas[0]), int(canvas[1])] or source.get("size") != size:
                raise ValidationError(f"bottom-bar visual source dimensions mismatch for {relative}")

    def validate_builtin(self) -> dict[str, int | str]:
        doc = load_json(self.layout.builtin_manifest, "apk-builtin manifest")
        if doc.get("kind") != "mltd-apk-builtin-manifest":
            raise ValidationError(f"unexpected apk-builtin kind {doc.get('kind')!r}")

        surfaces = doc.get("surfaces", [])
        if not isinstance(surfaces, list) or not surfaces:
            raise ValidationError("apk-builtin manifest lists no surfaces")
        names = [surface.get("name") for surface in surfaces if isinstance(surface, dict)]
        unknown = [name for name in names if name not in KNOWN_SURFACES]
        if unknown:
            raise ValidationError(f"unknown apk-builtin surface(s): {unknown}")
        if len(set(names)) != len(names):
            raise ValidationError("duplicate surface names")
        if doc.get("counts", {}).get("surfaces") != len(surfaces):
            raise ValidationError("counts.surfaces disagrees with surfaces")

        provenance = doc.get("provenance", {})
        client_version = provenance.get("client_version") if isinstance(provenance, dict) else None
        if not isinstance(client_version, str) or not re.fullmatch(r"\d+(?:\.\d+)+", client_version):
            raise ValidationError(f"invalid client_version {client_version!r}")
        if provenance.get("axis") != "client":
            raise ValidationError("apk-builtin provenance must declare axis=client")

        for surface in surfaces:
            if not isinstance(surface, dict):
                raise ValidationError("apk-builtin surface must be an object")
            self._validate_source(surface.get("translation_source"), surface.get("name"), "translation_source")
            for visual in surface.get("visual_sources", []) or []:
                self._validate_source(visual, surface.get("name"), "visual source")
        return {"surfaces": len(surfaces), "client_version": client_version}

    def _validate_source(self, source: object, surface_name: object, label: str) -> None:
        if source is None and label == "translation_source":
            return
        if not isinstance(source, dict):
            raise ValidationError(f"invalid {label} on {surface_name!r}")
        relative = source.get("relative_path")
        path = self._safe_path(relative)
        if path is None:
            raise ValidationError(f"invalid {label} path on {surface_name!r}")
        if not path.is_file():
            raise ValidationError(f"missing {label} {relative}")
        if source.get("sha256") != sha256(path):
            raise ValidationError(f"{label} hash mismatch for {relative}")
        expected_bytes = len(canonical_bytes(path))
        if source.get("bytes") != expected_bytes:
            raise ValidationError(f"{label} size mismatch for {relative}")

    def _safe_path(self, relative: object) -> Path | None:
        if not isinstance(relative, str) or not relative:
            return None
        candidate = Path(relative)
        if candidate.is_absolute() or ".." in candidate.parts:
            return None
        return self.root / candidate

    def validate_schema(self) -> None:
        schema = load_json(self.layout.builtin_schema, "apk-builtin schema")
        properties = schema.get("properties", {})
        if properties.get("kind", {}).get("const") != "mltd-apk-builtin-manifest":
            raise ValidationError("schema does not pin kind=mltd-apk-builtin-manifest")
        if properties.get("schema_version", {}).get("const") != 2:
            raise ValidationError("schema must be version 2 for the independent Client axis")

    def validate_runtime_sources(self) -> None:
        for path in self.layout.runtime_catalogues():
            doc = load_json(path, "runtime BI catalogue")
            if (
                doc.get("kind") != "mltd-apk-runtime-bi-source"
                or doc.get("client_version") != path.parent.name
                or doc.get("apk_entry") != "assets/bin/Data/data.unity3d"
                or not isinstance(doc.get("rows"), list)
                or not doc["rows"]
            ):
                raise ValidationError(f"Invalid runtime BI catalogue: {path}")
            for field in ("source_apk_sha256", "source_entry_sha256"):
                if not valid_sha256(doc.get(field)):
                    raise ValidationError(f"Invalid {field}: {path}")
            for index, row in enumerate(doc["rows"]):
                if not isinstance(row, dict):
                    raise ValidationError(f"Invalid BI row: {path}:{index}")
                source, zh = row.get("ja"), row.get("zh")
                if (
                    row.get("record_index") != index
                    or not isinstance(row.get("key"), str)
                    or not isinstance(source, str)
                    or not isinstance(zh, str)
                    or row.get("source_sha256") != source_id(source)
                ):
                    raise ValidationError(f"Invalid BI source identity/order: {path}:{index}")
                if row.get("translatable") is True:
                    if row.get("status") not in ("accepted", "untranslated"):
                        raise ValidationError(f"Invalid BI translation status: {path}:{index}")
                    if row["status"] == "accepted":
                        if not zh.strip():
                            raise ValidationError(f"Empty accepted BI translation: {path}:{index}")
                        validate_translation(source, zh)
                elif row.get("translatable") is not False or zh != source or row.get("status") != "passthrough":
                    raise ValidationError(f"Invalid BI passthrough record: {path}:{index}")
