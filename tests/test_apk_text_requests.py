from __future__ import annotations
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts import apk_text_requests as requests
from scripts.translation_pipeline import source_id, TranslationPipeline, validate_translation


def request():
    source = '続ける %1$s'
    return {'kind': 'mltd-client-text-request', 'schema_version': 1, 'images_enabled': False,
            'checkpoint_key': 'a' * 64, 'adaptation_id': 'b' * 64,
            'source': {'client_version': '8.0.750', 'source_apk_sha256': 'c' * 64},
            'rows': [{'source': source, 'source_sha256': source_id(source), 'contexts': [{
                'client_version': '8.0.750', 'apk_sha256': 'c' * 64, 'identity': 'data:1:MonoBehaviour',
                'surface': 'component', 'field_semantics_verified': True}]}]}


class RequestTests(unittest.TestCase):
    def test_Client_workflow_owns_translation_and_never_acquires_or_scans_APKs(self):
        text = (Path(__file__).resolve().parents[1] / '.github/workflows/llm-translate-client.yml').read_text(encoding='utf-8')
        for forbidden in ('client.apk_resource_sync', 'client.apk_sync_preflight', 'UnityPy', '.apk-tools', 'requirements-client-ci'):
            self.assertNotIn(forbidden, text)
        self.assertIn('translate_mltd_api_pool.py', text)
        self.assertIn('MLTD_LLM_API_KEY', text)
        self.assertIn('scripts.apk_text_requests callback', text)
    def test_pending_import_reuses_existing_translation_and_callbacks_exact_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prior = root / 'localization/9.0.300/source.json'
            prior.parent.mkdir(parents=True)
            prior.write_text(json.dumps({'rows': [{'ja': '続ける %1$s', 'zh': '继续 %1$s', 'status': 'accepted'}]}), encoding='utf-8')
            manifest = root / 'manifests/apk-builtin.manifest.json'
            manifest.parent.mkdir()
            manifest.write_text(json.dumps({'surfaces': []}), encoding='utf-8')
            requests.import_request(root, request(), 123, 'd' * 64)
            self.assertEqual(requests.callbacks(root, 'e' * 40, 'kohakunamori/MLTDTranslationClient'), 0)
            result = TranslationPipeline(root).collect(root / 'queue.jsonl')
            self.assertEqual(result['reused'], 1)
            self.assertEqual(result['items'], 0)
            with patch.object(requests, 'gh', return_value=b'') as gh:
                self.assertEqual(requests.callbacks(root, 'e' * 40, 'kohakunamori/MLTDTranslationClient'), 1)
                body = gh.call_args.kwargs['body']
                self.assertEqual(body['client_payload']['commit'], 'e' * 40)
                self.assertEqual(body['client_payload']['checkpoint_key'], 'a' * 64)
            requests.import_request(root, request(), 123, 'd' * 64)
            self.assertEqual(len(requests.read_json(root / requests.CATALOGUE)['rows']), 1)

    def test_unverified_fields_images_wrong_hash_or_apk_are_rejected_before_write(self):
        for mutation in ('semantics', 'surface', 'hash', 'apk', 'images'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                doc = request()
                if mutation == 'semantics': doc['rows'][0]['contexts'][0]['field_semantics_verified'] = False
                if mutation == 'surface': doc['rows'][0]['contexts'][0]['surface'] = 'image'
                if mutation == 'hash': doc['rows'][0]['source_sha256'] = '0' * 64
                if mutation == 'apk': doc['rows'][0]['contexts'][0]['apk_sha256'] = '0' * 64
                if mutation == 'images': doc['images_enabled'] = True
                root = Path(directory)
                with self.assertRaises(ValueError):
                    requests.import_request(root, doc, 123, 'd' * 64)
                self.assertFalse((root / requests.CATALOGUE).exists())

    def test_positional_format_and_markup_survive_translation(self):
        validate_translation('<b>続ける %1$s {0}</b>', '<b>继续 %1$s {0}</b>')
        with self.assertRaises(ValueError):
            validate_translation('続ける %1$s', '继续 %2$s')

    def test_shared_component_translation_reaches_active_build_input(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / 'localization/9.0.300/component-text-zhcn.json'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'kind': 'mltd-apk-component-text', 'rows': [], 'android_rows': []}), encoding='utf-8')
            manifest = root / 'manifests/apk-builtin.manifest.json'
            manifest.parent.mkdir()
            manifest.write_text(json.dumps({'surfaces': [{'name': 'component-text', 'translation_source': {
                'relative_path': path.relative_to(root).as_posix(), 'sha256': 'old', 'bytes': 0}}]}), encoding='utf-8')
            requests.import_request(root, request(), 123, 'd' * 64)
            draft = root / 'draft.jsonl'
            draft.write_text(json.dumps({'source': '続ける %1$s', 'source_sha256': source_id('続ける %1$s'),
                                        'translation': '继续 %1$s'}), encoding='utf-8')
            TranslationPipeline(root).apply(draft)
            self.assertEqual(requests.read_json(path)['rows'][0]['zh'], '继续 %1$s')
            binding = requests.read_json(manifest)['surfaces'][0]['translation_source']
            self.assertEqual(binding['sha256'], requests.hashlib.sha256(path.read_bytes()).hexdigest())

    def test_bad_draft_keeps_pending_source_while_saving_valid_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            requests.import_request(root, request(), 123, 'd' * 64)
            manifest = root / 'manifests/apk-builtin.manifest.json'
            manifest.write_text('{"surfaces":[]}', encoding='utf-8')
            draft = root / 'draft.jsonl'
            draft.write_text(json.dumps({'source': '続ける %1$s', 'source_sha256': source_id('続ける %1$s'),
                                        'translation': '继续 %2$s'}), encoding='utf-8')
            result = TranslationPipeline(root).apply(draft)
            self.assertEqual(result['rejected'], 1)
            self.assertEqual(requests.read_json(root / requests.CATALOGUE)['rows'][0]['status'], 'untranslated')


if __name__ == '__main__':
    unittest.main()
