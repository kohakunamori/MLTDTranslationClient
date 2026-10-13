#!/usr/bin/env python3
"""Hold a private-build notification for a merge window before it dispatches.

Why this exists
---------------
Every notification the Client sends the private APK build is bound to one exact
Client commit: for a ``repository_dispatch`` the build pins itself to the commit
in the payload and refuses to re-pin to a newer one, so a forgotten notification
is a release that never happens.  The cost of that correctness is that a *burst*
of notifications - a translation run that commits, a maintainer push, another
translation run two minutes later - buys one full Windows build per commit, and
an intermediate commit's build is superseded before anyone can use it.

The repository already refuses to lose a notification by queueing them
(``cancel-in-progress: false``), which is right: cancelling a run that is already
signing is pure loss.  What it does not do is stop the *superseded* build from
starting at all.

This gate adds that missing half.  It is deliberately an observation, never a
decision the build depends on:

  * it waits ``--settle-seconds``, so a burst has time to finish arriving;
  * it re-reads the branch head **after** the wait;
  * it stands down only when a newer commit changed the bytes the APK consumes.
    The comparison is the same ``artifact_inputs`` fingerprint the notification
    already uses, so "the newer commit delivers the same bytes" is not a guess:
    the build for the older commit would embed exactly what the newer one would.

When a newer commit changed the artifact inputs, that commit's own push
notification is what dispatches - a change to ``localization/<version>/`` or to
either binding manifest always matches the notifier's path filter, so standing
down cannot strand the content.  And when anything at all cannot be established -
an unreachable remote, a fetch that fails, an unreadable tree - the answer is
``dispatch=true``.  This gate may cost one build; it must never cost a release.

Nothing here writes to the repository, reads a secret, or touches the build's
own gates.  The private poller, the input lock, the release gate and the startup
verification remain exactly as they were: this only decides whether the cheap
notification is still worth sending.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

try:  # Keep the fingerprint definition in exactly one module.
    from scripts.artifact_inputs import decide as compare_inputs
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from artifact_inputs import decide as compare_inputs

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BRANCH = "main"
DEFAULT_REMOTE = "origin"
DEFAULT_SETTLE_SECONDS = 600
SHA_RE = re.compile(r"[0-9a-f]{40}")


def run_git(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=str(root), text=True, encoding="utf-8",
        errors="replace", stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )


def remote_head(root: Path, remote: str = DEFAULT_REMOTE, branch: str = DEFAULT_BRANCH) -> str | None:
    """Resolve ``<remote>/<branch>`` from the network, not from the local clone.

    The local remote-tracking ref is deliberately not used: this job may have
    checked out one commit several minutes ago, and the tracking ref would then
    answer with the head as it was *before* the wait.
    """
    result = run_git(root, "ls-remote", "--exit-code", remote, f"refs/heads/{branch}")
    if result.returncode != 0:
        return None
    line = (result.stdout or "").strip().splitlines()
    if len(line) != 1:
        return None
    sha = line[0].split("\t", 1)[0].strip().lower()
    return sha if SHA_RE.fullmatch(sha) else None


def have_revision(root: Path, revision: str) -> bool:
    return run_git(root, "cat-file", "-e", f"{revision}^{{commit}}").returncode == 0


def fetch_revision(root: Path, branch: str = DEFAULT_BRANCH) -> str | None:
    """Materialise one revision's tree without thinning the checked-out commit.

    ``--depth=1`` keeps this cheap, and it decides nothing on its own: the
    artifact input set is a tree listing, and a shallow commit still carries its
    full tree, so ``ls-tree`` and ``show`` answer exactly as they would on a full
    clone. The branch is fetched rather than the raw object so an ordinary
    hosting remote never has to serve an unadvertised commit.

    Returns the fetched tip, or ``None`` when the fetch did not succeed.
    """
    result = run_git(
        root, "fetch", "--depth=1", "--no-tags", "--quiet",
        DEFAULT_REMOTE, f"refs/heads/{branch}",
    )
    if result.returncode != 0:
        return None
    tip = run_git(root, "rev-parse", "FETCH_HEAD")
    sha = (tip.stdout or "").strip().lower()
    return sha if SHA_RE.fullmatch(sha) else None


def settle(
    root: Path,
    target: str,
    *,
    settle_seconds: int = DEFAULT_SETTLE_SECONDS,
    remote: str = DEFAULT_REMOTE,
    branch: str = DEFAULT_BRANCH,
    sleeper=time.sleep,
) -> dict:
    """Answer whether ``target`` should still notify the private build.

    Never raises, and never answers "skip" from an uncertainty: only a proven
    newer artifact-input set stands a notification down.
    """
    report: dict = {
        "target_revision": target,
        "settle_seconds": settle_seconds,
        "dispatch": True,
        "reason": "",
        "head_revision": None,
    }
    target = (target or "").strip().lower()
    if not SHA_RE.fullmatch(target):
        report["reason"] = "target_unreadable"
        return report

    if settle_seconds and settle_seconds > 0:
        sleeper(settle_seconds)

    head = remote_head(root, remote, branch)
    report["head_revision"] = head
    if head is None:
        report["reason"] = "head_unreadable"
        return report

    if head == target:
        report["reason"] = "head_is_target"
        return report

    # The head moved while this run waited. Whether that matters depends on one
    # thing only: do the two commits deliver the same bytes into the APK?
    if not have_revision(root, head):
        # A one-commit-deep checkout never saw the newer tip. Fetch it; a fetch
        # that fails leaves the question unanswered, and an unanswered question
        # dispatches.
        if fetch_revision(root, branch) is None or not have_revision(root, head):
            report["reason"] = "newer_head_unreadable"
            return report

    try:
        comparison = compare_inputs(root, target, head)
    except Exception as exc:  # pragma: no cover - defensive; decide() answers instead
        report["reason"] = "comparison_failed"
        report["detail"] = str(exc)
        return report

    report["comparison_reason"] = comparison.get("reason")
    report["target_fingerprint"] = comparison.get("before_fingerprint")
    report["head_fingerprint"] = comparison.get("after_fingerprint")
    if comparison.get("before_fingerprint") and (
        comparison.get("before_fingerprint") == comparison.get("after_fingerprint")
    ):
        # A newer commit exists but delivers the identical artifact input set:
        # building ``target`` produces what building ``head`` would, so this
        # notification is still the newest content and must be sent.
        report["reason"] = "newer_head_delivers_same_inputs"
        return report

    if comparison.get("reason") == "artifact_inputs_changed":
        report["dispatch"] = False
        report["reason"] = "superseded_by_newer_inputs"
        report["changed_paths"] = comparison.get("changed_paths", [])[:20]
        return report

    # No baseline could be read (a shallow clone without the parent, an unknown
    # revision). Unverified is not unchanged: dispatch.
    report["reason"] = "comparison_unverified"
    return report


def write_github_output(report: dict, stream) -> None:
    stream.write("dispatch=" + ("true" if report["dispatch"] else "false") + "\n")
    stream.write("reason=" + str(report.get("reason", "")) + "\n")
    stream.write("head_revision=" + str(report.get("head_revision") or "") + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--target", default=os.environ.get("TARGET_SHA", ""),
                        help="the Client commit this notification carries")
    parser.add_argument("--settle-seconds", type=int,
                        default=int(os.environ.get("SETTLE_SECONDS", DEFAULT_SETTLE_SECONDS)),
                        help="merge window; 0 reads the head once and never waits")
    parser.add_argument("--remote", default=DEFAULT_REMOTE)
    parser.add_argument("--branch", default=DEFAULT_BRANCH)
    parser.add_argument("--github-output", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    report = settle(
        args.root, args.target,
        settle_seconds=args.settle_seconds, remote=args.remote, branch=args.branch,
    )
    if args.github_output:
        target = os.environ.get("GITHUB_OUTPUT", "")
        if target:
            with open(target, "a", encoding="utf-8") as stream:
                write_github_output(report, stream)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    else:
        print(f"dispatch={report['dispatch']} reason={report['reason']} "
              f"head={report.get('head_revision')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
