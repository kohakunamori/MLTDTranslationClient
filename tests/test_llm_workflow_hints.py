"""Contract checks for the hosted LLM translation workflow.

The engine resolves several file defaults relative to the process CWD.  This
job runs with the Client repository as its CWD while the engine is checked out
under ``.translation-engine``, so every engine-internal path the step relies on
must be passed explicitly.  A default path that only exists inside the engine
checkout otherwise fails at run time with ``FileNotFoundError`` — which is how
the given-name hints file broke the first nonempty draft queue.
"""
import re
import unittest
from pathlib import Path

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github"
    / "workflows"
    / "llm-translate-client.yml"
)


def _translate_step_args() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    marker = "Translate with the shared provider pool"
    start = text.index(marker)
    block = text[start:]
    match = re.search(r"args=\((.*?)\n\s*\)", block, re.DOTALL)
    if not match:
        raise AssertionError("translate step has no args=( ... ) list")
    return match.group(1)


class GivenNameHintsWiringTests(unittest.TestCase):
    def test_translate_step_passes_engine_given_name_hints(self):
        args = _translate_step_args()
        self.assertRegex(
            args,
            r"--given-name-hints\s+\S*\.translation-engine[\\/]glossary[\\/]given-name-hints\.json",
            "the translate step must point --given-name-hints at the engine checkout; "
            "the engine default is CWD-relative and the file only exists in the engine",
        )

    def test_engine_glossary_paths_are_explicit(self):
        args = _translate_step_args()
        engine_glossary = r"\.translation-engine[\\/]glossary[\\/]"
        for flag, filename in (
            ("--glossary", "authoritative-terms.json"),
            ("--authoritative-terms", "authoritative-terms.json"),
            ("--given-name-hints", "given-name-hints.json"),
        ):
            self.assertRegex(
                args,
                rf"{re.escape(flag)}\s+\S*{engine_glossary}{re.escape(filename)}",
                f"{flag} must resolve inside the engine checkout",
            )

    def test_prompt_manifest_path_is_explicit(self):
        # The engine default for --prompt-manifest is
        # Path("localization/prompts/mltd-zhcn-system.manifest.json"), also
        # CWD-relative.  This repository has no localization/prompts/ tree, so
        # dropping the flag from the step breaks the run exactly like the hints
        # default did; the path must stay inside the engine checkout.
        args = _translate_step_args()
        self.assertRegex(
            args,
            r"--prompt-manifest\s+\S*\.translation-engine[\\/]",
            "--prompt-manifest must be passed an engine-internal path; the engine "
            "default is CWD-relative and does not exist in the Client repository",
        )


if __name__ == "__main__":
    unittest.main()
