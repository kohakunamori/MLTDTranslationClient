"""Domain logic for collecting and applying Client translation sources.

This module deliberately has no command-line concerns. Other automation can
reuse the same catalogue rules without importing a CLI module or manufacturing
``argparse.Namespace`` objects.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:  # Support package imports and direct script execution.
    from .repo_utils import (
        RepositoryLayout,
        canonical_bytes,
        read_json,
        sha256,
        sha256_bytes,
        write_json,
    )
except ImportError:  # pragma: no cover - direct file execution
    from repo_utils import RepositoryLayout, canonical_bytes, read_json, sha256, sha256_bytes, write_json

PROTECTED_TOKENS = re.compile(
    r"\{[^{}]+\}|%(?:\d+\$)?[-+0 #]*\d*(?:\.\d+)?[a-zA-Z%]|<[^<>\r\n]+>|\\[nrt]|\\[0-9]{2}\\|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
)
GROUPED_NUMBER = re.compile(r'(?<!\d)\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)')
TRANSLATED_GROUPED_NUMBER = re.compile(r'(?<!\d)\d{1,3}(?:[,，、]\d{3})+(?:\.\d+)?(?!\d)')


def repair_numeric_separators(source: str, translation: str) -> str:
    """Restore source separators only when the exact digits and decimal agree."""
    choices: dict[str, set[str]] = {}
    def identity(value):
        return re.sub('[,，、]', '', value)
    for match in GROUPED_NUMBER.finditer(source):
        choices.setdefault(identity(match[0]), set()).add(match[0])
    def restore(match):
        values = choices.get(identity(match[0]), set())
        return next(iter(values)) if len(values) == 1 else match[0]
    return TRANSLATED_GROUPED_NUMBER.sub(restore, translation)


def validate_translation(source: str, translation: str) -> None:
    if any(char in translation for char in ("|", "^", "\0")):
        raise ValueError("LLM output contains a reserved BI delimiter")
    if Counter(PROTECTED_TOKENS.findall(source)) != Counter(PROTECTED_TOKENS.findall(translation)):
        raise ValueError("LLM output changed protected formatting tokens")


def source_id(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def records(value: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield translation records from any nested JSON value."""
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
    return not row.get("zh", "") and row.get("status") in (None, "untranslated")


class TranslationPipeline:
    """Read and update all editable JSON catalogues for one repository."""

    def __init__(self, root: Path):
        self.layout = RepositoryLayout(root)
        self.root = self.layout.root

    def source_files(self) -> list[Path]:
        return self.layout.translation_sources()

    def refresh_source_hashes(self) -> None:
        path = self.layout.builtin_manifest
        document = read_json(path)
        shared_path = self.root / 'localization/shared/apk-text-zhcn.json'
        if shared_path.exists():
            from scripts.apk_text_requests import validate_catalogue
            shared = read_json(shared_path)
            validate_catalogue(shared)
            for surface in document['surfaces']:
                source = surface.get('translation_source')
                if surface.get('name') != 'component-text' or not source:
                    continue
                target_path = self.root / source['relative_path']
                component = read_json(target_path)
                for field, name in (('rows', 'component'), ('android_rows', 'android')):
                    indexed = {row['ja']: row for row in component.get(field, [])}
                    for row in shared['rows']:
                        if row['status'] != 'accepted' or not any(c['surface'] == name for c in row['contexts']):
                            continue
                        prior = indexed.get(row['ja'])
                        if prior and prior['zh'] != row['zh']:
                            raise ValueError('Shared Client text conflicts with the active catalogue')
                        if not prior:
                            indexed[row['ja']] = {key: row[key] for key in ('ja', 'zh', 'status', 'source_sha256')}
                    component[field] = list(indexed.values())
                component['counts'] = {'sources': len(component['rows']),
                    'accepted': sum(row['status'] == 'accepted' for row in component['rows']),
                    'excluded': sum(row['status'] == 'passthrough' for row in component['rows'])}
                write_json(target_path, component)
        changed = False
        for surface in document["surfaces"]:
            source = surface.get("translation_source")
            if not source:
                continue
            source_path = self.root / source["relative_path"]
            new_hash, size = sha256(source_path), len(canonical_bytes(source_path))
            if source.get("sha256") != new_hash or source.get("bytes") != size:
                source.update(sha256=new_hash, bytes=size)
                changed = True
        if changed:
            write_json(path, document)

    def collect(self, output: Path) -> dict[str, int | str]:
        # Resolve identical Japanese sources locally before spending provider tokens.
        documents = [(path, read_json(path)) for path in self.source_files()]
        repaired = 0
        for path, document in documents:
            changed = False
            for _, row in records(document):
                if row.get('status') not in (None, 'accepted') or not row['zh']:
                    continue
                corrected = repair_numeric_separators(row['ja'], row['zh'])
                if corrected != row['zh']:
                    validate_translation(row['ja'], corrected)
                    row['zh'] = corrected
                    row['format_repair'] = 'exact-source-numeric-separators'
                    changed = True
                    repaired += 1
            if changed:
                write_json(path, document, sort_keys=path == self.root / 'localization/shared/apk-text-zhcn.json')
        if repaired:
            self.refresh_source_hashes()
        candidates: dict[str, set[str]] = {}
        for _, document in documents:
            for _, row in records(document):
                if row["zh"] and row.get("status") in (None, "accepted"):
                    validate_translation(row["ja"], row["zh"])
                    candidates.setdefault(row["ja"], set()).add(row["zh"])

        reused = 0
        for path, document in documents:
            changed = False
            for _, row in records(document):
                choices = candidates.get(row["ja"], set())
                if eligible(row) and len(choices) == 1:
                    row.update(
                        zh=next(iter(choices)),
                        status="accepted",
                        translation_stage="reused_exact_source",
                    )
                    changed = True
                    reused += 1
            if changed:
                write_json(path, document, sort_keys=path == self.root / 'localization/shared/apk-text-zhcn.json')
        if reused:
            self.refresh_source_hashes()

        output.parent.mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        count = 0
        with output.open("w", encoding="utf-8", newline="\n") as stream:
            for path in self.source_files():
                document = read_json(path)
                for key_path, row in records(document):
                    source = row["ja"]
                    if not eligible(row) or not source:
                        continue
                    sid = source_id(source)
                    if sid in seen:
                        continue
                    seen.add(sid)
                    stream.write(
                        json.dumps(
                            {
                                "source": source,
                                "source_sha256": sid,
                                "bundle": path.relative_to(self.root).as_posix(),
                                "key": key_path,
                                "task": "UI",
                                "translation": "",
                                "status": "pending",
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                    count += 1
        return {"queue": str(output), "items": count, "reused": reused, "format_repaired": repaired}

    def apply(self, draft: Path) -> dict[str, int | str]:
        translations: dict[str, str] = {}
        rejected = 0
        for line in draft.read_text(encoding="utf-8-sig").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            source = str(row.get("source", ""))
            sid = str(row.get("source_sha256", ""))
            translation = str(row.get("translation", "")).strip()
            if not source or sid != source_id(source) or not translation:
                continue
            translation = repair_numeric_separators(source, translation)
            try:
                validate_translation(source, translation)
            except ValueError:
                # Keep valid progress and leave this source untranslated for
                # the next scheduled run; invalid formatting never reaches APKs.
                rejected += 1
                continue
            prior = translations.get(sid)
            if prior is not None and prior != translation:
                raise SystemExit(f"conflicting LLM output for source {sid}")
            translations[sid] = translation

        if not translations:
            return {"updated": 0, "drafts": 0, "rejected": rejected}

        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        updated = 0
        for path in self.source_files():
            document = read_json(path)
            changed = False
            for _, row in records(document):
                source = str(row.get("ja", ""))
                sid = source_id(source) if source else ""
                translation = translations.get(sid)
                if translation is None or not eligible(row):
                    continue
                row.update(
                    zh=translation,
                    status="accepted",
                    translation_stage="llm_translated",
                    updated_at=timestamp,
                )
                changed = True
                updated += 1
            if changed:
                write_json(path, document, sort_keys=path == self.root / 'localization/shared/apk-text-zhcn.json')
        self.refresh_source_hashes()
        return {"updated": updated, "drafts": len(translations), "rejected": rejected, "stage": "llm_translated"}
