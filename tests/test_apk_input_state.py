from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


state = module('apk_input_state')


class Repository:
    """A throwaway git repository holding a two-version Client tree."""

    def __init__(self, root: Path):
        self.root = root
        subprocess.run(['git', 'init', '-q'], cwd=root, check=True)
        self.write('manifests/apk-builtin.manifest.json', self.builtin('9.0.300'))
        self.write('manifests/bottom-bar.manifest.json', json.dumps({'kind': 'mltd-bottom-bar-manifest'}))
        for version in ('9.0.200', '9.0.300'):
            self.write(f'localization/{version}/runtime-bi-zhcn.json', json.dumps({'client_version': version}))
            self.write(f'localization/{version}/visuals/bottom-bar-off-v5.png', 'original-pixels')
        self.write('manifests/portal-resource-manifest.json', json.dumps({'totals': {}}))
        self.commit('base')

    @staticmethod
    def builtin(version):
        return json.dumps({'kind': 'mltd-apk-builtin-manifest',
                           'provenance': {'client_version': version, 'axis': 'client'}})

    def write(self, relative, text):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def commit(self, message):
        subprocess.run(['git', '-c', 'user.email=ci@example.invalid', '-c', 'user.name=ci',
                        'add', '-A'], cwd=self.root, check=True)
        subprocess.run(['git', '-c', 'user.email=ci@example.invalid', '-c', 'user.name=ci',
                        'commit', '-q', '-m', message], cwd=self.root, check=True)
        return subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=self.root, check=True,
                              text=True, stdout=subprocess.PIPE).stdout.strip()


class ArtifactInputDecisionTests(unittest.TestCase):
    def fixture(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        repository = Repository(Path(directory.name))
        return repository

    def test_a_commit_that_cannot_reach_the_apk_does_not_ask_for_a_build(self):
        """The whole point: bookkeeping and tooling edits must not notify."""
        repository = self.fixture()
        base = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repository.root, check=True,
                              text=True, stdout=subprocess.PIPE).stdout.strip()
        repository.write('manifests/apk-source-state.json', json.dumps({'build_supported': True}))
        repository.write('manifests/portal-resource-manifest.json', json.dumps({'totals': {'total': 1}}))
        repository.write('docs/LLM_TRANSLATION.md', 'notes')
        head = repository.commit('bookkeeping only')

        report = state.decide(repository.root, base, head)

        self.assertFalse(report['changed'])
        self.assertEqual(report['reason'], 'artifact_inputs_unchanged')
        self.assertEqual(report['changed_paths'], [])

    def test_a_change_to_another_version_directory_does_not_ask_for_a_build(self):
        """9.0.200 is history here: the manifest delivers 9.0.300 into the APK."""
        repository = self.fixture()
        base = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repository.root, check=True,
                              text=True, stdout=subprocess.PIPE).stdout.strip()
        repository.write('localization/9.0.200/runtime-bi-zhcn.json', json.dumps({'client_version': '9.0.200', 'rows': []}))
        repository.write('localization/9.0.200/apk-ui-strings-zhcn.json', '{"slots": []}')
        head = repository.commit('old version edit')

        report = state.decide(repository.root, base, head)

        self.assertFalse(report['changed'], report)
        self.assertEqual(report['after_client_version'], '9.0.300')

    def test_a_change_to_the_active_translation_source_asks_for_a_build(self):
        repository = self.fixture()
        base = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repository.root, check=True,
                              text=True, stdout=subprocess.PIPE).stdout.strip()
        repository.write('localization/9.0.300/runtime-bi-zhcn.json',
                         json.dumps({'client_version': '9.0.300', 'rows': [{'zh': '剧场'}]}))
        head = repository.commit('translation update')

        report = state.decide(repository.root, base, head)

        self.assertTrue(report['changed'], report)
        self.assertEqual(report['reason'], 'artifact_inputs_changed')
        self.assertIn('localization/9.0.300/runtime-bi-zhcn.json', report['changed_paths'])

    def test_a_change_to_the_manifests_that_bind_the_sources_asks_for_a_build(self):
        for relative in ('manifests/apk-builtin.manifest.json', 'manifests/bottom-bar.manifest.json'):
            with self.subTest(relative=relative):
                repository = self.fixture()
                base = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repository.root, check=True,
                                      text=True, stdout=subprocess.PIPE).stdout.strip()
                current = (repository.root / relative).read_text(encoding='utf-8')
                repository.write(relative, current.replace('mltd-', 'mltd-bound-'))
                head = repository.commit('manifest edit')

                self.assertTrue(state.decide(repository.root, base, head)['changed'])

    def test_an_unchanged_artifact_is_unchanged_even_across_a_revert(self):
        repository = self.fixture()
        base = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repository.root, check=True,
                              text=True, stdout=subprocess.PIPE).stdout.strip()
        repository.write('localization/9.0.300/runtime-bi-zhcn.json', json.dumps({'rows': [{'zh': '偶像'}]}))
        edited = repository.commit('translation edit')
        repository.write('localization/9.0.300/runtime-bi-zhcn.json', json.dumps({'client_version': '9.0.300'}))
        reverted = repository.commit('revert the edit')

        self.assertTrue(state.decide(repository.root, base, edited)['changed'])
        self.assertTrue(state.decide(repository.root, edited, reverted)['changed'])
        self.assertFalse(state.decide(repository.root, base, reverted)['changed'])

    def test_switching_the_active_version_asks_for_a_build(self):
        repository = self.fixture()
        base = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repository.root, check=True,
                              text=True, stdout=subprocess.PIPE).stdout.strip()
        repository.write('manifests/apk-builtin.manifest.json', Repository.builtin('9.0.200'))
        head = repository.commit('move the active version back')

        report = state.decide(repository.root, base, head)

        self.assertTrue(report['changed'], report)
        self.assertEqual(report['after_client_version'], '9.0.200')

    def test_every_uncertain_answer_asks_for_the_build(self):
        cases = {
            'empty baseline': ('', 'HEAD'),
            'null baseline': ('0' * 40, 'HEAD'),
            'unknown baseline': ('f' * 40, 'HEAD'),
            'unknown head': ('HEAD', 'f' * 40),
        }
        for label, (before, after) in cases.items():
            with self.subTest(label=label):
                repository = self.fixture()
                report = state.decide(repository.root, before, after)
                self.assertTrue(report['changed'], report)
                self.assertIn(report['reason'], ('no_baseline', 'baseline_unreadable'))

    def test_the_cli_reports_the_decision_to_the_workflow(self):
        repository = self.fixture()
        base = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=repository.root, check=True,
                              text=True, stdout=subprocess.PIPE).stdout.strip()
        repository.write('localization/9.0.300/runtime-bi-zhcn.json', json.dumps({'rows': [{'zh': '导航'}]}))
        head = repository.commit('translation update')
        output = repository.root / 'github-output.txt'
        environment = dict(os.environ, GITHUB_OUTPUT=str(output))
        script = ROOT / 'scripts' / 'apk_input_state.py'

        for before, expected in ((base, 'dispatch=true'), (head, 'dispatch=false')):
            output.write_text('', encoding='utf-8')
            result = subprocess.run(['python', str(script), '--root', str(repository.root),
                                     '--before', before, '--after', head, '--github-output'],
                                    text=True, stdout=subprocess.PIPE, env=environment, check=False)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertIn(expected, output.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
