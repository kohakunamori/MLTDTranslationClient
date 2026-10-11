"""Domain payloads for notifying the private APK build repository."""
from __future__ import annotations

from pathlib import Path

try:
    from scripts.repo_utils import (
        VERSION_RE,
        RepositoryLayout,
        active_client_version,
        read_json,
        require_repository_inputs,
        runtime_translation_ready,
        valid_sha256,
    )
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    from repo_utils import (
        VERSION_RE,
        RepositoryLayout,
        active_client_version,
        read_json,
        require_repository_inputs,
        runtime_translation_ready,
        valid_sha256,
    )


def payload(root: Path, repository: str, commit: str) -> dict | None:
    """Build a normal translated-resource event when the source is ready."""
    require_repository_inputs(repository, commit)
    layout = RepositoryLayout(root)
    state_path = layout.source_state_manifest
    state = read_json(state_path) if state_path.exists() else None
    if state and state.get("build_supported") is not True:
        return None
    version = active_client_version(root)
    if state and state["client_version"] != version:
        raise ValueError("Latest APK and active Client manifest versions differ")
    if not runtime_translation_ready(root, version):
        return None
    result = {
        "client_repository": repository,
        "client_branch": "main",
        "client_commit": commit,
        "client_version": version,
    }
    if state:
        result.update({key: state[key] for key in ("source_apk_sha256", "source_split_sha256")})
    return {"event_type": "client-resources-updated", "client_payload": result}


def recovery_payload(root: Path, repository: str, commit: str) -> dict | None:
    """Build a native recovery event for an unsupported official APK."""
    require_repository_inputs(repository, commit)
    layout = RepositoryLayout(root)
    state = read_json(layout.source_state_manifest)
    if state.get("build_supported") is not False:
        return None
    version = state.get("client_version", "")
    identity = state.get("source_identity", {})
    if (
        not VERSION_RE.fullmatch(version)
        or identity.get("client_version") != version
        or type(identity.get("version_code")) is not int
        or identity["version_code"] <= 0
    ):
        raise ValueError("Unsupported source state has no valid version identity")
    hashes = {key: state.get(key) for key in ("source_apk_sha256", "source_split_sha256")}
    if any(not valid_sha256(value) for value in hashes.values()):
        raise ValueError("Recovery requires exact official APK hashes")
    source = read_json(layout.runtime_catalogue(version))
    if (
        source.get("kind") != "mltd-apk-runtime-bi-source"
        or source.get("client_version") != version
        or source.get("source_apk_sha256") != hashes["source_apk_sha256"]
    ):
        raise ValueError("Recovery translation catalogue is not bound to the official APK")
    if not runtime_translation_ready(root, version):
        return None
    return {
        "event_type": "client-native-recovery-requested",
        "client_payload": {
            "client_repository": repository,
            "client_commit": commit,
            "client_version": version,
            "version_code": identity["version_code"],
            **hashes,
        },
    }
