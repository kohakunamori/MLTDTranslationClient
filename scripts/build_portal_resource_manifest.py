#!/usr/bin/env python3
"""Build the immutable Client summary consumed by the translation portal."""
from __future__ import annotations
import argparse, hashlib, json, subprocess
from datetime import datetime, timezone
from pathlib import Path


def canonical_bytes(path: Path) -> bytes:
    """Hash text sources as Git stores them, regardless of local checkout EOLs."""
    data = path.read_bytes()
    if path.suffix.lower() in {".json", ".md", ".py", ".txt"}:
        return data.replace(b"\r\n", b"\n")
    return data


def sha256(path: Path) -> str:
    # Hashing raw bytes would give a different digest in a working tree checked out
    # with core.autocrlf=true than in CI, so normalize the same way validate_repo.py
    # does. The portal reads these digests, so they must not depend on the checkout.
    return hashlib.sha256(canonical_bytes(path)).hexdigest()


def git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    except Exception:
        return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("manifests/portal-resource-manifest.json"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    builtin_path = root / "manifests" / "apk-builtin.manifest.json"
    bottom_path = root / "manifests" / "bottom-bar.manifest.json"
    builtin = json.loads(builtin_path.read_text(encoding="utf-8"))
    bottom = json.loads(bottom_path.read_text(encoding="utf-8"))
    provenance = builtin["provenance"]
    client_version = str(provenance["client_version"])
    slots = bottom.get("slots", [])
    translated = sum(1 for slot in slots if str(slot.get("zh") or "").strip())
    total = len(slots)
    bundles = {"bottom-bar.manifest.json": {"total": total, "translated": translated,
                                             "pending": 0, "untranslated": total - translated}}
    runtime_path = root / 'localization' / client_version / 'runtime-bi-zhcn.json'
    if runtime_path.is_file():
        runtime = json.loads(runtime_path.read_text(encoding='utf-8'))
        rows = [row for row in runtime.get('rows', []) if row.get('translatable')]
        accepted = sum(row.get('status') == 'accepted' and bool(str(row.get('zh') or '').strip()) for row in rows)
        bundles['runtime-bi-zhcn.json'] = {'total': len(rows), 'translated': accepted,
                                         'pending': 0, 'untranslated': len(rows) - accepted}
        total += len(rows)
        translated += accepted
    untranslated = total - translated
    commit = git_commit(root)
    updated_at = builtin.get("generated_at") or datetime.now(timezone.utc).isoformat()
    category = {
        "id": "system_ui",
        "domain": "system",
        "name": "APK 底栏与系统界面",
        "description": "Client 仓库可直接编辑的内置界面文字资源",
        "icon": "📱",
        "unit": "条",
        "entry": "client",
        "total": total,
        "accepted": translated,
        "pending": 0,
        "untranslated": untranslated,
        "progress_percent": round(translated / total * 100, 2) if total else 0,
        "bundles": bundles,
    }
    output = {
        "schema": "mltd.portal.resource-manifest/v1",
        "kind": "client",
        "generated_at": updated_at,
        "summary_ready": True,
        "release": {
            "release_id": f"client-{client_version}-arm64",
            "client_version": client_version,
            "abi": "arm64-v8a",
            # Acceptance is manual: the maintainer checked the output and pushed this
            # commit to main, so what the portal reads is released, not a candidate.
            "status": "published",
            "manifest_sha256": sha256(builtin_path),
            "client_resources_commit": commit,
            "updated_at": updated_at,
        },
        "totals": {
            "total": total,
            "translated": translated,
            "pending": 0,
            "untranslated": untranslated,
            "reused": 0,
            "suggested": 0,
            "blocked": 0,
        },
        "domains": [{"id": "system", "name": "系统界面", "icon": "⚙️", "total": total, "accepted": translated, "categories": ["system_ui"], "progress_percent": round(translated / total * 100, 2) if total else 0}],
        "categories": [category],
        "source": {
            "summary": "github-client-repository",
            "repository": "kohakunamori/MLTDTranslationClient",
            "commit": commit,
            "builtin_manifest_sha256": sha256(builtin_path),
            "bottom_bar_manifest_sha256": sha256(bottom_path),
            "surface_count": int(builtin.get("counts", {}).get("surfaces", 0)),
        },
    }
    target = (root / args.output).resolve() if not args.output.is_absolute() else args.output
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        previous = json.loads(target.read_text(encoding='utf-8'))
        def content_only(document):
            value = json.loads(json.dumps(document))
            value.get('source', {}).pop('commit', None)
            value.get('release', {}).pop('client_resources_commit', None)
            return value
        if content_only(previous) == content_only(output):
            print(json.dumps({'output': str(target), 'unchanged': True}))
            return 0
    target.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(target), "client_version": client_version, "total": total, "translated": translated}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
