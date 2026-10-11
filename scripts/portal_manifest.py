"""Build the immutable Client summary consumed by the translation portal."""
from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.repo_utils import RepositoryLayout, read_json, sha256, write_json
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from repo_utils import RepositoryLayout, read_json, sha256, write_json


def git_commit(root: Path) -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True,
        ).strip()
    except Exception:
        return None


def content_only(document: dict[str, Any]) -> dict[str, Any]:
    value = json.loads(json.dumps(document))
    value.get("source", {}).pop("commit", None)
    value.get("release", {}).pop("client_resources_commit", None)
    return value


class PortalManifestBuilder:
    """Create and persist a portal manifest from repository source manifests."""

    def __init__(self, root: Path):
        self.layout = RepositoryLayout(root)
        self.root = self.layout.root

    def build(self) -> dict[str, Any]:
        builtin = read_json(self.layout.builtin_manifest)
        bottom = read_json(self.layout.bottom_bar_manifest)
        client_version = str(builtin["provenance"]["client_version"])
        slots = bottom.get("slots", [])
        translated = sum(1 for slot in slots if str(slot.get("zh") or "").strip())
        total = len(slots)
        bundles = {
            "bottom-bar.manifest.json": {
                "total": total, "translated": translated,
                "pending": 0, "untranslated": total - translated,
            }
        }
        runtime_path = self.layout.runtime_catalogue(client_version)
        if runtime_path.is_file():
            runtime = read_json(runtime_path)
            rows = [row for row in runtime.get("rows", []) if row.get("translatable")]
            accepted = sum(
                row.get("status") == "accepted" and bool(str(row.get("zh") or "").strip())
                for row in rows
            )
            bundles["runtime-bi-zhcn.json"] = {
                "total": len(rows), "translated": accepted,
                "pending": 0, "untranslated": len(rows) - accepted,
            }
            total += len(rows)
            translated += accepted
        updated_at = builtin.get("generated_at") or datetime.now(timezone.utc).isoformat()
        commit = git_commit(self.root)
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
            "untranslated": total - translated,
            "progress_percent": round(translated / total * 100, 2) if total else 0,
            "bundles": bundles,
        }
        return {
            "schema": "mltd.portal.resource-manifest/v1",
            "kind": "client",
            "generated_at": updated_at,
            "summary_ready": True,
            "release": {
                "release_id": f"client-{client_version}-arm64",
                "client_version": client_version,
                "abi": "arm64-v8a",
                "status": "published",
                "manifest_sha256": sha256(self.layout.builtin_manifest),
                "client_resources_commit": commit,
                "updated_at": updated_at,
            },
            "totals": {
                "total": total, "translated": translated, "pending": 0,
                "untranslated": total - translated, "reused": 0,
                "suggested": 0, "blocked": 0,
            },
            "domains": [{
                "id": "system", "name": "系统界面", "icon": "⚙️",
                "total": total, "accepted": translated,
                "categories": ["system_ui"],
                "progress_percent": round(translated / total * 100, 2) if total else 0,
            }],
            "categories": [category],
            "source": {
                "summary": "github-client-repository",
                "repository": "kohakunamori/MLTDTranslationClient",
                "commit": commit,
                "builtin_manifest_sha256": sha256(self.layout.builtin_manifest),
                "bottom_bar_manifest_sha256": sha256(self.layout.bottom_bar_manifest),
                "surface_count": int(builtin.get("counts", {}).get("surfaces", 0)),
            },
        }

    def write(self, target: Path | None = None) -> tuple[Path, bool, dict[str, Any]]:
        target = target or self.layout.portal_manifest
        target = (self.root / target).resolve() if not target.is_absolute() else target
        output = self.build()
        if target.is_file() and content_only(read_json(target)) == content_only(output):
            return target, True, output
        write_json(target, output, sort_keys=True)
        return target, False, output
