"""Use the shared engine's pure text helpers in its disposable CI checkout."""
from __future__ import annotations
import argparse
from pathlib import Path

LEGACY = 'from pipelines.text.mltd_localize_gtx import read_jsonl, validate_translation'
PURE = ('from pipelines.core.jsonl import read_jsonl\n'
        'from pipelines.text.translation_tokens import validate_translation')


def prepare(engine):
    codec = engine / 'pipelines/text/mltd_localize_gtx.py'
    if codec.exists():
        source = codec.read_text(encoding='utf-8')
        changes = [('\nimport UnityPy\n', '', 'def get_text_asset(bundle: Path):\n', '    import UnityPy\n'),
                   ('\nfrom Crypto.Cipher import AES\n', '', 'def decrypt_payload(cipher: bytes) -> bytes:\n', '    from Crypto.Cipher import AES\n')]
        for eager, _, header, local in changes:
            if eager in source:
                if source.count(eager) != 1 or source.count(header) != 1:
                    raise ValueError('Shared codec dependency interface changed')
                source = source.replace(eager, '\n').replace(header, header + local)
                if 'Crypto.Cipher' in local:
                    encrypt = 'def encrypt_payload(plain: bytes) -> bytes:\n'
                    if source.count(encrypt) != 1:
                        raise ValueError('Shared codec encryption interface changed')
                    source = source.replace(encrypt, encrypt + local)
        codec.write_text(source, encoding='utf-8', newline='\n')
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
