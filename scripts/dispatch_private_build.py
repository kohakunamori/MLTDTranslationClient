#!/usr/bin/env python3
"""Notify Private Build about one validated, immutable Client commit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def payload(root: Path, repository: str, commit: str) -> dict | None:
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Expected a repository and a full commit SHA')
    manifest = json.loads((root / 'manifests/apk-builtin.manifest.json').read_text(encoding='utf-8'))
    state_path = root / 'manifests/apk-source-state.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else None
    if state and state.get('build_supported') is not True:
        print('Latest APK has no supported native build target; dispatch skipped.')
        return None
    version = manifest['provenance']['client_version']
    if state and state['client_version'] != version:
        raise ValueError('Latest APK and active Client manifest versions differ')
    for source_path in (root / 'localization' / version).glob('*.json'):
        document = json.loads(source_path.read_text(encoding='utf-8'))
        if document.get('kind') == 'mltd-apk-runtime-bi-source':
            if any(row.get('translatable') and (row.get('status') != 'accepted' or not row.get('zh', '').strip())
                   for row in document.get('rows', [])):
                print('Runtime BI translation queue is incomplete; dispatch skipped.')
                return None
    result = {'client_repository': repository, 'client_branch': 'main',
              'client_commit': commit, 'client_version': version}
    if state:
        result.update({key: state[key] for key in ('source_apk_sha256', 'source_split_sha256')})
    return {'event_type': 'client-resources-updated', 'client_payload': result}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--require-ready', action='store_true')
    parser.add_argument('--recover-unsupported', action='store_true')
    args = parser.parse_args()
    event = recovery_payload(ROOT, args.repository, args.commit) if args.recover_unsupported else payload(ROOT, args.repository, args.commit)
    if event is None:
        return 1 if args.require_ready else 0
    subprocess.run(['gh', 'api', '--method', 'POST',
                    'repos/kohakunamori/MLTDModifiedAPK/dispatches', '--input', '-'],
                   input=json.dumps(event), text=True, check=True)
    print(f"Dispatched Client {args.commit} ({event['client_payload']['client_version']}).")
    return 0


def recovery_payload(root: Path, repository: str, commit: str) -> dict | None:
    if not re.fullmatch(r'[\w.-]+/[\w.-]+', repository) or not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('Expected a repository and a full commit SHA')
    state = json.loads((root / 'manifests/apk-source-state.json').read_text(encoding='utf-8'))
    if state.get('build_supported') is not False:
        return None
    version = state.get('client_version', '')
    identity = state.get('source_identity', {})
    if (not re.fullmatch(r'\d+(?:\.\d+)+', version) or identity.get('client_version') != version
            or type(identity.get('version_code')) is not int or identity['version_code'] <= 0):
        raise ValueError('Unsupported source state has no valid version identity')
    hashes = {key: state.get(key) for key in ('source_apk_sha256', 'source_split_sha256')}
    if any(not isinstance(v, str) or not re.fullmatch(r'[0-9a-f]{64}', v) for v in hashes.values()):
        raise ValueError('Recovery requires exact official APK hashes')
    source = json.loads((root / 'localization' / version / 'runtime-bi-zhcn.json').read_text(encoding='utf-8'))
    if (source.get('kind') != 'mltd-apk-runtime-bi-source' or source.get('client_version') != version
            or source.get('source_apk_sha256') != hashes['source_apk_sha256']):
        raise ValueError('Recovery translation catalogue is not bound to the official APK')
    if any(row.get('translatable') and (row.get('status') != 'accepted' or not row.get('zh', '').strip())
           for row in source.get('rows', [])):
        return None
    return {'event_type': 'client-native-recovery-requested', 'client_payload': {
        'client_repository': repository, 'client_commit': commit,
        'client_version': version, 'version_code': identity['version_code'], **hashes}}


if __name__ == '__main__':
    raise SystemExit(main())
