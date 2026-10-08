from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


llm = module('llm_translate_untranslated')
dispatch = module('dispatch_private_build')


class TranslationPipelineTests(unittest.TestCase):
    def fixture(self, root, rows):
        source = root / 'localization/9.0.200/runtime-bi-zhcn.json'
        source.parent.mkdir(parents=True)
        source.write_text(json.dumps({'kind': 'mltd-apk-runtime-bi-source', 'rows': rows}, ensure_ascii=False), encoding='utf-8')
        (root / 'manifests').mkdir()
        manifest = {'provenance': {'client_version': '9.0.200'}, 'surfaces': [
            {'translation_source': {'relative_path': source.relative_to(root).as_posix(), 'sha256': 'stale', 'bytes': 0}}]}
        (root / 'manifests/apk-builtin.manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        return source

    def test_dedup_apply_updates_duplicate_records_and_refreshes_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [{'ja': '続ける {0}', 'zh': '', 'translatable': True, 'status': 'untranslated', 'key': key}
                    for key in ('a', 'a', 'b')]
            source = self.fixture(root, rows)
            queue, draft = root / 'queue.jsonl', root / 'draft.jsonl'
            with patch.object(llm, 'ROOT', root):
                llm.collect(argparse.Namespace(output=queue))
                self.assertEqual(len(queue.read_text(encoding='utf-8').splitlines()), 1)
                entry = json.loads(queue.read_text(encoding='utf-8'))
                entry['translation'] = '继续 {0}'
                draft.write_text(json.dumps(entry, ensure_ascii=False), encoding='utf-8')
                llm.apply(argparse.Namespace(draft=draft))
            self.assertEqual([r['zh'] for r in json.loads(source.read_text(encoding='utf-8'))['rows']], ['继续 {0}'] * 3)
            metadata = json.loads((root / 'manifests/apk-builtin.manifest.json').read_text())['surfaces'][0]['translation_source']
            self.assertEqual(metadata['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(metadata['bytes'], source.stat().st_size)

    def test_delimiters_and_placeholders_cannot_corrupt_bi(self):
        for translation in ('继续', '继续 {1}', '继续 {0}|a^b', '继续 {0}\0'):
            with self.subTest(translation=translation), self.assertRaises(ValueError):
                llm.validate_translation('続ける {0}', translation)

    def test_dispatch_waits_for_complete_translation_and_preserves_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.fixture(root, [{'ja': '続ける', 'zh': '', 'status': 'untranslated', 'translatable': True}])
            commit = 'a' * 40
            self.assertIsNone(dispatch.payload(root, 'owner/client', commit))
            doc = json.loads(source.read_text(encoding='utf-8'))
            doc['rows'][0].update(zh='继续', status='accepted')
            source.write_text(json.dumps(doc), encoding='utf-8')
            event = dispatch.payload(root, 'owner/client', commit)
            self.assertEqual(event['client_payload']['client_commit'], commit)
            self.assertEqual(event['client_payload']['client_version'], '9.0.200')
            (root / 'manifests/apk-source-state.json').write_text(json.dumps({'build_supported': False}), encoding='utf-8')
            self.assertIsNone(dispatch.payload(root, 'owner/client', commit))


if __name__ == '__main__':
    unittest.main()
