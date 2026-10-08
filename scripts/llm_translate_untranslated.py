#!/usr/bin/env python3
"""Collect and apply LLM drafts for the Client JSON translation sources.

The Client repository stores a small nested JSON source rather than the JSONL
catalogue used by Assets.  This adapter keeps the same provider pool and draft
semantics while preserving source identity and only filling empty ``zh``
fields.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

ROOT = Path(__file__).resolve().parents[1]
PROTECTED_TOKENS = re.compile(r"\{[^{}]+\}|%[-+0 #]*\d*(?:\.\d+)?[a-zA-Z]|<[^<>\r\n]+>|\\[nrt]|\\[0-9]{2}\\")


def validate_translation(source: str, translation: str) -> None:
    if any(char in translation for char in ('|', '^', '\0')):
        raise ValueError('LLM output contains a reserved BI delimiter')
    if Counter(PROTECTED_TOKENS.findall(source)) != Counter(PROTECTED_TOKENS.findall(translation)):
        raise ValueError('LLM output changed protected formatting tokens')


def refresh_source_hashes() -> None:
    path = ROOT / 'manifests/apk-builtin.manifest.json'
    document = json.loads(path.read_text(encoding='utf-8'))
    changed = False
    for surface in document['surfaces']:
        source = surface.get('translation_source')
        if source:
            data = (ROOT / source['relative_path']).read_bytes().replace(b'\r\n', b'\n')
            new_hash, size = hashlib.sha256(data).hexdigest(), len(data)
            if source.get('sha256') != new_hash or source.get('bytes') != size:
                source.update(sha256=new_hash, bytes=size)
                changed = True
    if changed:
        path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def source_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def source_files() -> Iterator[Path]:
    yield from sorted((ROOT / "localization").rglob("*.json"))


def records(value: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    if isinstance(value, dict):
        if isinstance(value.get("ja"), str) and isinstance(value.get("zh"), str):
            yield path, value
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from records(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from records(child, f"{path}[{index}]")


def eligible(row: dict[str, Any]) -> bool:
    status = row.get("status")
    return not row.get("zh", "") and status in (None, "untranslated")


def collect(args: argparse.Namespace) -> int:
    # Resolve identical Japanese sources locally before spending provider tokens.
    candidates: dict[str, set[str]] = {}
    documents = [(path, json.loads(path.read_text(encoding='utf-8'))) for path in source_files()]
    for _, document in documents:
        for _, row in records(document):
            if row['zh'] and row.get('status') in (None, 'accepted'):
                validate_translation(row['ja'], row['zh'])
                candidates.setdefault(row['ja'], set()).add(row['zh'])
    reused = 0
    for path, document in documents:
        changed = False
        for _, row in records(document):
            choices = candidates.get(row['ja'], set())
            if eligible(row) and len(choices) == 1:
                row.update(zh=next(iter(choices)), status='accepted', translation_stage='reused_exact_source')
                changed = True
                reused += 1
        if changed:
            path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8', newline='\n')
    if reused:
        refresh_source_hashes()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    count = 0
    with args.output.open("w", encoding="utf-8", newline="\n") as stream:
        for path in source_files():
            document = json.loads(path.read_text(encoding="utf-8"))
            for key_path, row in records(document):
                source = row["ja"]
                if not eligible(row) or not source:
                    continue
                sid = source_id(source)
                if sid in seen:
                    continue
                seen.add(sid)
                stream.write(json.dumps({
                    "source": source,
                    "source_sha256": sid,
                    "bundle": path.relative_to(ROOT).as_posix(),
                    "key": key_path,
                    "task": "UI",
                    "translation": "",
                    "status": "pending",
                }, ensure_ascii=False, separators=(",", ":")) + "\n")
                count += 1
    print(json.dumps({"queue": str(args.output), "items": count, "reused": reused}, ensure_ascii=False))
    return 0


def apply(args: argparse.Namespace) -> int:
    translations: dict[str, str] = {}
    for line in args.draft.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        source = str(row.get("source", ""))
        sid = str(row.get("source_sha256", ""))
        translation = str(row.get("translation", "")).strip()
        if not source or sid != source_id(source) or not translation:
            continue
        validate_translation(source, translation)
        prior = translations.get(sid)
        if prior is not None and prior != translation:
            raise SystemExit(f"conflicting LLM output for source {sid}")
        translations[sid] = translation

    if not translations:
        print(json.dumps({"updated": 0, "drafts": 0}, ensure_ascii=False))
        return 0

    timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    updated = 0
    for path in source_files():
        document = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for _, row in records(document):
            source = str(row.get("ja", ""))
            sid = source_id(source) if source else ""
            translation = translations.get(sid)
            if translation is None or not eligible(row):
                continue
            row["zh"] = translation
            # Client policy promotes LLM output directly into the buildable
            # state.  Keep the provenance marker so downstream tooling can
            # distinguish it from a human-authored translation.
            row["status"] = "accepted"
            row["translation_stage"] = "llm_translated"
            row["updated_at"] = timestamp
            changed = True
            updated += 1
        if changed:
            path.write_text(
                json.dumps(document, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
                newline="\n",
            )
    refresh_source_hashes()
    print(json.dumps({"updated": updated, "drafts": len(translations),
                      "stage": "llm_translated"}, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--output", type=Path, required=True)
    collect_parser.set_defaults(func=collect)
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--draft", type=Path, required=True)
    apply_parser.set_defaults(func=apply)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
