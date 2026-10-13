"""Import verified APK text into shared Client resources and resume private CI."""
from __future__ import annotations
import argparse
import hashlib
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
REQUESTS = 'manifests/apk-text-requests.json'
MAX_BYTES = 4 * 1024 * 1024


def gh(*args, body=None):
    return subprocess.check_output(['gh', *args], input=json.dumps(body).encode() if body is not None else None)


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


def import_request(root, doc, asset_id, digest, *, record_request=True):
    if (doc.get('kind') not in ('mltd-client-text-request', 'mltd-client-source-text') or doc.get('schema_version') != 1
            or doc.get('images_enabled') is not False or len(doc.get('rows', [])) > 5000
            or (record_request and (doc.get('kind') != 'mltd-client-text-request'
                or not re.fullmatch('[0-9a-f]{64}', doc.get('checkpoint_key', ''))
                or not re.fullmatch('[0-9a-f]{64}', doc.get('adaptation_id', ''))))):
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
    if not record_request:
        if catalogue['rows']:
            write_json(path, catalogue, sort_keys=True)
        return len(pending)
    request_path = root / REQUESTS
    requests = read_json(request_path) if request_path.exists() else {'schema_version': 1, 'requests': []}
    pin = {'request_asset_id': asset_id, 'request_sha256': digest,
           'checkpoint_key': doc['checkpoint_key'], 'source_sha256': source['source_apk_sha256'],
           'source_ids': sorted(set(pending))}
    prior = next((row for row in requests['requests'] if row['request_asset_id'] == asset_id), None)
    if prior and prior != pin:
        raise ValueError('Immutable APK text request changed')
    if not prior:
        requests['requests'].append(pin)
    if len(requests['requests']) > 256:
        raise ValueError('APK text request history budget exceeded')
    write_json(path, catalogue, sort_keys=True)
    write_json(request_path, requests, sort_keys=True)
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
    return import_request(root, doc, None, None, record_request=False)


def download(root, event):
    payload = event['client_payload']
    aid, digest = payload['request_asset_id'], payload['request_sha256']
    if not re.fullmatch('[1-9][0-9]*', str(aid)) or not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Invalid APK text asset pin')
    meta = json.loads(gh('api', f'repos/{PRIVATE}/releases/assets/{aid}'))
    if meta['size'] > MAX_BYTES or not re.fullmatch(r'ci-[1-9][0-9]*\.client-text-request\.json', meta['name']):
        raise ValueError('APK text asset budget or name mismatch')
    blob = gh('api', f'repos/{PRIVATE}/releases/assets/{aid}', '-H', 'Accept: application/octet-stream')
    if len(blob) != meta['size'] or hashlib.sha256(blob).hexdigest() != digest:
        raise ValueError('APK text asset hash mismatch')
    doc = json.loads(blob)
    producer = doc['producer']
    run = json.loads(gh('api', f'repos/{PRIVATE}/actions/runs/{producer["run_id"]}'))
    if (producer['repository'] != PRIVATE or run['head_sha'] != producer['commit']
            or run['head_branch'] != 'main' or run['head_repository']['full_name'] != PRIVATE
            or run['path'] != '.github/workflows/future-version.yml'
            or meta['name'] != f'ci-{producer["run_id"]}.client-text-request.json'):
        raise ValueError('APK text request producer is not trusted private CI')
    return import_request(root, doc, aid, digest)


def validate_source_event(event):
    payload = event['client_payload']
    if (payload.get('producer_repository') != PRIVATE
            or not re.fullmatch('[0-9a-f]{40}', payload.get('producer_commit', ''))
            or not re.fullmatch('[0-9a-f]{40}', payload.get('commit', ''))
            or not re.fullmatch('[1-9][0-9]*', str(payload.get('producer_run', '')))):
        raise ValueError('Invalid source discovery origin')
    run = json.loads(gh('api', f'repos/{PRIVATE}/actions/runs/{payload["producer_run"]}'))
    if (run['path'] != '.github/workflows/discover-client-resources.yml' or run['head_branch'] != 'main'
            or run['head_sha'] != payload['producer_commit'] or run['head_repository']['full_name'] != PRIVATE):
        raise ValueError('Source discovery is not trusted private CI')
    head = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    compared = json.loads(gh('api', f'repos/kohakunamori/MLTDTranslationClient/compare/{payload["commit"]}...{head}'))
    if compared['status'] not in ('identical', 'ahead'):
        raise ValueError('Source discovery commit is not on the checked-out Client main')


def callbacks(root, commit, repository):
    if repository != 'kohakunamori/MLTDTranslationClient' or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Invalid Client callback origin')
    if not (root / REQUESTS).exists():
        return 0
    doc = read_json(root / CATALOGUE)
    validate_catalogue(doc)
    accepted = {row['source_sha256'] for row in doc['rows'] if row['status'] == 'accepted'}
    count = 0
    for request in read_json(root / REQUESTS)['requests']:
        if not set(request['source_ids']) <= accepted:
            continue
        payload = {key: request[key] for key in ('request_asset_id', 'request_sha256', 'checkpoint_key')}
        payload.update(repository=repository, commit=commit)
        gh('api', '--method', 'POST', f'repos/{PRIVATE}/dispatches', '--input', '-',
           body={'event_type': 'client-candidate-text-updated', 'client_payload': payload})
        count += 1
    return count


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['import', 'callback', 'import-local-scan', 'validate-source-event'])
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--commit')
    parser.add_argument('--repository', default='kohakunamori/MLTDTranslationClient')
    args = parser.parse_args()
    if args.command == 'import':
        print(f'Imported {download(args.root, read_json(Path(os.environ["GITHUB_EVENT_PATH"])))} verified text sources.')
    elif args.command == 'import-local-scan':
        print(f'Imported {import_local_scan(args.root)} verified publisher text sources.')
    elif args.command == 'validate-source-event':
        validate_source_event(read_json(Path(os.environ['GITHUB_EVENT_PATH'])))
        print('Private APK discovery origin verified.')
    else:
        print(f'Dispatched {callbacks(args.root, args.commit, args.repository)} complete text requests.')
