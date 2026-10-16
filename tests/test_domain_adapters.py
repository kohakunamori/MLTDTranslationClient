from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

from scripts.portal_manifest import PortalManifestBuilder
from scripts.private_build import payload, recovery_payload
from scripts.repo_utils import RepositoryLayout, read_json


ROOT = Path(__file__).resolve().parents[1]


class DomainAdapterTests(unittest.TestCase):
    def test_portal_builder_matches_checked_in_summary_without_commit_identity(self):
        builder = PortalManifestBuilder(ROOT)
        generated = builder.build()
        checked_in = builder.layout.portal_manifest.read_text(encoding="utf-8")
        import json

        expected = json.loads(checked_in)
        generated["source"].pop("commit", None)
        generated["release"].pop("client_resources_commit", None)
        expected["source"].pop("commit", None)
        expected["release"].pop("client_resources_commit", None)
        self.assertEqual(generated, expected)

    def test_private_build_payload_matches_the_current_source_state(self):
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
        ).strip()
        repository = "kohakunamori/MLTDTranslationClient"
        state_path = RepositoryLayout(ROOT).source_state_manifest
        state = read_json(state_path) if state_path.exists() else None

        if state and state.get("build_supported") is False:
            self.assertIsNone(payload(ROOT, repository, commit))
            event = recovery_payload(ROOT, repository, commit)
            self.assertIsNotNone(event)
            self.assertEqual(event["event_type"], "client-native-recovery-requested")
            self.assertEqual(event["client_payload"]["client_version"], state["client_version"])
        else:
            event = payload(ROOT, repository, commit)
            self.assertIsNotNone(event)
            self.assertEqual(event["event_type"], "client-resources-updated")
            self.assertEqual(event["client_payload"]["client_version"], "9.0.300")
        self.assertEqual(event["client_payload"]["client_commit"], commit)


if __name__ == "__main__":
    unittest.main()
