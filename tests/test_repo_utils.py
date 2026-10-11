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


if __name__ == "__main__":
    unittest.main()
