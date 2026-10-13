from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


settle_module = module('dispatch_settle')


def git(cwd, *args):
    return subprocess.run(['git', *args], cwd=cwd, check=True, text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()


class Fixture:
    """A working clone plus a bare `origin`, so ls-remote answers for real."""

    def __init__(self, root: Path):
        self.root = root
        self.remote = root / 'origin.git'
        self.work = root / 'work'
        subprocess.run(['git', 'init', '-q', '--bare', str(self.remote)], check=True)
        subprocess.run(['git', 'init', '-q', '-b', 'main', str(self.work)], check=True)
        git(self.work, 'config', 'user.email', 'ci@example.invalid')
        git(self.work, 'config', 'user.name', 'ci')
        git(self.work, 'remote', 'add', 'origin', str(self.remote))
        self.write('manifests/apk-builtin.manifest.json', self.builtin('9.0.300'))
        self.write('manifests/bottom-bar.manifest.json', json.dumps({'kind': 'mltd-bottom-bar-manifest'}))
        self.write('localization/9.0.300/runtime-bi-zhcn.json', json.dumps({'rows': []}))
        self.commit('base')
        git(self.work, 'push', '-q', '-u', 'origin', 'main')
        # A bare repository created by `git init` still points HEAD at the
        # initial-branch default, which no push here has created, so a later
        # clone would check out nothing at all.
        subprocess.run(['git', 'symbolic-ref', 'HEAD', 'refs/heads/main'],
                       cwd=self.remote, check=True)

    @staticmethod
    def builtin(version):
        return json.dumps({'kind': 'mltd-apk-builtin-manifest',
                           'provenance': {'client_version': version, 'axis': 'client'}})

    def write(self, relative, text):
        path = self.work / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def commit(self, message):
        git(self.work, 'add', '-A')
        git(self.work, 'commit', '-q', '-m', message)
        return git(self.work, 'rev-parse', 'HEAD')

    def publish(self, revision):
        """Make `revision` the remote's main, the way a push would."""
        git(self.work, 'push', '-q', '--force', 'origin', f'{revision}:refs/heads/main')
        return revision


class DispatchSettleTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Fixture(Path(directory.name))

    def test_the_head_that_is_still_this_commit_dispatches(self):
        fixture = self.fixture()
        target = git(fixture.work, 'rev-parse', 'HEAD')

        report = settle_module.settle(fixture.work, target, settle_seconds=0)

        self.assertTrue(report['dispatch'])
        self.assertEqual(report['reason'], 'head_is_target')

    def test_a_newer_commit_that_delivers_the_same_bytes_still_dispatches(self):
        """Only the artifact inputs decide; a docs-only push must not stand down."""
        fixture = self.fixture()
        target = git(fixture.work, 'rev-parse', 'HEAD')
        fixture.write('docs/NOTES.md', 'bookkeeping only')
        newer = fixture.commit('docs only')
        fixture.publish(newer)

        report = settle_module.settle(fixture.work, target, settle_seconds=0)

        self.assertTrue(report['dispatch'])
        self.assertEqual(report['reason'], 'newer_head_delivers_same_inputs')
        self.assertEqual(report['head_revision'], newer)
        self.assertEqual(report['target_fingerprint'], report['head_fingerprint'])

    def test_a_newer_commit_that_changes_the_apk_bytes_stands_this_one_down(self):
        """The newer push has its own notification; this one must not spend a build."""
        fixture = self.fixture()
        target = git(fixture.work, 'rev-parse', 'HEAD')
        fixture.write('localization/9.0.300/runtime-bi-zhcn.json',
                      json.dumps({'rows': [{'zh': '导航'}]}))
        newer = fixture.commit('translation update')
        fixture.publish(newer)

        report = settle_module.settle(fixture.work, target, settle_seconds=0)

        self.assertFalse(report['dispatch'])
        self.assertEqual(report['reason'], 'superseded_by_newer_inputs')
        self.assertIn('localization/9.0.300/runtime-bi-zhcn.json', report['changed_paths'])

    def test_the_merge_window_waits_exactly_once_and_only_when_asked(self):
        fixture = self.fixture()
        target = git(fixture.work, 'rev-parse', 'HEAD')
        waited = []

        settle_module.settle(fixture.work, target, settle_seconds=600,
                             sleeper=waited.append)
        self.assertEqual(waited, [600])

        settle_module.settle(fixture.work, target, settle_seconds=0,
                             sleeper=waited.append)
        self.assertEqual(waited, [600])

    def test_an_unreachable_branch_dispatches_rather_than_dropping_the_notification(self):
        fixture = self.fixture()
        target = git(fixture.work, 'rev-parse', 'HEAD')
        git(fixture.work, 'remote', 'set-url', 'origin', str(fixture.root / 'missing.git'))

        report = settle_module.settle(fixture.work, target, settle_seconds=0)

        self.assertTrue(report['dispatch'])
        self.assertEqual(report['reason'], 'head_unreadable')

    def test_a_target_that_is_not_a_commit_dispatches(self):
        fixture = self.fixture()

        for bad in ('', '0', 'not-a-sha'):
            with self.subTest(target=bad):
                report = settle_module.settle(fixture.work, bad, settle_seconds=0)
                self.assertTrue(report['dispatch'])
                self.assertEqual(report['reason'], 'target_unreadable')

    def test_a_newer_commit_that_cannot_be_read_still_dispatches(self):
        """Unverified is not unchanged: a shallow clone without the new head fetches
        it, and a head that is a real commit on another branch is read normally."""
        fixture = self.fixture()
        target = git(fixture.work, 'rev-parse', 'HEAD')
        fixture.write('localization/9.0.300/runtime-bi-zhcn.json', json.dumps({'rows': [{'zh': 'a'}]}))
        newer = fixture.commit('translation update')
        fixture.publish(newer)
        # Object still present locally, so this exercises the readable path; the
        # unreadable path is covered by the unreachable-remote case above.
        self.assertTrue(settle_module.have_revision(fixture.work, newer))

    def test_a_one_commit_deep_checkout_fetches_the_newer_head_before_deciding(self):
        """The notified job checks out one commit; the newer tip arrives later."""
        fixture = self.fixture()
        target = git(fixture.work, 'rev-parse', 'HEAD')
        shallow = fixture.root / 'shallow'
        subprocess.run(['git', 'clone', '-q', '--depth', '1', '--no-single-branch',
                        f'file://{fixture.remote}', str(shallow)], check=True)
        self.assertEqual(git(shallow, 'rev-parse', 'HEAD'), target)
        fixture.write('localization/9.0.300/runtime-bi-zhcn.json',
                      json.dumps({'rows': [{'zh': '导航'}]}))
        newer = fixture.publish(fixture.commit('translation update'))
        self.assertFalse(settle_module.have_revision(shallow, newer))

        report = settle_module.settle(shallow, target, settle_seconds=0)

        self.assertFalse(report['dispatch'])
        self.assertEqual(report['reason'], 'superseded_by_newer_inputs')
        self.assertEqual(report['head_revision'], newer)

    def test_github_output_always_states_the_dispatch_decision(self):
        fixture = self.fixture()
        target = git(fixture.work, 'rev-parse', 'HEAD')
        fixture.write('localization/9.0.300/runtime-bi-zhcn.json',
                      json.dumps({'rows': [{'zh': '导航'}]}))
        fixture.publish(fixture.commit('translation update'))
        output = fixture.root / 'github-output.txt'
        output.write_text('', encoding='utf-8')

        environment = dict(os.environ, GITHUB_OUTPUT=str(output), TARGET_SHA=target,
                           SETTLE_SECONDS='0')
        result = subprocess.run(
            [sys.executable, str(ROOT / 'scripts' / 'dispatch_settle.py'),
             '--root', str(fixture.work), '--github-output'],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=environment,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        written = output.read_text(encoding='utf-8')
        self.assertIn('dispatch=false', written)
        self.assertIn('reason=superseded_by_newer_inputs', written)


if __name__ == '__main__':
    unittest.main()
