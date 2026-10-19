"""Import verified APK text into shared Client resources."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import re
import subprocess

from scripts.repo_utils import read_json, write_json
from scripts.translation_pipeline import source_id, validate_translation

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = 'kohakunamori/MLTDModifiedAPK'
CATALOGUE = 'localization/shared/apk-text-zhcn.json'
MAX_BYTES = 4 * 1024 * 1024


def trusted_private_commit(commit):
    if not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Invalid private discovery commit')
    compared = json.loads(subprocess.check_output(
        ['gh', 'api', f'repos/{PRIVATE}/compare/{commit}...main']))
    if compared['status'] not in ('identical', 'ahead'):
        raise ValueError('Private discovery commit is not on main')


def validate_catalogue(doc):
    if (doc.get('kind') != 'mltd-shared-apk-text' or doc.get('schema_version') != 1
            or doc.get('images_enabled') is not False or not isinstance(doc.get('rows'), list) or len(doc['rows']) > 5000):
        raise ValueError('Invalid shared APK text catalogue')
    seen = set()
    for row in doc['rows']:
        ja, zh = row.get('ja'), row.get('zh')
        sid = row.get('source_sha256')
        if (not isinstance(ja, str) or not ja or not isinstance(zh, str) or sid != source_id(ja)
                or sid in seen or row.get('translatable') is not True):
            raise ValueError('Invalid shared APK text source')
        seen.add(sid)
        if row.get('status') == 'accepted' and zh.strip():
            validate_translation(ja, zh)
        elif row.get('status') != 'untranslated' or zh:
            raise ValueError('Invalid shared APK translation state')
        contexts = row.get('contexts')
        if not isinstance(contexts, list) or not contexts or len(contexts) > 2000:
            raise ValueError('Invalid shared APK text contexts')
        for context in contexts:
            if (context.get('surface') not in ('bi', 'component', 'android')
                    or context.get('field_semantics_verified') is not True
                    or not re.fullmatch('[0-9a-f]{64}', context.get('apk_sha256', ''))
                    or not re.fullmatch(r'\d+\.\d+\.\d+', context.get('client_version', ''))
                    or not isinstance(context.get('identity'), str)):
                raise ValueError('Unverified shared APK text field')


def import_request(root, doc):
    # Only the document the daily scan stages into this repository is accepted.
    # `mltd-client-text-request` carried the retired Release-asset pin, and no
    # producer emits it any more.
    if (doc.get('kind') != 'mltd-client-source-text' or doc.get('schema_version') != 1
            or doc.get('images_enabled') is not False or len(doc.get('rows', [])) > 5000):
        raise ValueError('Invalid APK text request')
    source = doc['source']
    path = root / CATALOGUE
    catalogue = read_json(path) if path.exists() else {
        'kind': 'mltd-shared-apk-text', 'schema_version': 1, 'images_enabled': False, 'rows': []}
    indexed = {row['source_sha256']: row for row in catalogue['rows']}
    pending = []
    for item in doc['rows']:
        sid, text = item['source_sha256'], item['source']
        if sid != source_id(text) or len(text.encode()) > 65536:
            raise ValueError('APK text source hash or budget mismatch')
        for context in item['contexts']:
            if (context['apk_sha256'] != source['source_apk_sha256']
                    or context['client_version'] != source['client_version']):
                raise ValueError('APK text context does not match original APK')
        row = indexed.setdefault(sid, {'ja': text, 'zh': '', 'source_sha256': sid,
                                     'status': 'untranslated', 'translatable': True, 'contexts': []})
        for context in item['contexts']:
            if context not in row['contexts']:
                row['contexts'].append(context)
        pending.append(sid)
    catalogue['rows'] = sorted(indexed.values(), key=lambda row: row['source_sha256'])
    validate_catalogue(catalogue)
    if catalogue['rows']:
        write_json(path, catalogue, sort_keys=True)
    return len(pending)


def import_local_scan(root):
    """Import a serialized queue; APK downloading/scanning belongs to Private Build."""
    state = read_json(root / 'manifests/apk-source-state.json')
    version = state['client_version']
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Invalid discovered Client version')
    path = root / 'localization' / version / 'discovery/automatic-text-request.json'
    if not path.exists():
        return 0
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Discovery text budget exceeded')
    doc = read_json(path)
    if doc.get('source') != {'client_version': version, 'source_apk_sha256': state['source_apk_sha256']}:
        raise ValueError('Private text queue and source manifest disagree')
    return import_request(root, doc)


def validate_source_event(event):
    payload = event['client_payload']
    if (payload.get('producer_repository') != PRIVATE
            or not re.fullmatch('[0-9a-f]{40}', payload.get('producer_commit', ''))
            or not re.fullmatch('[0-9a-f]{40}', payload.get('commit', ''))
            or not re.fullmatch('[1-9][0-9]*', str(payload.get('producer_run', '')))):
        raise ValueError('Invalid source discovery origin')
    if event.get('sender', {}).get('type') != 'Bot':
        raise ValueError('Source discovery is not trusted private CI')
    trusted_private_commit(payload['producer_commit'])
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    compared = json.loads(subprocess.check_output(
        ['gh', 'api', f'repos/kohakunamori/MLTDTranslationClient/compare/{payload["commit"]}...{head}']))
    if compared['status'] not in ('identical', 'ahead'):
        raise ValueError('Source discovery commit is not on the checked-out Client main')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['import-local-scan', 'validate-source-event'])
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    if args.command == 'import-local-scan':
        print(f'Imported {import_local_scan(args.root)} verified publisher text sources.')
    else:
        validate_source_event(read_json(Path(os.environ['GITHUB_EVENT_PATH'])))
        print('Private APK discovery origin verified.')
