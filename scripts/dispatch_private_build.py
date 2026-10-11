#!/usr/bin/env python3
"""Notify Private Build about one validated, immutable Client commit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess

try:  # Works both as a package import in tests and as a CI file entrypoint.
    from scripts.repo_utils import (
        VERSION_RE,
        RepositoryLayout,
        active_client_version,
        read_json,
        require_repository_inputs,
        runtime_translation_ready,
        valid_sha256,
    )
except ModuleNotFoundError:  # pragma: no cover - exercised by direct execution
    from repo_utils import (
        VERSION_RE,
        RepositoryLayout,
        active_client_version,
        read_json,
        require_repository_inputs,
        runtime_translation_ready,
        valid_sha256,
    )

ROOT = Path(__file__).resolve().parents[1]


def payload(root: Path, repository: str, commit: str) -> dict | None:
    require_repository_inputs(repository, commit)
    layout = RepositoryLayout(root)
    state_path = layout.source_state_manifest
    state = read_json(state_path) if state_path.exists() else None
    if state and state.get('build_supported') is not True:
        print('Latest APK has no supported native build target; dispatch skipped.')
        return None
    version = active_client_version(root)
    if state and state['client_version'] != version:
        raise ValueError('Latest APK and active Client manifest versions differ')
    if not runtime_translation_ready(root, version):
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
    require_repository_inputs(repository, commit)
    layout = RepositoryLayout(root)
    state = read_json(layout.source_state_manifest)
    if state.get('build_supported') is not False:
        return None
    version = state.get('client_version', '')
    identity = state.get('source_identity', {})
    if (not VERSION_RE.fullmatch(version) or identity.get('client_version') != version
            or type(identity.get('version_code')) is not int or identity['version_code'] <= 0):
        raise ValueError('Unsupported source state has no valid version identity')
    hashes = {key: state.get(key) for key in ('source_apk_sha256', 'source_split_sha256')}
    if any(not valid_sha256(v) for v in hashes.values()):
        raise ValueError('Recovery requires exact official APK hashes')
    source = read_json(layout.runtime_catalogue(version))
    if (source.get('kind') != 'mltd-apk-runtime-bi-source' or source.get('client_version') != version
            or source.get('source_apk_sha256') != hashes['source_apk_sha256']):
        raise ValueError('Recovery translation catalogue is not bound to the official APK')
    if not runtime_translation_ready(root, version):
        return None
    return {'event_type': 'client-native-recovery-requested', 'client_payload': {
        'client_repository': repository, 'client_commit': commit,
        'client_version': version, 'version_code': identity['version_code'], **hashes}}


if __name__ == '__main__':
    raise SystemExit(main())
