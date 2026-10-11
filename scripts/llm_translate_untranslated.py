#!/usr/bin/env python3
"""CLI adapter for the Client translation pipeline."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterator

try:  # Support both direct CI execution and package imports in tests.
    from scripts import translation_pipeline as _translation_pipeline
except ModuleNotFoundError:  # pragma: no cover - direct file execution
    import translation_pipeline as _translation_pipeline

TranslationPipeline = _translation_pipeline.TranslationPipeline
eligible = _translation_pipeline.eligible
records = _translation_pipeline.records
source_id = _translation_pipeline.source_id
validate_translation = _translation_pipeline.validate_translation

ROOT = Path(__file__).resolve().parents[1]


def _pipeline() -> TranslationPipeline:
    return TranslationPipeline(ROOT)


# Keep these compatibility functions for automation that imported the original
# script module before the domain module existed.
def refresh_source_hashes() -> None:
    _pipeline().refresh_source_hashes()


def source_files() -> Iterator[Path]:
    yield from _pipeline().source_files()


def collect(args: argparse.Namespace) -> int:
    result = _pipeline().collect(args.output)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def apply(args: argparse.Namespace) -> int:
    result = _pipeline().apply(args.draft)
    print(json.dumps(result, ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    collect_parser = sub.add_parser("collect")
    collect_parser.add_argument("--output", type=Path, required=True)
    collect_parser.set_defaults(func=collect)
    apply_parser = sub.add_parser("apply")
    apply_parser.add_argument("--draft", type=Path, required=True)
    apply_parser.set_defaults(func=apply)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
