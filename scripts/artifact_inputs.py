"""Compare the exact repository inputs embedded in the built Client APK."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

try:
    from scripts.repo_utils import BOTTOM_BAR_MANIFEST_RELATIVE, BUILTIN_MANIFEST_RELATIVE
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from repo_utils import BOTTOM_BAR_MANIFEST_RELATIVE, BUILTIN_MANIFEST_RELATIVE

NULL_REVISION = "0" * 40
MANIFESTS = (BUILTIN_MANIFEST_RELATIVE, BOTTOM_BAR_MANIFEST_RELATIVE)


class InputError(Exception):
    """The input set could not be read; callers must build, not skip."""


def git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=str(root), text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if result.returncode != 0:
        raise InputError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def show(root: Path, revision: str, path: str) -> str:
    return git(root, "show", f"{revision}:{path}")


def ls_tree(root: Path, revision: str) -> dict[str, str]:
    """Map every path in a revision tree to its stored Git blob."""
    entries: dict[str, str] = {}
    for line in git(root, "ls-tree", "-r", revision).splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) >= 3 and path:
            entries[path] = parts[2]
    return entries


def read_client_version(root: Path, revision: str) -> str:
    document = json.loads(show(root, revision, BUILTIN_MANIFEST_RELATIVE))
    version = str(document.get("provenance", {}).get("client_version", "")).strip()
    if not version:
        raise InputError(f"{BUILTIN_MANIFEST_RELATIVE} names no client_version at {revision}")
    return version


def inputs_at(root: Path, revision: str) -> dict[str, str]:
    """Return the artifact input set at one revision as ``{path: blob}``."""
    version = read_client_version(root, revision)
    prefix = f"localization/{version}/"
    entries = {
        path: blob for path, blob in ls_tree(root, revision).items()
        if path in MANIFESTS or path.startswith(prefix)
    }
    missing = [path for path in MANIFESTS if path not in entries]
    if missing:
        raise InputError(f"{', '.join(missing)} missing from the tree at {revision}")
    if not any(path.startswith(prefix) for path in entries):
        raise InputError(f"localization/{version}/ holds no file at {revision}")
    return entries


def fingerprint(entries: dict[str, str]) -> str:
    digest = hashlib.sha256()
    for path in sorted(entries):
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(entries[path].encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def difference(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return sorted(
        path for path in set(before) | set(after)
        if before.get(path) != after.get(path)
    )


def decide(root: Path, before: str, after: str) -> dict:
    """Compare two revisions; never raise, always answer."""
    report: dict = {
        "before_revision": before, "after_revision": after,
        "changed": True, "reason": "", "changed_paths": [],
    }
    before = (before or "").strip().lower()
    if not before or before == NULL_REVISION:
        report["reason"] = "no_baseline"
        return report
    try:
        after_entries = inputs_at(root, after)
        before_entries = inputs_at(root, before)
    except (InputError, ValueError, OSError, json.JSONDecodeError) as exc:
        report["reason"] = "baseline_unreadable"
        report["detail"] = str(exc)
        return report

    report["after_client_version"] = read_client_version(root, after)
    report["before_client_version"] = read_client_version(root, before)
    report["after_fingerprint"] = fingerprint(after_entries)
    report["before_fingerprint"] = fingerprint(before_entries)
    report["inputs"] = len(after_entries)
    report["changed_paths"] = difference(before_entries, after_entries)
    if report["before_fingerprint"] == report["after_fingerprint"]:
        report["changed"] = False
        report["reason"] = "artifact_inputs_unchanged"
    else:
        report["reason"] = "artifact_inputs_changed"
    return report


def write_github_output(report: dict, stream) -> None:
    dispatch = "true" if report["changed"] else "false"
    stream.write(f"dispatch={dispatch}\n")
    stream.write(f"reason={report['reason']}\n")
    paths = ",".join(report.get("changed_paths", [])[:20])
    stream.write(f"changed_paths={paths}\n")
