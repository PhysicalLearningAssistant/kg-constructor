"""规则版粗筛：从教材段落中抽取候选节点与候选关系素材。

目标是“宁可少抽，不要抽碎”：优先命中常见术语、加粗/引号术语、定义句和
“X定理/X定律/X方程”这类完整名词短语，避免把整句话当成知识点。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .ids import KNOWN_NODE_IDS
from .segment import Section

CJK = r"\u4e00-\u9fff"
GREEK = r"\u0391-\u03a9\u03b1-\u03c9"
TERM_CHARS = rf"{CJK}A-Za-z{GREEK}0-9\-·"
TERM = rf"[{TERM_CHARS}]"
BOUNDARY = rf"(?:^|[，。；：、（）()\s和与及或由在用把将被使对从向])"

BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
QUOTE_RE = re.compile(r"“([^”]{2,20})”")
DEF_BEFORE_RE = re.compile(rf"{BOUNDARY}({TERM}{{2,12}}?)(?:定义为|称为|叫做|是指|是一种)")
DEF_AFTER_RE = re.compile(rf"(?:称为|叫做|是指)({TERM}{{2,12}})")
SUFFIX_RE = re.compile(rf"{BOUNDARY}({TERM}{{2,12}}?(?:定理|定律|方程|原理))")
METHOD_RE = re.compile(rf"{BOUNDARY}({TERM}{{2,8}}?法)(?=是|可以|时|，|。|；|$)")
APPLICATION_RE = re.compile(
    rf"{BOUNDARY}({TERM}{{2,12}}?的电场)(?=具有|内部|外部|处处|等效|，|。|；|$)"
)
FORMULA_BLOCK_RE = re.compile(r"\$\$(.+?)\$\$", re.S)
INLINE_FORMULA_RE = re.compile(r"\$[^$]{1,200}\$")

CANONICAL_NAMES = {
    "电场": "电场强度",
    "高斯定律": "高斯定理",
    "安培环路定律": "安培环路定理",
    "法拉第定律": "法拉第电磁感应定律",
    "麦克斯韦方程": "麦克斯韦方程组",
    "高斯磁定律": "高斯磁定律",
    "安培-麦克斯韦定律": "安培-麦克斯韦定律",
}

ALIASES = {
    "电场强度": ["电场"],
    "高斯定理": ["高斯定律"],
    "安培环路定理": ["安培环路定律"],
    "法拉第电磁感应定律": ["法拉第定律"],
}

STOPWORDS = {
    "我们", "你们", "它们", "可以", "因此", "所以", "但是", "如果", "由于", "根据",
    "利用", "通过", "为了", "其中", "这个", "那个", "这些", "那些", "一个", "两个",
    "这种", "那种", "上述", "如下", "如图", "所示", "需要", "能够", "进行", "表示",
    "称为", "叫做", "定义", "问题", "方法", "情况", "条件", "结果", "关系", "内容",
    "第一", "第二", "第三", "本章", "本节", "教材", "例题", "习题", "现象", "公式",
    "定理", "定律", "方程", "原理",
}

BAD_STARTS = (
    "当", "若", "如果", "对于", "在", "用", "把", "将", "使", "由", "和", "与", "及",
    "或", "而", "但", "则", "即", "也", "都", "有", "不", "该", "此", "其",
    "这", "那", "外部", "内部", "任意", "所有", "任何", "每个", "研究", "问题",
    "这种", "种", "上述", "所谓", "一个", "两个", "利用", "通过", "根据", "定义", "可以",
)

BAD_PARTS = (
    "研究问题", "形状", "大小", "解题", "使用", "利用", "表示", "称为", "定义",
    "判断", "组成", "包括", "等于", "正比", "反比", "平方", "距离", "方向",
    "比值", "代数", "真空", "介质", "影响", "情况", "条件", "作用", "过程",
    "关系", "内容", "结果", "原因", "目的", "方法", "步骤", "可以", "置于", "某一", "有向",
)

BAD_ENDS = (
    "的", "是", "为", "由", "和", "与", "及", "或", "在", "对", "从", "向", "把",
    "将", "被", "使", "让", "给", "有", "无", "不", "表示", "称为", "定义",
    "包括", "组成", "等于", "正比", "反比", "平方", "距离", "方向",
)

LAW_SUFFIXES = ("定理", "定律", "方程", "原理")


@dataclass
class Candidate:
    name: str
    type: str
    description: str
    quote: str
    section: Section
    formula_latex: str | None = None
    aliases: list[str] = field(default_factory=list)
    conditions: list[str] = field(default_factory=list)
    position: int = 0

    @property
    def canonical(self) -> str:
        return CANONICAL_NAMES.get(self.name, self.name)


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[。！？!?；;])\s*", text)
    return [item.strip() for item in parts if item.strip()]


def clean_term(value: str) -> str | None:
    term = value.strip().strip("，。；：、,.;:!?！？（）()[]【】《》“”\"' \t")
    term = re.sub(r"\s+", " ", term)
    for _ in range(2):
        for prefix in BAD_STARTS:
            if term.startswith(prefix) and len(term) > len(prefix) + 1:
                term = term[len(prefix) :].strip()
    term = term.strip("，。；：、,.;:!?！？（）()[]【】《》“”\"' \t")

    if not (2 <= len(term) <= 20):
        return None
    if term in STOPWORDS or term in {"现象", "方法", "公式", "定理", "定律", "方程", "原理"}:
        return None
    if len(re.findall(f"[{CJK}]", term)) < 2:
        return None
    if any(part in term for part in BAD_PARTS):
        return None
    if any(term.endswith(ending) for ending in BAD_ENDS):
        return None
    if "的" in term and len(term) > 14:
        return None
    if re.fullmatch(r"第[一二三四五六七八九十百零〇\d]+[章节]", term):
        return None
    return term


def classify(name: str, *, is_formula: bool = False) -> str:
    if is_formula:
        return "formula"
    if name in {"麦克斯韦方程组", "高斯磁定律", "安培-麦克斯韦定律"}:
        return "law"
    if name.endswith(LAW_SUFFIXES):
        return "law"
    if name.endswith(("方法", "法")):
        return "method"
    if name.endswith(("现象", "效应")):
        return "phenomenon"
    if name.endswith(("的电场", "的应用")):
        return "application"
    return "concept"


def _quote_for(term: str, sentences: list[str], fallback: str) -> str:
    for sentence in sentences:
        if term in sentence:
            return sentence[:4000]
    return fallback[:4000]


def _add_candidate(
    found: dict[str, Candidate],
    name: str,
    section: Section,
    sentences: list[str],
    fallback: str,
    *,
    position: int = 0,
    is_formula: bool = False,
    formula_latex: str | None = None,
) -> None:
    cleaned = clean_term(name)
    if cleaned is None:
        return
    canonical = CANONICAL_NAMES.get(cleaned, cleaned)
    kind = classify(canonical, is_formula=is_formula)
    quote = f"$${formula_latex}$$" if is_formula and formula_latex else _quote_for(cleaned, sentences, fallback)
    if is_formula:
        description = f"{canonical}的数学表达式。"
    else:
        description = _quote_for(cleaned, sentences, fallback)[:8000]

    existing = found.get(canonical)
    if existing is not None:
        if cleaned != canonical and cleaned not in existing.aliases:
            existing.aliases.append(cleaned)
        if len(quote) > len(existing.quote):
            existing.quote = quote
        return

    found[canonical] = Candidate(
        name=canonical,
        type=kind,
        description=description,
        quote=quote,
        section=section,
        formula_latex=formula_latex,
        aliases=list(ALIASES.get(canonical, [])),
        position=position,
    )


def _formula_base(found: dict[str, Candidate], start: int, section: Section) -> str:
    preceding = [item for item in found.values() if item.type != "formula" and item.position <= start]
    laws = [item for item in preceding if item.type == "law"]
    if laws:
        return laws[-1].name
    return re.sub(r"^\d+(\.\d+)*\s*", "", section.title).strip() or section.title


def extract_candidates(sections: list[Section], *, max_per_section: int = 10) -> list[Candidate]:
    candidates: list[Candidate] = []

    for section in sections:
        raw = section.text
        formulas = [(m.start(), m.group(1).strip()) for m in FORMULA_BLOCK_RE.finditer(raw)]
        text_without_formulas = FORMULA_BLOCK_RE.sub(" ", raw)
        text_without_formulas = INLINE_FORMULA_RE.sub(" ", text_without_formulas)
        sentences = split_sentences(text_without_formulas)
        fallback = sentences[0] if sentences else raw[:4000]

        found: dict[str, Candidate] = {}

        for match in BOLD_RE.finditer(text_without_formulas):
            _add_candidate(found, match.group(1), section, sentences, fallback, position=match.start(1))
        for match in QUOTE_RE.finditer(text_without_formulas):
            _add_candidate(found, match.group(1), section, sentences, fallback, position=match.start(1))
        for match in DEF_BEFORE_RE.finditer(text_without_formulas):
            _add_candidate(found, match.group(1), section, sentences, fallback, position=match.start(1))
        for match in DEF_AFTER_RE.finditer(text_without_formulas):
            _add_candidate(found, match.group(1), section, sentences, fallback, position=match.start(1))
        for match in SUFFIX_RE.finditer(text_without_formulas):
            _add_candidate(found, match.group(1), section, sentences, fallback, position=match.start(1))
        for match in METHOD_RE.finditer(text_without_formulas):
            _add_candidate(found, match.group(1), section, sentences, fallback, position=match.start(1))

        # 常见术语兜底：优先保证核心概念不漏
        for known in KNOWN_NODE_IDS:
            if known in text_without_formulas:
                _add_candidate(found, known, section, sentences, fallback, position=raw.find(known))

        # 公式块挂到本节最近的定律/概念下
        for start, latex in formulas:
            if not latex:
                continue
            base = _formula_base(found, start, section)
            if base.endswith("公式"):
                name = base
            else:
                name = f"{base}公式"
            index = 2
            while name in found:
                name = f"{base}公式（{index}）"
                index += 1
            _add_candidate(
                found,
                name,
                section,
                sentences,
                fallback,
                position=start,
                is_formula=True,
                formula_latex=latex,
            )

        priority = {"law": 0, "formula": 1, "method": 2, "phenomenon": 3, "application": 4, "concept": 5}
        ordered = sorted(found.values(), key=lambda item: (priority[item.type], item.position))
        candidates.extend(ordered[:max_per_section])

    unique: dict[str, Candidate] = {}
    for candidate in candidates:
        unique.setdefault(candidate.canonical, candidate)
    return list(unique.values())
