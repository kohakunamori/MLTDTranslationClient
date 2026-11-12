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
        self.assertIn(
            "--given-name-hints .translation-engine/glossary/given-name-hints.json",
            args,
            "the translate step must point --given-name-hints at the engine checkout; "
            "the engine default is CWD-relative and the file only exists in the engine",
        )

    def test_engine_glossary_paths_are_explicit(self):
        args = _translate_step_args()
        for flag in (
            "--glossary",
            "--authoritative-terms",
            "--given-name-hints",
            "--prompt-manifest",
        ):
            self.assertIn(flag, args, f"{flag} must be explicit in the translate step")
        for line in args.splitlines():
            option = line.strip()
            if option.startswith(("--glossary", "--authoritative-terms", "--given-name-hints")):
                self.assertIn(
                    ".translation-engine/glossary/",
                    option,
                    f"{option.split()[0]} must resolve inside the engine checkout",
                )


if __name__ == "__main__":
    unittest.main()
