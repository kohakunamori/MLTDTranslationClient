"""Shared repository primitives used by the Client maintenance scripts.

Keeping these rules in one module prevents the validator, translation adapter,
portal manifest builder, and dispatch gate from silently disagreeing about
canonical bytes or which Client version is active.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

TEXT_SUFFIXES = {".json", ".md", ".py", ".txt"}
SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMIT_RE = re.compile(r"[0-9a-f]{40}")
REPOSITORY_RE = re.compile(r"[\w.-]+/[\w.-]+")
VERSION_RE = re.compile(r"\d+(?:\.\d+)+")
BUILTIN_MANIFEST_RELATIVE = "manifests/apk-builtin.manifest.json"
BOTTOM_BAR_MANIFEST_RELATIVE = "manifests/bottom-bar.manifest.json"


@dataclass(frozen=True, slots=True)
class RepositoryLayout:
    """Stable path contract for the Client repository.

    Workflow scripts should ask the layout for paths instead of rebuilding
    directory strings. New resource families can add one accessor here without
    changing every caller.
    """

    root: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", Path(self.root))

    @property
    def manifests(self) -> Path:
        return self.root / "manifests"

    @property
    def localization(self) -> Path:
        return self.root / "localization"

    @property
    def builtin_manifest(self) -> Path:
        return self.root / BUILTIN_MANIFEST_RELATIVE

    @property
    def bottom_bar_manifest(self) -> Path:
        return self.root / BOTTOM_BAR_MANIFEST_RELATIVE

    @property
    def source_state_manifest(self) -> Path:
        return self.manifests / "apk-source-state.json"

    @property
    def portal_manifest(self) -> Path:
        return self.manifests / "portal-resource-manifest.json"

    def client_directory(self, version: str) -> Path:
        return self.localization / version

    def runtime_catalogue(self, version: str) -> Path:
        return self.client_directory(version) / "runtime-bi-zhcn.json"

    def translation_sources(self, version: str | None = None) -> list[Path]:
        directory = self.client_directory(version) if version else self.localization
        return sorted(directory.rglob("*.json"))

    def runtime_catalogues(self) -> list[Path]:
        return sorted(self.localization.glob("*/runtime-bi-zhcn.json"))


def canonical_bytes(path: Path) -> bytes:
    """Return bytes as Git stores text files regardless of checkout EOLs."""
    data = path.read_bytes()
    return data.replace(b"\r\n", b"\n") if path.suffix.lower() in TEXT_SUFFIXES else data


def sha256(path: Path) -> str:
    return sha256_bytes(canonical_bytes(path))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any, *, sort_keys: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=sort_keys) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def active_client_version(root: Path) -> str:
    manifest = read_json(RepositoryLayout(root).builtin_manifest)
    version = str(manifest.get("provenance", {}).get("client_version", "")).strip()
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"Invalid active client version: {version!r}")
    return version


def runtime_catalogue(root: Path, version: str | None = None) -> tuple[Path, dict[str, Any]] | None:
    version = version or active_client_version(root)
    path = RepositoryLayout(root).runtime_catalogue(version)
    if not path.is_file():
        return None
    return path, read_json(path)


def runtime_translation_ready(root: Path, version: str | None = None) -> bool:
    """Whether every translatable runtime row has a non-empty accepted zh value."""
    catalogue = runtime_catalogue(root, version)
    if catalogue is None:
        return True
    _, document = catalogue
    return not any(
        row.get("translatable")
        and (row.get("status") != "accepted" or not str(row.get("zh", "")).strip())
        for row in document.get("rows", [])
    )


def require_repository_inputs(repository: str, commit: str) -> None:
    if not REPOSITORY_RE.fullmatch(repository) or not COMMIT_RE.fullmatch(commit):
        raise ValueError("Expected a repository and a full commit SHA")


def valid_sha256(value: object) -> bool:
    return isinstance(value, str) and bool(SHA256_RE.fullmatch(value))
