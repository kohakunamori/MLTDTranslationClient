"""Use the shared engine's pure text helpers in its disposable CI checkout."""
from __future__ import annotations
import argparse
from pathlib import Path

LEGACY = 'from pipelines.text.mltd_localize_gtx import read_jsonl, validate_translation'
PURE = ('from pipelines.core.jsonl import read_jsonl\n'
        'from pipelines.text.translation_tokens import validate_translation')


def prepare(engine):
    path = engine / 'pipelines/text/translate_mltd_api_pool.py'
    source = path.read_text(encoding='utf-8')
    for relative in ('pipelines/core/jsonl.py', 'pipelines/text/translation_tokens.py'):
        if not (engine / relative).is_file():
            raise ValueError('Shared engine is missing its pure text helpers')
    if LEGACY in source:
        if source.count(LEGACY) != 1:
            raise ValueError('Ambiguous shared provider helper import')
        # The legacy module reexports these exact helpers, but eagerly imports
        # bundle parsing and AES. Keep the same validator and JSONL reader while
        # excluding APK dependencies from Client's text translation process.
        path.write_text(source.replace(LEGACY, PURE), encoding='utf-8', newline='\n')
    elif PURE not in source:
        raise ValueError('Shared provider helper interface changed; review before translation')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', type=Path, required=True)
    prepare(parser.parse_args().engine)
