#!/usr/bin/env python3
"""Decide whether a push changed anything the built APK actually embeds.

The private build is keyed on the Client commit: a new commit on this
repository's `main` makes it build the whole APK again, and its daily poll reads
this repository's head.  A push that cannot reach the artifact - a workflow
tweak, a documentation edit, or a change confined to a *different* official
version's directory than the one the built-in manifest currently names - would
therefore buy a full Windows build for bytes that are already on the release.

This answers the question the notification needs answered, and nothing else:

    "do the two revisions deliver the same bytes into the APK?"

The compared input set is the one the built-in manifest describes as its
output, not the repository:

* `manifests/apk-builtin.manifest.json`
* `manifests/bottom-bar.manifest.json`
* every file under `localization/<client_version>/`, where the version is the
  one the built-in manifest names *at that revision*

The comparison is content based rather than commit based, so a revert, a
rewritten commit, or a change to an inactive version's directory all answer
"unchanged" when the delivered bytes are in fact unchanged.

Every uncertain answer is "changed": a missing or unreadable baseline, an
unparsable manifest or an absent git object all ask for the build rather than
silently skipping one.  The script exits 0 on every path, so a caller can use
its output as an answer instead of as an error signal.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path

try:  # Keep Git-tree paths shared with the rest of the repository tooling.
    from scripts.repo_utils import BOTTOM_BAR_MANIFEST_RELATIVE, BUILTIN_MANIFEST_RELATIVE
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from repo_utils import BOTTOM_BAR_MANIFEST_RELATIVE, BUILTIN_MANIFEST_RELATIVE

ROOT = Path(__file__).resolve().parents[1]
BUILTIN_MANIFEST = BUILTIN_MANIFEST_RELATIVE
BOTTOM_BAR_MANIFEST = BOTTOM_BAR_MANIFEST_RELATIVE
MANIFESTS = (BUILTIN_MANIFEST, BOTTOM_BAR_MANIFEST)
NULL_REVISION = "0" * 40


class InputError(Exception):
    """The input set could not be read; the caller must build, not skip."""


def git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=str(root), text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if result.returncode != 0:
        raise InputError(f"git {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def show(root: Path, revision: str, path: str) -> str:
    return git(root, "show", f"{revision}:{path}")


def ls_tree(root: Path, revision: str) -> dict[str, str]:
    """Map every path in the revision's tree to the blob git stores for it."""
    entries: dict[str, str] = {}
    for line in git(root, "ls-tree", "-r", revision).splitlines():
        meta, _, path = line.partition("\t")
        parts = meta.split()
        if len(parts) < 3 or not path:
            continue
        entries[path] = parts[2]
    return entries


def read_client_version(root: Path, revision: str) -> str:
    document = json.loads(show(root, revision, BUILTIN_MANIFEST))
    version = str(document.get("provenance", {}).get("client_version", "")).strip()
    if not version:
        raise InputError(f"{BUILTIN_MANIFEST} names no client_version at {revision}")
    return version


def inputs_at(root: Path, revision: str) -> dict[str, str]:
    """The artifact's input set at one revision: `{path: blob}`."""
    version = read_client_version(root, revision)
    prefix = f"localization/{version}/"
    entries = {path: blob for path, blob in ls_tree(root, revision).items()
               if path in MANIFESTS or path.startswith(prefix)}
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
    report: dict = {"before_revision": before, "after_revision": after,
                    "changed": True, "reason": "", "changed_paths": []}
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
    changed_paths = difference(before_entries, after_entries)
    report["changed_paths"] = changed_paths
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--before", default=os.environ.get("BEFORE_SHA", ""),
                        help="the commit this push supersedes (github.event.before)")
    parser.add_argument("--after", default=os.environ.get("AFTER_SHA", "HEAD"),
                        help="the pushed commit (github.sha)")
    parser.add_argument("--github-output", action="store_true",
                        help="append dispatch/reason to $GITHUB_OUTPUT")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args()

    try:
        report = decide(args.root, args.before, args.after)
    except Exception as exc:  # never turn an unreadable input into a skip
        report = {"changed": True, "reason": "decision_failed", "detail": str(exc),
                  "changed_paths": []}

    if args.github_output:
        target = os.environ.get("GITHUB_OUTPUT", "")
        if target:
            with open(target, "a", encoding="utf-8") as stream:
                write_github_output(report, stream)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"dispatch={report['changed']} reason={report['reason']}")
        if report.get("changed_paths"):
            print("changed artifact inputs: " + ", ".join(report["changed_paths"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
