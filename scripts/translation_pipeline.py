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
    "日圆", "精采", "身分", "优格", "集点卡",
    "网路", "软体", "硬体", "萤幕", "滑鼠",
    "简讯", "伺服器", "记忆体", "解析度", "档案夹", "资料库",
    "萤光", "图示", "视窗", "选单", "列印", "影印机",
    "游标", "自订要素", "机率", "连线失败", "连线错误", "排行榜机能",
    "搥", "拚命", "打拚", "拚尽", "要拚", "拚了",
    "於剧", "关於", "不同於",
    "姊姊", "大姊", "好姊妹", "三姊妹", "兩姊妹", "两姊妹",
    "迎春花蕾所見之夢", "追逐夢想", "{0}天日間",
    "点选", "點選", "脚踏车", "腳踏車", "计程车", "計程車", "高丽菜", "高麗菜",
    "义大利", "義大利", "霜淇淋", "原子笔", "原子筆", "麦克笔", "麥克筆",
    "百汇", "百匯", "凤梨", "鳳梨", "起司",
    "种稙", "你佷", "渡假", "直接了当", "磅礡",
    "草苺", "战戯", "戦戯", "通販节目", "仕掛け人大人", "裏读み", "祂",
)
ALWAYS_FORBIDDEN_TW_TERMS = ("感謝祭", "感謝", "全員")
TW_BORROW_RE = re.compile(r"藉(?:着|著|此|助|口|机|以|这|工作|写真)")
FALLBACK_TRADITIONAL_OUTPUT_CHARS = set(
    "妳製觀藝體這為會來說對沒裡還時學應與發萬張聲點門間從將讓見過麼麗實該閉腦現給難當國們歡聽獎續緊認謝種樣個開關頭書話寫讀轉選氣亞達場樂牠祂搧麽礡"
)
SIMPLIFIED_ZHU_COMPOUND_RE = re.compile(
    r"著名(?!流)|著作(?!笔记)|名著|原著|显著|执著|著称|著者|编著|合著|巨著|专著|"
    r"译著|遗著|新著|旧著|拙著|土著|昭著|着作|(?<![讨争议辩谈理结无言论])论著"
)
ZH_SENTENCE_FINAL_DE_SHUO_RE = re.compile(r"的说(?=(?:[！!。…～〜♪☆？?，,—]|\\\d+\\|\s*$))")
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
SHINJITAI_CREDIT_STRIP_RE = re.compile(
    r"[（(](?:CV|ＣＶ|声优)[^）)\n]*[）)]"
    r"|^[\s\u3000]*(?:作词|作曲|编曲|演唱)(?:[·・、/／](?:作词|作曲|编曲|演唱))*[：:].*$"
    r"|^\d+\s*[.．].*$",
    re.MULTILINE,
)
SHINJITAI_PROSE_STRIP_RE = re.compile(
    r"#[^\s\n]+"
    r"|世駆志威|亞蛇流帝|我威琉弩|カラオケの鉄人|絵羽模様|伝ゎっ|暁の砲弾|暁クロエ"
)
SHINJITAI_TO_SIMPLIFIED = {
    "紬": "䌷", "恵": "惠", "歩": "步", "浜": "滨", "桜": "樱",
    "駆": "驱", "姫": "姬", "気": "气", "瀬": "濑", "竜": "龙",
    "覇": "霸", "響": "响", "辺": "边", "緑": "绿", "穂": "穗",
    "黒": "黑", "亜": "亚", "鉄": "铁", "絵": "绘",
    "徳": "德", "環": "环", "髙": "高", "於": "于", "姉": "姐", "姊": "姐",
}
TRADITIONAL_IDOL_NAME_TOKENS = (
    ("紗代子", "纱代子"), ("莉緒", "莉绪"), ("麗花", "丽花"), ("貴音", "贵音"),
    ("詩花", "诗花"), ("奈緒", "奈绪"), ("琴葉", "琴叶"), ("千鶴", "千鹤"),
    ("徳川", "德川"), ("馬場", "马场"), ("大神環", "大神环"),
    ("髙橋", "高桥"), ("髙桥", "高桥"),
    ("二階堂", "二阶堂"), ("宮尾", "宫尾"), ("天空橋", "天空桥"), ("伊織", "伊织"),
    ("野々原", "野野原"), ("菜緒", "菜绪"), ("颯太", "飒太"),
    ("凛音亞", "凛音亚"), ("慧深璃亞", "慧深璃亚"), ("逢路蘭", "逢路兰"), ("深淵海", "深渊海"),
    ("笹森藍", "笹森蓝"), ("真田湊", "真田凑"), ("凛々加", "凛凛加"), ("神宮寺", "神宫寺"),
    ("白石 䌷", "白石䌷"),
)
UNTRANSLATED_JAPANESE_FRAGMENT_RE = re.compile(
    r"わたくし|ぜんぜん[ぁ-ゖ一-龯]|知ってるけど|分かってない|"
    r"故意に[一-龯]|憧れ[一-龯]|本当に[一-龯ぁ-ゖ]|"
    r"[一-龯ァ-ヺぁ-ゖ]{2,}(?:ましょうか|しませんか)|"
    r"かしみや|ぴょーん|必ゅ|さ玛|っ斯|"
    r"（りりか）|裏読み|裏读み"
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
    """Return an error reason when translation corrupts an authoritative MLTD idol/album/studio name."""
    compact = translation.replace("\n", "")
    for trad_name, canonical_name in TRADITIONAL_IDOL_NAME_TOKENS:
        if trad_name in compact and translation != source:
            return f"LLM output uses Traditional/Japanese kanji idol name {trad_name} instead of {canonical_name}"
    if "白石紬" in compact:
        return "LLM output uses non-authoritative idol name 白石紬 instead of 白石䌷"
    if "白石䋾" in compact:
        return "LLM output uses non-authoritative idol name 白石䋾 instead of 白石䌷"
    for bad_emily in (
        "司徒亚特", "艾米莉‧斯图亚特", "艾米莉・斯图亚特",
        "艾米莉 斯图亚特", "艾米莉\u3000斯图亚特",
    ):
        if bad_emily in compact and bad_emily not in source:
            return f"LLM output uses non-authoritative idol token {bad_emily} instead of 艾米莉·斯图亚特"
    if "エミリー" in source:
        for bad_em in ("エミリー", "艾米丽", "爱米莉", "爱米丽", "爱蜜莉", "艾蜜莉", "爱丽米莉"):
            if bad_em in compact and bad_em not in source:
                return f"LLM output uses non-authoritative Emily idol name {bad_em} instead of 艾米莉"
    for token in (
        "筿",
        "ソROCOレ", "ROCOレ", "索ROCO", "单ROCO", "ROCO集",
        "やよ伊", "まつ莉", "この美", "这个み",
    ):
        if token in compact and token not in source:
            return f"LLM output uses non-authoritative idol/product token {token}"
    if "ソロコレ" in source and "ROCO" in compact:
        stripped = SOLO_CORRECTION_RE.sub("", source)
        if "ロコ" not in stripped and "ROCO" not in stripped:
            return "LLM output misrenders ソロコレ as ROCO instead of 个人精选"
    for bad_tsumugi in ("白石纺", "白石紡", "纺希", "䌷希", "阿纺", "小纺", "纺纺", "纺小姐", "䋾"):
        if bad_tsumugi in compact and bad_tsumugi not in source:
            return f"LLM output uses non-authoritative idol name {bad_tsumugi} instead of 白石䌷"
    if ("紬" in source or "つむぎ" in source) and not any(k in source for k in ("紡", "つむぐ", "織", "糸")):
        if "纺织" in compact or "紡織" in compact or ("纺" in compact and "纺" not in source):
            return "LLM output uses 纺/纺织 for 紬 instead of 䌷"
    if any(k in source for k in ("亜利沙", "ありさ", "アリサ", "ありりーん")):
        if (
            "亜利沙" in compact
            or ("有栖" in compact and "有栖" not in source)
            or ("有纱" in compact and "紗" not in source)
            or any(
                bad in compact and bad not in source
                for bad in (
                    "阿莉莎", "亚丽莎", "亚利纱", "亚里沙", "阿利沙",
                    "有利沙", "有里纱", "有理沙", "有里莎", "有利纱",
                    "亚莉莎", "爱丽莎", "有莉莎", "啊莉莎", "有希莎",
                )
            )
        ):
            return "LLM output uses non-authoritative Arisa idol name instead of 松田亚利沙"
    if "あずさ" in TADOKORO_AZUSA_RE.sub("", source):
        azusa_spaced_ok = any(k in source for k in ("三浦\u3000あずさ", "三浦 あずさ")) and "三浦 梓" in translation
        if (
            any(bad in compact and bad not in source for bad in ("あず沙", "あず莎"))
            or (
                any(k in source for k in ("三浦あずさ", "三浦\u3000あずさ", "三浦 あずさ"))
                and "三浦" in compact
                and "三浦梓" not in compact
                and not azusa_spaced_ok
            )
            or ("秋月" in compact and not any(k in source for k in ("秋月", "律子", "りつこ", "リツコ")))
            or ("静香" in compact and not any(k in source for k in ("静香", "最上", "しずか", "シズカ")))
            or ("瑞希" in compact and not any(k in source for k in ("瑞希", "真壁", "みずき", "ミズキ")))
        ):
            return "LLM output uses non-authoritative Azusa idol name instead of 三浦梓"
    if "まつり" in translation.replace("まつり湯", "").replace("まつり汤", ""):
        return "non-authoritative Matsuri idol name instead of 德川茉莉 in zh-CN output"
    if "まつり" in source.replace("まつり湯", ""):
        matsuri_spaced_ok = any(k in source for k in ("徳川\u3000まつり", "徳川 まつり")) and "德川 茉莉" in translation
        if (
            any(
                bad in compact and bad not in source
                for bad in (
                    "小毬", "玛茜", "小松莉", "松莉",
                    "马茨莉", "玛茨莉", "玛祖丽", "玛特莉", "玛茨琳",
                    "祭典公主", "祭公主", "祭姬", "小松姬", "小松代", "小松丽",
                    "祭莉", "祭里", "真莉莉", "小真理", "真祭", "茉莉莉",
                )
            )
            or (re.search(r"小祭(?![典坛祀])", compact) is not None and "小祭" not in source)
            or (
                any(k in source for k in ("徳川まつり", "徳川\u3000まつり", "徳川 まつり", "徳川茉莉"))
                and "德川" in compact
                and "德川茉莉" not in compact
                and not matsuri_spaced_ok
            )
        ):
            return "LLM output uses non-authoritative Matsuri idol name instead of 德川茉莉"
    if "このみ" in source or "コノミ" in source:
        konomi_spaced_ok = any(k in source for k in ("馬場\u3000このみ", "馬場 このみ")) and "马场 木实" in translation
        if (
            any(
                bad in compact and bad not in source
                for bad in (
                    "木乃美", "这乃", "この美", "这个み", "马场木乃", "这个位美", "这位小美", "这位木实",
                    "马场好美", "马场此美", "歌奈美", "歌乃美", "可奈美", "可可美", "木野实",
                    "木之美", "此乃美", "此木乃", "可妮米", "柯诺美", "科诺美", "小野美",
                    "小此木", "这奈美", "这由美", "这个实", "木实实",
                )
            )
            or ("好姐姐" in compact and not any(x in source for x in ("いいお姉", "素敵なお姉", "優しいお姉")))
            or re.search(
                r"(?:这位|马场|阿)这美|(?<![这那])这美(?:小姐|前辈|桑|酱)|这个美(?![好丽艳妙景貌食德观感])",
                compact,
            )
            is not None
            or ("木下" in compact and not any(k in source for k in ("木下", "ひなた", "ヒナタ")))
            or (
                re.search(r"馬場[\s\u3000]*このみ|(?<![こそあど])このみ(?:さん|ちゃん|先生|お?姉|様|さま|っち|ん(?!な))", source) is not None
                and "木实" not in compact
            )
            or (
                any(k in source for k in ("馬場このみ", "馬場\u3000このみ", "馬場 このみ"))
                and "马场" in compact
                and "马场木实" not in compact
                and not konomi_spaced_ok
            )
        ):
            return "LLM output uses non-authoritative Konomi idol name instead of 马场木实"
    if any(k in source for k in ("のり子", "のりさん", "のりっぺ", "のーりーこ")):
        noriko_bads = [
            "福田纪子", "福田典子", "福田则子", "德莉亚音", "德利子", "德莉子",
            "乃莉子", "诺丽子", "诺里子", "乃里子", "诺莉姐", "诺里姐", "诺里",
            "诺莉", "海苔子", "法理子", "阿诺子", "法子子", "のり子",
        ]
        if "ノリコ" not in source:
            noriko_bads.extend(["诺莉可", "诺莉子"])
        if not any(x in source for x in ("紀子", "典子", "則子")):
            noriko_bads.extend(["纪子", "典子", "则子"])
        for bad_nor in noriko_bads:
            if bad_nor in compact and bad_nor not in source:
                return f"LLM output uses non-authoritative Noriko idol name {bad_nor} instead of 福田法子"
    if "エレナ" in source:
        for bad_el in (
            "艾蕾娜", "艾莲娜", "埃莱娜", "爱莲娜", "艾丽娜", "艾雷娜",
            "绘莲娜", "艾莉娜", "艾伦娜", "埃琳娜", "埃列娜", "爱丽娜",
            "小埃莱娜", "エレナ",
        ):
            if bad_el in compact and bad_el not in source:
                return f"LLM output uses non-authoritative Elena idol name {bad_el} instead of 岛原艾琳娜"
        if "伊利亚" in compact and "イリヤ" not in source:
            return "LLM output uses non-authoritative Elena idol name 伊利亚 instead of 艾琳娜"
    if "ジュリア" in source and "ジュリアン" not in source:
        for bad_ju in ("ジュリア", "朱莉娅", "朱莉亚"):
            if bad_ju in compact and bad_ju not in source:
                return f"LLM output uses non-authoritative Julia idol name {bad_ju} instead of 茱莉亚"
    if "昴" in source:
        if any(bad in compact and bad not in source for bad in ("永吉昂", "小昂", "阿昂")) or (
            "昂" in compact
            and not any(w in compact for w in ("昂首", "昂扬", "高昂", "激昂", "低昂"))
            and re.search(r"(?<![高激低轩气])昂(?![首扬然藏贵])", compact) is not None
        ):
            return "LLM output uses non-authoritative Subaru idol kanji 昂 instead of 永吉昴"
    if (
        "杏奈" in source
        or ("アンナ" in source and not any(x in source for x in ("ドクター", "バニーポリス", "博士")) and "Dr." not in translation)
    ) and "安娜" in compact and "安娜" not in source:
        return "LLM output uses non-authoritative Anna idol name 安娜 instead of 望月杏奈"
    if "ひなた" in source.replace("ひなたぼっこ", "").replace("ひなたまつり", ""):
        for bad_hi in ("木下阳向", "木下雏田", "小雏田", "ひなた"):
            if bad_hi in compact and bad_hi not in source:
                return f"LLM output uses non-authoritative Hinata idol name {bad_hi} instead of 木下日向"
    if "歌織" in source and any(b in compact for b in ("樱守可织", "樱守香织")):
        return "LLM output uses non-authoritative Kaori idol name instead of 樱守歌织"
    if "志保" in source and any(b in compact for b in ("北泽诗穗", "北泽诗织")):
        return "LLM output uses non-authoritative Shiho idol name instead of 北泽志保"
    if "アオノリ" in source:
        for bad_ao in ("阿奥诺里", "奥诺里", "阿欧诺里", "阿乌诺利", "アオノリ"):
            if bad_ao in compact and bad_ao not in source:
                return f"LLM output uses non-authoritative Aonori name {bad_ao} instead of 青海苔"
    if "ミラソニ" in source:
        for bad_ms in ("ミラソニ", "蜜拉索尼", "MiraSoni"):
            if bad_ms in compact and bad_ms not in source:
                return f"LLM output uses non-authoritative MiraSoni name {bad_ms} instead of 米拉索尼"
    for bad_cv in ("高桥ミナミ", "髙桥ミナミ", "髙橋ミナミ"):
        if bad_cv in compact:
            return f"LLM output uses non-authoritative CV name {bad_cv} instead of 高桥未奈美"
    for bad_kanji, canonical_kanji in (
        ("大和撫子", "大和抚子"),
        ("陰界戦戯", "阴界战戏"),
        ("六学窓", "六学窗"),
        ("月兎", "月兔"),
        ("詰将棋", "诘将棋"),
    ):
        if bad_kanji in compact:
            return f"LLM output retains unconverted Japanese kanji {bad_kanji!r} instead of {canonical_kanji!r}"
    if (
        re.search(r"動画|ムービー|ビデオ", source)
        and "映画" not in source
        and "フィルム" not in source
        and re.search(r"影片(?!场)", compact)
    ):
        return "LLM output uses zh-TW lexicon '影片' for video instead of '视频'"
    if "うどん" in source and "乌龙面" in compact:
        return "LLM output uses zh-TW lexicon '乌龙面' instead of '乌冬面'"
    if re.search(r"プロジェクト|企画", source) and "专案" in compact:
        return "LLM output uses zh-TW lexicon '专案' instead of '企划'"
    if "バス" in source and "公车" in compact:
        return "LLM output uses zh-TW lexicon '公车' instead of '公交车'"
    if "推し" in source and "推し" in re.sub(r'[《「『“"][^》」』”"]*[》」』”"]', "", compact):
        return "LLM output retains untranslated '推し' in zh-CN prose"
    if "765プロ" in source and "765プロデューサー" not in source:
        for bad_pro in (
            "765制作人", "765专业", "765职业", "765制作公司", "765制造所", "765制作所",
            "765事务部", "765位制作人", "765名专业", "765位专业", "第765位",
            "765名职业", "765位职业", "765プ", "765PROCO", "765制作人ROCO", "765艺剧场",
        ):
            if bad_pro in compact and bad_pro not in source:
                return f"LLM output uses non-authoritative studio name {bad_pro} for 765プロ instead of 765事务所"
    if "961プロ" in source and "961プロデューサー" not in source:
        for bad_pro in ("961制作人", "961专业", "961职业", "961位制作人", "961名专业", "961制作公司"):
            if bad_pro in compact and bad_pro not in source:
                return f"LLM output uses non-authoritative studio name {bad_pro} for 961プロ instead of 961事务所"
    if source.rstrip().endswith("\nなお") and translation.rstrip().split("\n")[-1].strip() in {
        "另外", "另外，", "啊，等等", "然后", "还有", "顺带一提",
    }:
        return "LLM output mistranslates Nao sign-off なお as conjunction instead of 奈绪"
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
    repo_root = Path(__file__).resolve().parents[1]
    for relative in (
        ".translation-engine/pipelines/text/configs/traditional-to-simplified-char-map.json",
        "schema/traditional-to-simplified-char-map.json",
    ):
        map_path = repo_root / relative
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


REQUIRED_DOMAIN_TERMS = (
    ("閃光☆HANABI団", "闪光☆HANABI团"),
    ("期間限定オートライブPASS", "限时自动演出通行证"),
    ("Angelステップ", "Angel舞步"),
    ("Fairyステップ", "Fairy舞步"),
    ("Princessステップ", "Princess舞步"),
    ("Angelハーモニー", "Angel和声"),
    ("Angelテクニック", "Angel技巧"),
)

FORBIDDEN_UI_TERMS = (
    ("期間限定オートライブPASS", ("限时自动演出PASS", "自动直播", "自动实况"), "限时自动演出通行证"),
    ("ミリコレ", ("百万音乐", "百万收集"), "百万收藏"),
    ("楽天イーグルス", ("乐天老鹰", "乐天鹰"), "乐天金鹰"),
    ("スパークドリンク", ("能量饮料", "火花饮料", "活力饮料", "气泡饮料"), "充电饮料"),
    ("ライブチケット", ("演唱会门票", "演出门票", "入场券", "Live演出门票", "演出道具", "演唱会入场券"), "演唱会券"),
    ("ユニット編成", ("队伍编组", "队伍编制", "编队"), "组合编成"),
    ("ラウンジ", ("休息室", "酒廊"), "社交厅"),
    ("２次元コード", ("２维码", "2维码", "2次元码", "QR码"), "二维码"),
    ("2次元コード", ("２维码", "2维码", "2次元码", "QR码"), "二维码"),
    ("自分のコードを表示", ("显示自己的代码",), "显示自己的二维码"),
    ("次回以降表示しない", ("以后不再显示",), "下次起不再显示"),
    ("弊社サポートセンター", ("我司客服", "客服支持中心"), "本公司客服中心"),
    ("引き継ぎ", ("引继", "数据转移"), "数据继承"),
)


def _client_terminology_error(source: str, translation: str) -> str | None:
    """Enforce consistent Client UI and canonical unit/skill terminology."""
    compact = re.sub(r"\s+", "", translation)
    for src_term, canonical in REQUIRED_DOMAIN_TERMS:
        if src_term in source and canonical not in compact:
            return f"LLM output uses non-authoritative {src_term} translation instead of {canonical}"
    if (
        "期間限定オートライブPASS" in source
        and "オートライブPASS" not in source.replace("期間限定オートライブPASS", "")
        and "自动演出PASS" in translation
    ):
        return "LLM output uses inconsistent UI term 自动演出PASS for 期間限定オートライブPASS (use 限时自动演出通行证)"
    for src_term, bad_terms, canonical in FORBIDDEN_UI_TERMS:
        if src_term in source:
            for bad in bad_terms:
                if bad in translation and bad not in source:
                    return f"LLM output uses inconsistent UI term {bad} for {src_term} (use {canonical})"
    if "マスターレッスン" in source and any(b in compact for b in ("大师特训", "大师课程")):
        return "LLM output uses inconsistent UI term for マスターレッスン (use 明星课程)"
    if "ラウンジ" in source and "マスター" in source:
        for bad in ("室长", "团长", "主控", "厅主"):
            if bad in translation:
                return f"LLM output uses inconsistent UI term {bad} for lounge マスター (use 厅长)"
    if "ユニット" in source and "団体" not in source and "团体" in translation:
        return "LLM output uses inconsistent UI term 团体 for ユニット (use 组合)"
    if "元気" in source and "体力" not in source and "体力" in translation:
        return "LLM output uses inconsistent UI term 体力 for 元気 (use 活力)"
    if source.strip() == "引き継ぎ" and translation.strip() != "数据继承":
        return "LLM output uses inconsistent UI term for 引き継ぎ (use 数据继承)"
    if source.strip() == "お問い合わせ" and translation.strip() != "联系我们":
        return "LLM output uses inconsistent UI term for お問い合わせ (use 联系我们)"
    if "ゲスト" in source and "助演" in translation:
        return "LLM output uses inconsistent UI term 助演 for ゲスト (use 嘉宾)"
    return None


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
    if TW_BORROW_RE.search(translation) and not TW_BORROW_RE.search(source):
        raise ValueError("LLM output contains non-mainland zh-TW lexicon (藉*)")
    if "、】【" in translation and "、】【" not in source:
        raise ValueError("LLM output contains malformed trailing brackets 、】【")
    if re.search(r"<color=[^>]*></color>", translation) and not re.search(r"<color=[^>]*></color>", source):
        raise ValueError("LLM output contains empty <color=...></color> tag")
    if re.sub(r"\\\d+\\|\\[nrt]|\\_", "", translation).count("\\") > re.sub(r"\\\d+\\|\\[nrt]|\\_", "", source).count("\\"):
        raise ValueError("LLM output contains stray backslash outside \\NN\\ emoticon code")
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
    term_error = _client_terminology_error(source, translation)
    if term_error:
        raise ValueError(term_error)
    if translation != source:
        no_credits = SHINJITAI_CREDIT_STRIP_RE.sub("", PROTECTED_TOKENS.sub("", translation))
        prose_clean = SHINJITAI_PROSE_STRIP_RE.sub("", QUOTED_TEXT_RE.sub("", no_credits))
        for tw_term in ALWAYS_FORBIDDEN_TW_TERMS:
            if tw_term in prose_clean or any(
                tw_term in quoted and quoted not in source
                for quoted in QUOTED_TEXT_RE.findall(no_credits)
            ):
                raise ValueError(f"LLM output contains non-mainland zh-TW lexicon ({tw_term})")
        if "紬" in prose_clean or any(
            "紬" in quoted and quoted not in source
            for quoted in QUOTED_TEXT_RE.findall(no_credits)
        ):
            raise ValueError("LLM output contains unconverted Japanese kanji 紬 (use 䌷)")
        for jp_kanji, simplified in SHINJITAI_TO_SIMPLIFIED.items():
            if jp_kanji != "紬" and jp_kanji in prose_clean:
                raise ValueError(f"LLM output contains unconverted Japanese kanji {jp_kanji} (use {simplified})")


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


NON_EDITABLE_CATALOGUE_KINDS = frozenset({
    "mltd-apk-ui-strings",
    "mltd-apk-resource-inventory",
    "mltd-client-source-text",
})


def _is_editable_catalogue(document: Any) -> bool:
    """Ignore baked-atlas descriptors and discovery staging payloads."""
    if not isinstance(document, dict):
        return False
    if document.get("kind") in NON_EDITABLE_CATALOGUE_KINDS:
        return False
    policy = document.get("policy")
    if isinstance(policy, dict) and policy.get("baked_pixels_are_not_text_records") is True:
        return False
    return True


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
        documents = [
            (path, document)
            for path in self.source_files()
            if _is_editable_catalogue(document := read_json(path))
        ]
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
                if not _is_editable_catalogue(document):
                    continue
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
            if not _is_editable_catalogue(document):
                continue
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
