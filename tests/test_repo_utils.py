from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from scripts import repo_utils


class RepositoryUtilityTests(unittest.TestCase):
    def test_layout_accepts_string_roots_and_exposes_versioned_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            layout = repo_utils.RepositoryLayout(directory)

            self.assertEqual(layout.builtin_manifest, Path(directory) / "manifests/apk-builtin.manifest.json")
            self.assertEqual(layout.runtime_catalogue("9.0.300"), Path(directory) / "localization/9.0.300/runtime-bi-zhcn.json")

    def test_canonical_bytes_normalizes_text_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            text = root / "source.json"
            image = root / "source.png"
            text.write_bytes('{\r\n  "ja": "劇場"\r\n}\r\n'.encode())
            image.write_bytes(b"\x89PNG\r\n")

            self.assertEqual(repo_utils.canonical_bytes(text), '{\n  "ja": "劇場"\n}\n'.encode())
            self.assertEqual(repo_utils.canonical_bytes(image), b"\x89PNG\r\n")

    def test_runtime_translation_ready_uses_the_active_catalogue(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifests/apk-builtin.manifest.json"
            manifest.parent.mkdir()
            manifest.write_text(json.dumps({"provenance": {"client_version": "9.0.300"}}), encoding="utf-8")
            catalogue = root / "localization/9.0.300/runtime-bi-zhcn.json"
            catalogue.parent.mkdir(parents=True)
            catalogue.write_text(json.dumps({"rows": [{"translatable": True, "status": "untranslated", "zh": ""}]}), encoding="utf-8")

            self.assertFalse(repo_utils.runtime_translation_ready(root))
            catalogue.write_text(json.dumps({"rows": [{"translatable": True, "status": "accepted", "zh": "剧场"}]}), encoding="utf-8")
            self.assertTrue(repo_utils.runtime_translation_ready(root))

    def test_write_json_is_deterministic_and_creates_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "document.json"
            repo_utils.write_json(path, {"z": 1, "a": "剧场"}, sort_keys=True)

            self.assertEqual(
                path.read_bytes(),
                '{\n  "a": "剧场",\n  "z": 1\n}\n'.encode(),
            )

    def test_translation_sources_excludes_baked_atlas_and_discovery_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            expected = [
                root / "localization/9.0.300/source.json",
                root / "localization/9.0.400/component-text-zhcn.json",
                root / "localization/9.0.400/runtime-bi-zhcn.json",
                root / "localization/shared/apk-text-zhcn.json",
            ]
            ignored = [
                root / "localization/9.0.400/apk-ui-strings-zhcn.json",
                root / "localization/9.0.400/discovery/automatic-text-request.json",
                root / "localization/9.0.400/discovery/resource-inventory.json",
                root / "localization/discovery/apk-text-zhcn.json",
            ]
            for path in expected + ignored:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}", encoding="utf-8")

            layout = repo_utils.RepositoryLayout(root)
            self.assertEqual(layout.translation_sources(), sorted(expected))


if __name__ == "__main__":
    unittest.main()
