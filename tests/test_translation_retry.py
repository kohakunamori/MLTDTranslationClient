import copy
import json
from pathlib import Path
import tempfile
import textwrap
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = 'owner/client'


def retry_script():
    workflow = (ROOT / '.github/workflows/retry-client-translation.yml').read_text(encoding='utf-8')
    source = workflow.split("python3 - <<'PY'\n", 1)[1].rsplit('\n          PY', 1)[0]
    return compile(textwrap.dedent(source), '<translation-retry>', 'exec')


class TranslationRetryTests(unittest.TestCase):
    def event_file(self, event):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / 'event.json'
        path.write_text(json.dumps(event), encoding='utf-8')
        return path

    def test_translation_retries_only_the_failed_current_attempt(self):
        trigger = {'id': 123, 'run_attempt': 1}
        current = {**trigger, 'repository': {'full_name': REPOSITORY},
                   'head_repository': {'full_name': REPOSITORY}, 'head_branch': 'main',
                   'path': '.github/workflows/llm-translate-client.yml',
                   'status': 'completed', 'conclusion': 'failure'}
        event_path = self.event_file({'workflow_run': trigger})
        for changes, retries in (({}, True), ({'run_attempt': 2}, False),
                                 ({'run_attempt': 3}, False), ({'status': 'in_progress'}, False),
                                 ({'conclusion': 'success'}, False), ({'head_branch': 'topic'}, False),
                                 ({'head_repository': {'full_name': 'other/fork'}}, False),
                                 ({'path': '.github/workflows/notify-private-build.yml'}, False)):
            with self.subTest(changes=changes):
                run = copy.deepcopy(current)
                run.update(changes)
                with (patch.dict('os.environ', GITHUB_EVENT_PATH=str(event_path),
                                 GITHUB_REPOSITORY=REPOSITORY, GITHUB_EVENT_NAME='workflow_run'),
                      patch('subprocess.check_output', return_value=json.dumps(run)),
                      patch('subprocess.run') as request):
                    exec(retry_script(), {})
                self.assertEqual(request.called, retries)
                if retries:
                    self.assertTrue(request.call_args.args[0][-1].endswith(
                        '/actions/runs/123/rerun-failed-jobs'))

    def test_manual_dispatch_translation_retry_recovers_a_missed_completion(self):
        workflow = (ROOT / '.github/workflows/retry-client-translation.yml').read_text(encoding='utf-8')
        self.assertIn('workflow_dispatch:', workflow)
        self.assertIn('workflow_run:', workflow)
        self.assertNotIn('schedule:', workflow)
        self.assertNotIn('cron:', workflow)

        run = {'id': 123, 'run_attempt': 2, 'repository': {'full_name': REPOSITORY},
               'head_repository': {'full_name': REPOSITORY}, 'head_branch': 'main',
               'path': '.github/workflows/llm-translate-client.yml',
               'status': 'completed', 'conclusion': 'failure'}
        event_path = self.event_file({})
        for status, retries in (('completed', True), ('in_progress', False)):
            with self.subTest(status=status):
                current = {**run, 'status': status}
                with (patch.dict('os.environ', GITHUB_EVENT_PATH=str(event_path),
                                 GITHUB_REPOSITORY=REPOSITORY, GITHUB_EVENT_NAME='workflow_dispatch'),
                      patch('subprocess.check_output', side_effect=[
                          json.dumps({'workflow_runs': [current]}), json.dumps(current)]),
                      patch('subprocess.run') as request):
                    exec(retry_script(), {})
                self.assertEqual(request.called, retries)
