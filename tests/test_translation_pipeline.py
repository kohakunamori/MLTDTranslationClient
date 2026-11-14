from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from scripts import translation_pipeline as pipeline

ROOT = Path(__file__).resolve().parents[1]


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / f'{name}.py')
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


dispatch = module('dispatch_private_build')


class TranslationPipelineTests(unittest.TestCase):
    def test_domain_pipeline_runs_without_cli_arguments(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root, [{'ja': '続ける', 'zh': '', 'status': 'untranslated'}])
            queue = root / 'queue.jsonl'

            result = pipeline.TranslationPipeline(root).collect(queue)

            self.assertEqual(result['items'], 1)
            self.assertEqual(json.loads(queue.read_text(encoding='utf-8'))['source'], '続ける')

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
            pipeline.TranslationPipeline(root).collect(queue)
            self.assertEqual(len(queue.read_text(encoding='utf-8').splitlines()), 1)
            entry = json.loads(queue.read_text(encoding='utf-8'))
            entry['translation'] = '继续 {0}'
            draft.write_text(json.dumps(entry, ensure_ascii=False), encoding='utf-8')
            pipeline.TranslationPipeline(root).apply(draft)
            self.assertEqual([r['zh'] for r in json.loads(source.read_text(encoding='utf-8'))['rows']], ['继续 {0}'] * 3)
            metadata = json.loads((root / 'manifests/apk-builtin.manifest.json').read_text())['surfaces'][0]['translation_source']
            self.assertEqual(metadata['sha256'], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertEqual(metadata['bytes'], source.stat().st_size)

    def test_delimiters_and_placeholders_cannot_corrupt_bi(self):
        for translation in ('继续', '继续 {1}', '继续 {0}|a^b', '继续 {0}\0'):
            with self.subTest(translation=translation), self.assertRaises(ValueError):
                pipeline.validate_translation('続ける {0}', translation)

    def test_corrupted_scripts_extb_meta_and_tw_calques_are_rejected(self):
        for source_text, bad_zh in (
            ('お知らせ', '通知Привет'),
            ('お知らせ', '알림通知'),
            ('通知', 'แจ้ง通知'),
            ('魚', '红\U0002B810'),
            ('ガシャ', '抽转蛋'),
            ('プッシュ通知', '推播通知'),
            ('メッセージ', '关闭此讯息'),
            ('最終ログイン', '最后登入'),
            ('獲得履歴', '获得履历'),
            ('テスト', '测试（译者注）'),
        ):
            with self.subTest(source=source_text, bad_zh=bad_zh), self.assertRaises(ValueError):
                pipeline.validate_translation(source_text, bad_zh)
        pipeline.validate_translation('テスト', '简体中文测试')

    def test_collect_reuses_lf_crlf_equivalent_accepted_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [
                {'ja': '一行目\n二行目', 'zh': '第一行\n第二行', 'status': 'accepted'},
                {'ja': '一行目\r\n二行目', 'zh': '', 'status': 'untranslated'},
            ]
            source = self.fixture(root, rows)
            queue = root / 'queue.jsonl'
            result = pipeline.TranslationPipeline(root).collect(queue)
            self.assertEqual(result['reused'], 1)
            self.assertEqual(result['items'], 0)
            saved = json.loads(source.read_text(encoding='utf-8'))['rows']
            self.assertEqual(saved[1]['zh'], '第一行\n第二行')
            self.assertEqual(saved[1]['status'], 'accepted')

    def test_provider_error_banners_are_rejected_and_not_applied(self):
        tos_banner = (
            '⚠ This service has been disabled in this account for violation of '
            'Terms of Service. Please submit an appeal to continue using this product.'
        )
        with self.assertRaises(ValueError):
            pipeline.validate_translation('通信に失敗しました', tos_banner)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.fixture(root, [{'ja': '通信に失敗しました', 'zh': '', 'translatable': True, 'status': 'untranslated'}])
            queue, draft = root / 'queue.jsonl', root / 'draft.jsonl'
            pipeline.TranslationPipeline(root).collect(queue)
            entry = json.loads(queue.read_text(encoding='utf-8'))
            entry['translation'] = tos_banner
            draft.write_text(json.dumps(entry, ensure_ascii=False), encoding='utf-8')
            report = pipeline.TranslationPipeline(root).apply(draft)
            self.assertEqual(report['updated'], 0)
            self.assertEqual(report['rejected'], 1)
            row = json.loads(source.read_text(encoding='utf-8'))['rows'][0]
            self.assertEqual(row['status'], 'untranslated')
            self.assertEqual(row['zh'], '')

    def test_unrecognized_english_prose_and_warning_banners_are_rejected_without_breaking_short_terms(self):
        for translation in (
            '⚠ Gateway maintenance',
            'Please verify your credentials before making another translation request.',
            'Your request cannot finish right now because credentials expired.',
        ):
            with self.subTest(rejected=translation), self.assertRaises(ValueError):
                pipeline.validate_translation('通信に失敗しました {0}', translation + ' {0}' if '{0}' not in translation else translation)
        for source_text, accepted in (
            ('シアターデイズ', 'Theater Days'),
            ('ネオユニバースブライト', 'Neo Universe Bright'),
            ('コスト', 'Cost'),
            ('Theater Days', 'Theater Days'),
            ('LIVEの準備', 'LIVE准备'),
        ):
            with self.subTest(source=source_text, accepted=accepted):
                pipeline.validate_translation(source_text, accepted)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.fixture(root, [{'ja': '通信に失敗しました', 'zh': '', 'translatable': True, 'status': 'untranslated'}])
            queue, draft = root / 'queue.jsonl', root / 'draft.jsonl'
            pipeline.TranslationPipeline(root).collect(queue)
            entry = json.loads(queue.read_text(encoding='utf-8'))
            entry['translation'] = 'Please verify your credentials before making another translation request.'
            draft.write_text(json.dumps(entry, ensure_ascii=False), encoding='utf-8')
            report = pipeline.TranslationPipeline(root).apply(draft)
            self.assertEqual(report['updated'], 0)
            self.assertEqual(report['rejected'], 1)
            row = json.loads(source.read_text(encoding='utf-8'))['rows'][0]
            self.assertEqual(row['status'], 'untranslated')
            self.assertEqual(row['zh'], '')

    def test_collect_reuses_unambiguous_accepted_sources_without_provider_calls(self):
        for choices, expected in ((['继续 {0}'], 0), (['继续 {0}', '接着 {0}'], 1)):
            with self.subTest(choices=choices), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                rows = [{'ja': '続ける {0}', 'zh': zh, 'status': 'accepted'} for zh in choices]
                rows.append({'ja': '続ける {0}', 'zh': '', 'status': 'untranslated'})
                source = self.fixture(root, rows)
                queue = root / 'queue.jsonl'
                pipeline.TranslationPipeline(root).collect(queue)
                self.assertEqual(len(queue.read_text(encoding='utf-8').splitlines()), expected)
                last = json.loads(source.read_text(encoding='utf-8'))['rows'][-1]
                self.assertEqual(last['zh'], choices[0] if not expected else '')

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

    def test_unknown_version_dispatches_bound_recovery_without_changing_old_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root, [])
            path = root / 'localization/9.0.300/runtime-bi-zhcn.json'
            path.parent.mkdir()
            doc = {'kind': 'mltd-apk-runtime-bi-source', 'client_version': '9.0.300',
                   'source_apk_sha256': 'a' * 64, 'rows': [
                       {'translatable': True, 'status': 'accepted', 'zh': '继续'}]}
            path.write_text(json.dumps(doc))
            (root / 'manifests/apk-source-state.json').write_text(json.dumps({
                'build_supported': False, 'client_version': '9.0.300',
                'source_identity': {'client_version': '9.0.300', 'version_code': 90300},
                'source_apk_sha256': 'a' * 64, 'source_split_sha256': 'b' * 64}))
            event = dispatch.recovery_payload(root, 'owner/client', 'c' * 40)
            self.assertEqual(event['event_type'], 'client-native-recovery-requested')
            self.assertEqual(event['client_payload']['client_version'], '9.0.300')
            with (patch.object(dispatch, 'ROOT', root),
                  patch('sys.argv', ['dispatch_private_build', '--repository', 'owner/client',
                                     '--commit', 'c' * 40, '--auto-route']),
                  patch.object(dispatch.subprocess, 'run') as request):
                self.assertEqual(dispatch.main(), 0)
                self.assertEqual(json.loads(request.call_args.kwargs['input']), event)
            doc['rows'][0]['status'] = 'untranslated'
            path.write_text(json.dumps(doc))
            self.assertIsNone(dispatch.recovery_payload(root, 'owner/client', 'c' * 40))

    def test_workflow_reports_provider_and_rejected_failures_before_settling_or_dispatching(self):
        workflow = (ROOT / '.github/workflows/llm-translate-client.yml').read_text(encoding='utf-8')
        ordered = [
            '- name: Commit Client text translations to main',
            '- name: Report provider failure after saving source progress',
            '- name: Report rejected formatting after preserving valid progress',
            '- name: Hold the notification for a merge window',
            '- name: Dispatch the exact translated Client commit to Private Build',
            '- name: Request native recovery for a new unsupported official APK',
        ]
        positions = [workflow.index(step) for step in ordered]
        self.assertEqual(positions, sorted(positions))

    def test_validate_translation_rejects_traditional_chars_tw_terms_and_invisible_unicode(self):
        for source_text, bad_zh in (
            ('エミリー', '艾蜜莉'),
            ('ブログ', '官方部落格'),
            ('ポップアップ', '显示弹跳视窗'),
            ('ホルダ', '资料夹'),
            ('アプリ', '应用程式'),
            ('キャッシュ', '快取资料'),
            ('白石紬', '白石紬'),
            ('白石紬', '白石䋾'),
            ('白石紬', '白石纺'),
            ('篠宮可憐', '筿宫可怜'),
            ('エミリー　スチュアート', '艾米莉‧司徒亚特'),
            ('エミリー　スチュアート', '艾米莉・斯图亚特'),
            ('エミリー　スチュアート', '艾米莉 斯图亚特'),
            ('ソロコレ発売', 'ソROCOレ发售'),
            ('ソロコレ発売', 'ROCO发售'),
            ('松田亜利沙', '松田有栖'),
            ('三浦あずさ', '三浦秋月'),
            ('徳川まつり', '德川玛茜'),
            ('徳川まつり', '德川小祭'),
            ('馬場このみ', '马场木乃美'),
            ('馬場このみ', '这位小美'),
            ('高槻やよい', '高槻やよ伊'),
            ('スタイルドロップ', '风格掉落物'),
            ('マスタースタイルドロップ', '大师造型水滴'),
            ('ネトスワで話題', '在网滑上很火'),
            ('ログイン', '登入'),
            ('ガシャ履歴', '扭蛋履历'),
            ('テスト', '這裡是測試'),
            ('そうです', '就是这样的说！'),
            ('通知', '通知\u200b'),
            ('通知', '通知\ue000'),
            ('通知', '通知[::thought]'),
            ('通知', '变成：\n\n通知'),
            ('あずさの写真', 'あず莎的照片'),
            ('ジュニオール', '是ジュ尼奥尔？'),
            ('ジュリアーノ', '问茱莉亚ーノ'),
            ('わたくし', '关于わたくし的事'),
            ('わざと', '故意に露出破绽'),
            ('全力でお届けするのです！', 'まつり会竭尽全力！'),
            ('悪い意味じゃなくて', '没有别的意思'),
            ('バイクで来た', '骑自行车来的'),
            ('劇は盛り上がってます', '演出很热闹'),
        ):
            with self.subTest(source=source_text, bad=bad_zh), self.assertRaises(ValueError):
                pipeline.validate_translation(source_text, bad_zh)
        pipeline.validate_translation('履歴書', '履历表')
        pipeline.validate_translation('篠宮可憐', '篠宫可怜')
        pipeline.validate_translation('有名な著者', '知名著者')
        pipeline.validate_translation('田所あずささんと三浦あずさ', '田所あずさ与三浦梓')
        pipeline.validate_translation('三浦 あずさ', '三浦 梓')
        pipeline.validate_translation('徳川 まつり', '德川 茉莉')
        pipeline.validate_translation('馬場 このみ', '马场 木实')
        pipeline.validate_translation('このみさんとこの景色', '木实与这美景')
        pipeline.validate_translation('まつり湯', 'まつり汤')
        pipeline.validate_translation('ロコのソロコレ', 'ROCO的个人精选')
        pipeline.validate_translation('マスタースタイルドロップ', '大师风格水滴')
        pipeline.validate_translation('ネトスワで話題', '在NetSwipes上引发热议')
        pipeline.validate_translation('スタローコラボカフェ', 'スタロー联动咖啡')
        pipeline.validate_translation('悪い意味じゃなくて', '不是说不好，只是觉得自然')
        pipeline.validate_translation('マウンテンバイク', '山地自行车')
        pipeline.validate_translation('自転車とバイク', '自行车与摩托车')
        pipeline.validate_translation('劇が盛り上がる', '这出剧很热闹')

    def test_collect_and_apply_handle_crlf_equivalence_and_u2028(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self.fixture(root, [
                {'ja': '一行\r\n二行', 'zh': '', 'translatable': True, 'status': 'untranslated'},
                {'ja': '一行\n二行', 'zh': '', 'translatable': True, 'status': 'untranslated'},
            ])
            queue, draft = root / 'queue.jsonl', root / 'draft.jsonl'
            collected = pipeline.TranslationPipeline(root).collect(queue)
            self.assertEqual(collected['items'], 1)
            entry = json.loads(queue.read_text(encoding='utf-8'))
            entry['translation'] = '第一行\u2028第二行'
            draft.write_text(json.dumps(entry, ensure_ascii=False) + '\r\n', encoding='utf-8')
            report = pipeline.TranslationPipeline(root).apply(draft)
            self.assertEqual(report['updated'], 2)
            rows = json.loads(source.read_text(encoding='utf-8'))['rows']
            self.assertEqual([r['zh'] for r in rows], ['第一行\u2028第二行', '第一行\u2028第二行'])

    def test_shared_text_populates_untranslated_component_row(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ja = '設定'
            sid = pipeline.source_id(ja)
            self.fixture(root, [])
            comp_path = root / 'localization/9.0.200/component-text-zhcn.json'
            comp_path.write_text(json.dumps({
                'kind': 'mltd-apk-component-text',
                'client_version': '9.0.200',
                'rows': [{'ja': ja, 'zh': '', 'status': 'untranslated', 'source_sha256': sid}],
            }, ensure_ascii=False), encoding='utf-8')
            manifest = json.loads((root / 'manifests/apk-builtin.manifest.json').read_text(encoding='utf-8'))
            manifest['surfaces'].append({
                'name': 'component-text',
                'translation_source': {'relative_path': comp_path.relative_to(root).as_posix(), 'sha256': '0' * 64, 'bytes': 0},
            })
            (root / 'manifests/apk-builtin.manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
            shared_dir = root / 'localization/shared'
            shared_dir.mkdir(parents=True)
            (shared_dir / 'apk-text-zhcn.json').write_text(json.dumps({
                'kind': 'mltd-shared-apk-text',
                'schema_version': 1,
                'images_enabled': False,
                'rows': [{
                    'ja': ja,
                    'zh': '设置',
                    'status': 'accepted',
                    'source_sha256': sid,
                    'translatable': True,
                    'translation_stage': 'llm_translated',
                    'updated_at': '2026-11-14T00:00:00Z',
                    'contexts': [{
                        'surface': 'component',
                        'client_version': '9.0.200',
                        'apk_sha256': '0' * 64,
                        'field_semantics_verified': True,
                        'identity': 'resources.assets:1:Text',
                    }],
                }],
            }, ensure_ascii=False), encoding='utf-8')
            pipeline.TranslationPipeline(root).refresh_source_hashes()
            updated = json.loads(comp_path.read_text(encoding='utf-8'))['rows'][0]
            self.assertEqual(updated['zh'], '设置')
            self.assertEqual(updated['status'], 'accepted')


if __name__ == '__main__':
    unittest.main()
