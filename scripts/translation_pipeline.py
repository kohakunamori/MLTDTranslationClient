"""Domain logic for collecting and applying Client translation sources.

This module deliberately has no command-line concerns. Other automation can
reuse the same catalogue rules without importing a CLI module or manufacturing
``argparse.Namespace`` objects.
"""
from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

try:  # Support package imports and direct script execution.
    from .repo_utils import (
        RepositoryLayout,
        canonical_bytes,
        read_json,
        sha256,
        sha256_bytes,
        write_json,
    )
except ImportError:  # pragma: no cover - direct file execution
    from repo_utils import RepositoryLayout, canonical_bytes, read_json, sha256, sha256_bytes, write_json

PROTECTED_TOKENS = re.compile(
    r"\{[^{}]+\}|%(?:\d+\$)?[-+0 #]*\d*(?:\.\d+)?[a-zA-Z%]|<[^<>\r\n]+>|\\[nrt]|\\[0-9]{2}\\|\d{1,3}(?:,\d{3})+(?:\.\d+)?"
)
GROUPED_NUMBER = re.compile(r'(?<!\d)\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)')
TRANSLATED_GROUPED_NUMBER = re.compile(r'(?<!\d)\d{1,3}(?:[,，、]\d{3})+(?:\.\d+)?(?!\d)')
PROVIDER_ERROR_RE = re.compile(
    r"this service has been disabled"
    r"|violation of terms of service"
    r"|submit an appeal to continue"
    r"|account has been (?:disabled|suspended|banned|terminated)"
    r"|account is (?:disabled|suspended)"
    r"|exceeded your current quota"
    r"|insufficient[_ ]quota"
    r"|\b(?:too many requests|rate limit exceeded|service unavailable|bad gateway)\b"
    r"|\b(?:upstream error|model is currently overloaded)\b"
    r"|i'?m sorry,?\s+(?:but\s+)?i can(?:not|'t)\s+(?:assist|help|translate|comply|fulfill)"
    r"|\bas an ai(?:\s+(?:language\s+)?model)?\b",
    re.IGNORECASE,
)
JAPANESE_OR_HAN_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
ASCII_WORD_RE = re.compile(r"[A-Za-z]{2,}")
BLOCKED_SCRIPT_PREFIXES = (
    "CYRILLIC", "HANGUL", "DEVANAGARI", "THAI", "KANNADA", "GUJARATI", "MALAYALAM",
    "TAMIL", "TELUGU", "BENGALI", "ORIYA", "GURMUKHI", "SINHALA", "GEORGIAN",
    "ARMENIAN", "HEBREW", "ARABIC", "ETHIOPIC", "MYANMAR", "KHMER", "LAO", "TIBETAN",
    "BUBBLES", "THOUGHT BALLOON", "SPEECH BALLOON",
)
INVISIBLE_FORMAT_CODEPOINTS = frozenset({0x00A0, 0x200B, 0x200F, 0xFEFF})
META_MARKERS = (
    "译者注", "翻译注", "translator note", "translation:",
    "[::thought", "🫧thought", "[::]", "[::-]", "[:::]",
    "原文意思", "这里的意思", "可能是：", "可能是:",
    "变成：", "变成:", "rel久久热",
)
TW_UNCONDITIONAL = (
    "艾蜜莉", "转蛋", "轉蛋", "推播", "此讯息", "此訊息",
    "部落格", "弹跳视窗", "彈跳視窗", "资料夹", "資料夾",
    "应用程式", "應用程式", "快取资料", "快取資料",
)
FALLBACK_TRADITIONAL_OUTPUT_CHARS = set(
    "妳製觀藝體這為會來說對沒裡還時學應與發萬張聲點門間從將讓見過麼麗實該閉腦現給難當國們歡聽獎續緊認謝種樣個開關頭書話寫讀轉選氣亞達場樂"
)
SIMPLIFIED_ZHU_COMPOUND_RE = re.compile(
    r"著名(?!流)|著作(?!笔记)|名著|原著|显著|执著|著称|著者|编著|合著|巨著|专著|"
    r"译著|遗著|新著|旧著|拙著|土著|昭著|着作|(?<![讨争议辩谈理结无言论])论著"
)
ZH_SENTENCE_FINAL_DE_SHUO_RE = re.compile(r"的说(?=(?:[！!。…～〜♪☆？?，,]|\\\d+\\|\s*$))")
BROKEN_RANK_RE = re.compile(r"第(?:最高分|活动|社交厅|粉丝数?)排行榜")
SOLO_CORRECTION_RE = re.compile(r"ソロコレ(?:クション)?")
TADOKORO_AZUSA_RE = re.compile(r"田所\s*あずさ")
TRUNCATED_KATA_ADJ_HAN_RE = re.compile(r"(?:[ァ-ヺー]+(?=[一-龯])|(?<=[一-龯])[ァ-ヺー]+)")
KATAKANA_TOKEN_RE = re.compile(r"[ァ-ヺー]{2,}")
KATAKANA_COMPOUND_TAILS = (
    "コラボ", "カフェ", "カウント", "ダウン", "セレクション", "ライブ", "イベント",
    "ガシャ", "ガチャ", "キャンペーン", "マスター", "エリア", "ツアー", "ショップ",
    "グッズ", "シャツ", "バッジ", "ポスター", "パネル", "ステージ", "シリーズ",
)
KATAKANA_IGNORE_TOKENS = frozenset({"ー", "ノ", "ノシ", "ッ"})
QUOTED_TEXT_RE = re.compile(r"「[^」\n]*」|『[^』\n]*』|《[^》\n]*》|“[^”\n]*”")
UNTRANSLATED_JAPANESE_FRAGMENT_RE = re.compile(
    r"わたくし|ぜんぜん[ぁ-ゖ一-龯]|知ってるけど|分かってない|"
    r"故意に[一-龯]|憧れ[一-龯]|かしみや|ぴょーん|必ゅ|さ玛|っ斯"
)
ZH_BAD_MEANING_CUE_RE = re.compile(
    r"(?:坏(?:的)?(?:意思|意义|处|方面|事)|不好的(?:意思|意义|方面)|不好(?:意义|方面)|(?:不是说|并非|不算|并不是)不好|"
    r"恶意|贬义|贬低|负面(?:的)?(?:意思|意义)|批评|嘲笑|往坏处|往坏的方面)"
)
JP_BICYCLE_COMPOUND_RE = re.compile(
    r"(?:マウンテンバイク|ロードバイク|クロスバイク|エアロバイク|フィットネスバイク|ミニバイク|ポケバイ)"
)
ZH_BICYCLE_RE = re.compile(r"(?:自行车|自行車|单车|單車|脚踏车|腳踏車)")
ZH_MOTORBIKE_CUE_RE = re.compile(r"(?:摩托|机车|機車|重机|重機|电单车|電單車)")
JP_STANDALONE_GEKI_RE = re.compile(r"(?<!演)劇(?!場|団|團|的)")
ZH_PLAY_CUE_RE = re.compile(r"(?:舞台剧|舞台劇|戏剧|戲劇|话剧|話劇|剧|劇)")


def _semantic_mistranslation_error(source: str, translation: str) -> str | None:
    """Reject high-precision semantic/lexical class mistranslations in Client output."""
    if not translation or not ("悪い意味" in source or "バイク" in source or "劇" in source):
        return None
    if "悪い意味" in source and not ZH_BAD_MEANING_CUE_RE.search(translation):
        return "LLM output omits bad meaning (悪い意味) semantics"
    if "バイク" in source:
        stripped = JP_BICYCLE_COMPOUND_RE.sub("", source)
        is_triathlon = "トライアスロン" in source or ("スイム" in source and "ラン" in source)
        if (
            "バイク" in stripped
            and not is_triathlon
            and ZH_BICYCLE_RE.search(translation)
            and not ZH_MOTORBIKE_CUE_RE.search(translation)
        ):
            return "LLM output mistranslates motorbike (バイク) as bicycle"
    if JP_STANDALONE_GEKI_RE.search(source) and "演出" in translation and not ZH_PLAY_CUE_RE.search(translation):
        return "LLM output generalizes standalone play/drama (劇) as 演出"
    return None


def _kana_hybrid_or_fragment_error(source: str, translation: str) -> str | None:
    """Reject truncated Katakana+Hanzi hybrids and untranslated hiragana fragments."""
    if not translation or translation == source:
        return None
    source_tokens = KATAKANA_TOKEN_RE.findall(source)
    if source_tokens:
        unwrapped = re.sub(r"(?<=[ァ-ヺー])\n(?=[ァ-ヺー])", "", translation)
        for match in TRUNCATED_KATA_ADJ_HAN_RE.finditer(unwrapped):
            fragment = match.group(0)
            if set(fragment) <= {"ー"} or fragment in KATAKANA_IGNORE_TOKENS or fragment in source_tokens:
                continue
            for source_token in source_tokens:
                if fragment == source_token or fragment not in source_token:
                    continue
                if source_token.startswith(fragment):
                    tail = source_token[len(fragment):]
                    if tail.startswith(KATAKANA_COMPOUND_TAILS) or (len(fragment) >= 4 and len(tail) >= 3):
                        continue
                return f"LLM output contains truncated katakana hybrid {fragment} from {source_token}"
    frag_match = UNTRANSLATED_JAPANESE_FRAGMENT_RE.search(QUOTED_TEXT_RE.sub("", translation))
    if frag_match:
        return f"LLM output retains untranslated Japanese fragment {frag_match.group(0)}"
    return None


def _non_authoritative_idol_error(source: str, translation: str) -> str | None:
    """Return an error reason when translation corrupts an authoritative MLTD idol/album name."""
    if "白石紬" in translation:
        return "LLM output uses non-authoritative idol name 白石紬 instead of 白石䌷"
    if "白石䋾" in translation:
        return "LLM output uses non-authoritative idol name 白石䋾 instead of 白石䌷"
    for bad_emily in (
        "司徒亚特", "艾米莉‧斯图亚特", "艾米莉・斯图亚特",
        "艾米莉 斯图亚特", "艾米莉\u3000斯图亚特",
    ):
        if bad_emily in translation and bad_emily not in source:
            return f"LLM output uses non-authoritative idol token {bad_emily} instead of 艾米莉·斯图亚特"
    for token in (
        "筿",
        "ソROCOレ", "ROCOレ", "索ROCO", "单ROCO", "ROCO集",
        "やよ伊", "まつ莉", "この美", "这个み",
    ):
        if token in translation and token not in source:
            return f"LLM output uses non-authoritative idol/product token {token}"
    if "ソロコレ" in source and "ROCO" in translation:
        stripped = SOLO_CORRECTION_RE.sub("", source)
        if "ロコ" not in stripped and "ROCO" not in stripped:
            return "LLM output misrenders ソロコレ as ROCO instead of 个人精选"
    for bad_tsumugi in ("白石纺", "白石紡", "纺希", "䌷希", "阿纺", "小纺", "纺纺", "纺小姐", "䋾"):
        if bad_tsumugi in translation and bad_tsumugi not in source:
            return f"LLM output uses non-authoritative idol name {bad_tsumugi} instead of 白石䌷"
    if ("紬" in source or "つむぎ" in source) and not any(k in source for k in ("紡", "つむぐ", "織", "糸")):
        if "纺织" in translation or "紡織" in translation or ("纺" in translation and "纺" not in source):
            return "LLM output uses 纺/纺织 for 紬 instead of 䌷"
    if any(k in source for k in ("亜利沙", "ありさ", "アリサ")):
        if "亜利沙" in translation or ("有栖" in translation and "有栖" not in source) or any(
            bad in translation and bad not in source for bad in ("阿莉莎", "亚丽莎", "亚利纱")
        ):
            return "LLM output uses non-authoritative Arisa idol name instead of 松田亚利沙"
    if "あずさ" in TADOKORO_AZUSA_RE.sub("", source):
        azusa_spaced_ok = any(k in source for k in ("三浦\u3000あずさ", "三浦 あずさ")) and "三浦 梓" in translation
        if (
            any(bad in translation and bad not in source for bad in ("あず沙", "あず莎"))
            or (
                any(k in source for k in ("三浦あずさ", "三浦\u3000あずさ", "三浦 あずさ"))
                and "三浦" in translation
                and "三浦梓" not in translation
                and not azusa_spaced_ok
            )
            or ("秋月" in translation and not any(k in source for k in ("秋月", "律子", "りつこ", "リツコ")))
            or ("静香" in translation and not any(k in source for k in ("静香", "最上", "しずか", "シズカ")))
            or ("瑞希" in translation and not any(k in source for k in ("瑞希", "真壁", "みずき", "ミズキ")))
        ):
            return "LLM output uses non-authoritative Azusa idol name instead of 三浦梓"
    if "まつり" in translation.replace("まつり湯", "").replace("まつり汤", ""):
        return "non-authoritative Matsuri idol name instead of 德川茉莉 in zh-CN output"
    if "まつり" in source.replace("まつり湯", ""):
        matsuri_spaced_ok = any(k in source for k in ("徳川\u3000まつり", "徳川 まつり")) and "德川 茉莉" in translation
        if (
            any(bad in translation and bad not in source for bad in ("小毬", "玛茜", "小松莉", "松莉"))
            or (re.search(r"小祭(?![典坛祀])", translation) is not None and "小祭" not in source)
            or (
                any(k in source for k in ("徳川まつり", "徳川\u3000まつり", "徳川 まつり", "徳川茉莉"))
                and "德川" in translation
                and "德川茉莉" not in translation
                and not matsuri_spaced_ok
            )
        ):
            return "LLM output uses non-authoritative Matsuri idol name instead of 德川茉莉"
    if "このみ" in source:
        konomi_spaced_ok = any(k in source for k in ("馬場\u3000このみ", "馬場 このみ")) and "马场 木实" in translation
        if (
            any(
                bad in translation and bad not in source
                for bad in ("木乃美", "这乃", "马场木乃", "这个位美", "这位小美", "这位木实")
            )
            or re.search(r"(?:这位|马场|阿)这美|(?<![这那])这美(?:小姐|前辈|桑|酱)", translation) is not None
            or ("木下" in translation and not any(k in source for k in ("木下", "ひなた", "ヒナタ")))
            or (
                any(k in source for k in ("馬場このみ", "馬場\u3000このみ", "馬場 このみ"))
                and "马场" in translation
                and "马场木实" not in translation
                and not konomi_spaced_ok
            )
        ):
            return "LLM output uses non-authoritative Konomi idol name instead of 马场木实"
    if "スタイルドロップ" in source:
        for bad_drop in (
            "大师造型水滴", "大师风格掉落", "大师风格微滴",
            "Style Drop", "StyleDrop", "风格掉落道具", "风格掉落物", "风格服装代币",
            "造型掉落物", "造型水滴", "样式水滴", "身姿水滴", "造型掉落", "造型滴露",
            "造型徽章", "风格掉落", "风格滴露", "风格糖果", "风格吊饰", "风格微滴",
            "风格碎片",
        ):
            if bad_drop in translation and bad_drop not in source:
                return f"LLM output uses non-authoritative Style Drop wording {bad_drop} instead of 风格水滴 / 大师风格水滴"
    if "ネトスワ" in source or "ネットスワイプス" in source:
        if "NetSwipes" not in translation or any(
            k in translation for k in ("ネトスワ", "ネットスワイプス")
        ):
            return "LLM output uses non-authoritative NetSwipes wording instead of NetSwipes"
    return None


def _load_traditional_output_chars() -> set[str]:
    map_path = (
        Path(__file__).resolve().parents[1]
        / ".translation-engine/pipelines/text/configs/traditional-to-simplified-char-map.json"
    )
    if map_path.is_file():
        doc = json.loads(map_path.read_text(encoding="utf-8-sig"))
        mapping = doc.get("map", {}) if isinstance(doc, dict) else {}
        if isinstance(mapping, dict):
            chars = {
                str(src)
                for src, dst in mapping.items()
                if len(str(src)) == 1 and len(str(dst)) == 1 and str(src) != str(dst)
            }
            if chars:
                return chars
    return set(FALLBACK_TRADITIONAL_OUTPUT_CHARS)


TRADITIONAL_OUTPUT_CHARS = _load_traditional_output_chars()


def _foreign_scripts(text: str) -> set[str]:
    scripts: set[str] = set()
    stripped = PROTECTED_TOKENS.sub("", text)
    for ch in stripped:
        if ord(ch) < 128 or "\u3000" <= ch <= "\u9fff" or "\uf900" <= ch <= "\ufaff" or "\uff00" <= ch <= "\uffef":
            continue
        name = unicodedata.name(ch, "")
        for prefix in BLOCKED_SCRIPT_PREFIXES:
            if prefix in name:
                scripts.add(prefix)
                break
    return scripts


def _introduced_traditional_chars(source: str, translation: str) -> set[str]:
    clean_source = SIMPLIFIED_ZHU_COMPOUND_RE.sub("", source)
    clean_translation = SIMPLIFIED_ZHU_COMPOUND_RE.sub("", translation).replace("篠宫", "")
    src_counts = Counter(ch for ch in clean_source if ch in TRADITIONAL_OUTPUT_CHARS)
    dst_counts = Counter(ch for ch in clean_translation if ch in TRADITIONAL_OUTPUT_CHARS)
    return {ch for ch, cnt in dst_counts.items() if cnt > src_counts.get(ch, 0)}


def repair_numeric_separators(source: str, translation: str) -> str:
    """Restore source separators only when the exact digits and decimal agree."""
    choices: dict[str, set[str]] = {}
    def identity(value):
        return re.sub('[,，、]', '', value)
    for match in GROUPED_NUMBER.finditer(source):
        choices.setdefault(identity(match[0]), set()).add(match[0])
    def restore(match):
        values = choices.get(identity(match[0]), set())
        return next(iter(values)) if len(values) == 1 else match[0]
    return TRANSLATED_GROUPED_NUMBER.sub(restore, translation)


def validate_translation(source: str, translation: str) -> None:
    if any(char in translation for char in ("|", "^", "\0")):
        raise ValueError("LLM output contains a reserved BI delimiter")
    if Counter(PROTECTED_TOKENS.findall(source)) != Counter(PROTECTED_TOKENS.findall(translation)):
        raise ValueError("LLM output changed protected formatting tokens")
    match = PROVIDER_ERROR_RE.search(translation)
    if match and match.group(0).lower() not in source.lower():
        raise ValueError("LLM output contains an upstream provider error message")
    if "⚠" in translation and "⚠" not in source:
        raise ValueError("LLM output contains an unexpected warning banner")
    stripped_source = PROTECTED_TOKENS.sub(" ", source)
    stripped_translation = PROTECTED_TOKENS.sub(" ", translation)
    if (
        JAPANESE_OR_HAN_RE.search(stripped_source)
        and not JAPANESE_OR_HAN_RE.search(stripped_translation)
        and len(ASCII_WORD_RE.findall(stripped_source)) <= 1
        and len(ASCII_WORD_RE.findall(stripped_translation)) >= 5
    ):
        raise ValueError("LLM output looks like untranslated English prose or an error banner")
    introduced_scripts = _foreign_scripts(translation) - _foreign_scripts(source)
    if introduced_scripts:
        raise ValueError(f"LLM output contains unexpected foreign script: {sorted(introduced_scripts)[0]}")
    src_counts = Counter(source)
    dst_counts = Counter(translation)
    for code in sorted(INVISIBLE_FORMAT_CODEPOINTS):
        if dst_counts[chr(code)] > src_counts[chr(code)]:
            raise ValueError(f"LLM output contains unexpected invisible format U+{code:04X}")
    for ch in translation:
        if ch not in source and (
            unicodedata.category(ch) in {"Cn", "Cs", "Co"}
            or (ord(ch) >= 0x20000 and unicodedata.category(ch).startswith("L"))
        ):
            raise ValueError(f"LLM output contains unexpected non-BMP ideograph U+{ord(ch):X}")
    introduced_trad = _introduced_traditional_chars(source, translation)
    if introduced_trad:
        raise ValueError(f"LLM output contains Traditional Chinese chars: {''.join(sorted(introduced_trad))}")
    lowered = translation.lower()
    lowered_source = source.lower()
    if any(marker in lowered and marker not in lowered_source for marker in META_MARKERS):
        raise ValueError("LLM output contains translator meta text")
    if any(term in translation and term not in source for term in TW_UNCONDITIONAL):
        raise ValueError("LLM output contains non-mainland zh-TW lexicon")
    idol_error = _non_authoritative_idol_error(source, translation)
    if idol_error:
        raise ValueError(idol_error)
    if BROKEN_RANK_RE.search(translation):
        raise ValueError("LLM output contains malformed ranking phrase")
    if ZH_SENTENCE_FINAL_DE_SHUO_RE.search(translation) and "的说" not in source:
        raise ValueError("LLM output uses sentence-final calque 的说")
    if "ログイン" in source and "登入" in translation and "登入" not in source:
        raise ValueError("LLM output uses non-mainland 登入 instead of 登录")
    if "履歴" in source and "履歴書" not in source and "履历" in translation and "履历" not in source:
        raise ValueError("LLM output uses non-mainland 履历 instead of 记录")
    hybrid_error = _kana_hybrid_or_fragment_error(source, translation)
    if hybrid_error:
        raise ValueError(hybrid_error)
    semantic_error = _semantic_mistranslation_error(source, translation)
    if semantic_error:
        raise ValueError(semantic_error)


def source_id(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def records(value: Any, path: str = "") -> Iterator[tuple[str, dict[str, Any]]]:
    """Yield translation records from any nested JSON value."""
    if isinstance(value, dict):
        if isinstance(value.get("ja"), str) and isinstance(value.get("zh"), str):
            yield path, value
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            yield from records(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from records(child, f"{path}[{index}]")


def eligible(row: dict[str, Any]) -> bool:
    return not row.get("zh", "") and row.get("status") in (None, "untranslated")


class TranslationPipeline:
    """Read and update all editable JSON catalogues for one repository."""

    def __init__(self, root: Path):
        self.layout = RepositoryLayout(root)
        self.root = self.layout.root

    def source_files(self) -> list[Path]:
        return self.layout.translation_sources()

    def refresh_source_hashes(self) -> None:
        path = self.layout.builtin_manifest
        document = read_json(path)
        shared_path = self.root / 'localization/shared/apk-text-zhcn.json'
        if shared_path.exists():
            from scripts.apk_text_requests import validate_catalogue
            shared = read_json(shared_path)
            validate_catalogue(shared)
            for surface in document['surfaces']:
                source = surface.get('translation_source')
                if surface.get('name') != 'component-text' or not source:
                    continue
                target_path = self.root / source['relative_path']
                component = read_json(target_path)
                for field, name in (('rows', 'component'), ('android_rows', 'android')):
                    indexed = {row['ja']: row for row in component.get(field, [])}
                    for row in shared['rows']:
                        if row['status'] != 'accepted' or not any(c['surface'] == name for c in row['contexts']):
                            continue
                        prior = indexed.get(row['ja'])
                        if prior and prior.get('status') in (None, 'untranslated') and not prior.get('zh'):
                            prior['zh'] = row['zh']
                            prior['status'] = 'accepted'
                            if 'translation_stage' in row:
                                prior['translation_stage'] = row['translation_stage']
                            if 'updated_at' in row:
                                prior['updated_at'] = row['updated_at']
                        elif prior and prior['zh'] != row['zh']:
                            raise ValueError('Shared Client text conflicts with the active catalogue')
                        elif not prior:
                            indexed[row['ja']] = {key: row[key] for key in ('ja', 'zh', 'status', 'source_sha256')}
                    component[field] = list(indexed.values())
                component['counts'] = {'sources': len(component['rows']),
                    'accepted': sum(row['status'] == 'accepted' for row in component['rows']),
                    'excluded': sum(row['status'] == 'passthrough' for row in component['rows'])}
                write_json(target_path, component)
        changed = False
        for surface in document["surfaces"]:
            source = surface.get("translation_source")
            if not source:
                continue
            source_path = self.root / source["relative_path"]
            new_hash, size = sha256(source_path), len(canonical_bytes(source_path))
            if source.get("sha256") != new_hash or source.get("bytes") != size:
                source.update(sha256=new_hash, bytes=size)
                changed = True
        if changed:
            write_json(path, document)

    def collect(self, output: Path) -> dict[str, int | str]:
        # Resolve identical Japanese sources locally before spending provider tokens.
        documents = [(path, read_json(path)) for path in self.source_files()]
        repaired = 0
        for path, document in documents:
            changed = False
            for _, row in records(document):
                if row.get('status') not in (None, 'accepted') or not row['zh']:
                    continue
                corrected = repair_numeric_separators(row['ja'], row['zh'])
                if corrected != row['zh']:
                    validate_translation(row['ja'], corrected)
                    row['zh'] = corrected
                    row['format_repair'] = 'exact-source-numeric-separators'
                    changed = True
                    repaired += 1
            if changed:
                write_json(path, document, sort_keys=path == self.root / 'localization/shared/apk-text-zhcn.json')
        if repaired:
            self.refresh_source_hashes()
        candidates: dict[str, set[str]] = {}
        normalized_candidates: dict[str, set[str]] = {}
        for _, document in documents:
            for _, row in records(document):
                if row["zh"] and row.get("status") in (None, "accepted"):
                    validate_translation(row["ja"], row["zh"])
                    candidates.setdefault(row["ja"], set()).add(row["zh"])
                    normalized_candidates.setdefault(row["ja"].replace("\r\n", "\n"), set()).add(row["zh"])

        reused = 0
        for path, document in documents:
            changed = False
            for _, row in records(document):
                if not eligible(row):
                    continue
                choices = candidates.get(row["ja"], set())
                if len(choices) != 1:
                    choices = normalized_candidates.get(row["ja"].replace("\r\n", "\n"), set())
                if len(choices) == 1:
                    row.update(
                        zh=next(iter(choices)),
                        status="accepted",
                        translation_stage="reused_exact_source",
                    )
                    changed = True
                    reused += 1
            if changed:
                write_json(path, document, sort_keys=path == self.root / 'localization/shared/apk-text-zhcn.json')
        if reused:
            self.refresh_source_hashes()

        output.parent.mkdir(parents=True, exist_ok=True)
        seen: set[str] = set()
        seen_norm: set[str] = set()
        count = 0
        with output.open("w", encoding="utf-8", newline="\n") as stream:
            for path in self.source_files():
                document = read_json(path)
                for key_path, row in records(document):
                    source = row["ja"]
                    if not eligible(row) or not source:
                        continue
                    sid = source_id(source)
                    norm_sid = source_id(source.replace("\r\n", "\n"))
                    if sid in seen or norm_sid in seen_norm:
                        continue
                    seen.add(sid)
                    seen_norm.add(norm_sid)
                    stream.write(
                        json.dumps(
                            {
                                "source": source,
                                "source_sha256": sid,
                                "bundle": path.relative_to(self.root).as_posix(),
                                "key": key_path,
                                "task": "UI",
                                "translation": "",
                                "status": "pending",
                            },
                            ensure_ascii=False,
                            separators=(",", ":"),
                        )
                        + "\n"
                    )
                    count += 1
        return {"queue": str(output), "items": count, "reused": reused, "format_repaired": repaired}

    def apply(self, draft: Path) -> dict[str, int | str]:
        translations: dict[str, str] = {}
        normalized_translations: dict[str, str] = {}
        rejected = 0
        for line in draft.read_text(encoding="utf-8-sig").replace("\r\n", "\n").split("\n"):
            if not line.strip():
                continue
            row = json.loads(line)
            source = str(row.get("source", ""))
            sid = str(row.get("source_sha256", ""))
            translation = str(row.get("translation", "")).strip()
            if not source or sid != source_id(source) or not translation:
                continue
            translation = repair_numeric_separators(source, translation)
            try:
                validate_translation(source, translation)
            except ValueError:
                # Keep valid progress and leave this source untranslated for
                # the next scheduled run; invalid formatting never reaches APKs.
                rejected += 1
                continue
            prior = translations.get(sid)
            if prior is not None and prior != translation:
                raise SystemExit(f"conflicting LLM output for source {sid}")
            norm_sid = source_id(source.replace("\r\n", "\n"))
            norm_prior = normalized_translations.get(norm_sid)
            if norm_prior is not None and norm_prior != translation:
                raise SystemExit(f"conflicting LLM output for normalized source {norm_sid}")
            translations[sid] = translation
            normalized_translations[norm_sid] = translation

        if not translations:
            return {"updated": 0, "drafts": 0, "rejected": rejected}

        timestamp = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        updated = 0
        for path in self.source_files():
            document = read_json(path)
            changed = False
            for _, row in records(document):
                source = str(row.get("ja", ""))
                sid = source_id(source) if source else ""
                translation = translations.get(sid)
                if translation is None and source:
                    translation = normalized_translations.get(source_id(source.replace("\r\n", "\n")))
                if translation is None or not eligible(row):
                    continue
                row.update(
                    zh=translation,
                    status="accepted",
                    translation_stage="llm_translated",
                    updated_at=timestamp,
                )
                changed = True
                updated += 1
            if changed:
                write_json(path, document, sort_keys=path == self.root / 'localization/shared/apk-text-zhcn.json')
        self.refresh_source_hashes()
        return {"updated": updated, "drafts": len(translations), "rejected": rejected, "stage": "llm_translated"}
