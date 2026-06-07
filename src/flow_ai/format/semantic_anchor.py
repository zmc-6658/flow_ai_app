from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from flow_ai.format.ast_reader import ParagraphRecord

ANCHOR_PATTERNS: dict[str, re.Pattern[str]] = {
    "abstract_cn": re.compile(r"^摘\s*要$"),
    "abstract_en": re.compile(r"^ABSTRACT$", re.IGNORECASE),
    "keywords_cn": re.compile(r"^关键词"),
    "keywords_en": re.compile(r"^KEY\s*WORDS", re.IGNORECASE),
    "toc": re.compile(r"^目\s*录$"),
    "references": re.compile(r"^参\s*考\s*文\s*献$"),
    "acknowledgment": re.compile(r"^致\s*谢$"),
}

COVER_SCHOOL_RE = re.compile(r"(学院|大学)")
COVER_DOC_TYPE_RE = re.compile(r"(毕业论文|学位论文|毕业设计)")
COVER_TITLE_RE = re.compile(r"^论文题目")
COVER_INFO_RE = re.compile(r"^\s*(专\s*业|班\s*级|姓\s*名|学\s*号|指导教师)")
COVER_FOOTER_DATE_RE = re.compile(r"\d{4}\s*年")


class DocumentSection(StrEnum):

    COVER = "cover"
    FRONT_MATTER = "front_matter"
    TOC = "toc"
    BODY = "body"
    BACK_MATTER = "back_matter"
    UNKNOWN = "unknown"


@dataclass
class AnchorState:

    section: DocumentSection = DocumentSection.COVER
    anchor_hits: dict[str, int] = field(default_factory=dict)
    section_by_index: dict[int, DocumentSection] = field(default_factory=dict)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text)


def _find_anchor_index(paragraphs: list[ParagraphRecord], name: str) -> int | None:
    pattern = ANCHOR_PATTERNS.get(name)
    if pattern is None:
        return None
    for index, record in enumerate(paragraphs):
        text = record.text.strip()
        if pattern.match(_compact(text)) or pattern.match(text):
            return index
    return None


def _find_body_start(paragraphs: list[ParagraphRecord], toc_index: int | None) -> int | None:
    if toc_index is None:
        return None
    for index in range(toc_index + 1, len(paragraphs)):
        text = paragraphs[index].text.strip()
        compact = _compact(text)
        if re.match(r"^1(\s|\.|前)", compact) or re.match(r"^1\s*绪论", text):
            return index
        if re.match(r"^第[一二三四五六七八九十\d]+[章节篇]", compact):
            return index
    return toc_index + 1 if toc_index + 1 < len(paragraphs) else None


def annotate_sections(paragraphs: list[ParagraphRecord]) -> AnchorState:
    state = AnchorState()
    if not paragraphs:
        return state

    abstract_cn = _find_anchor_index(paragraphs, "abstract_cn")
    abstract_en = _find_anchor_index(paragraphs, "abstract_en")
    toc_index = _find_anchor_index(paragraphs, "toc")
    references_index = _find_anchor_index(paragraphs, "references")
    acknowledgment_index = _find_anchor_index(paragraphs, "acknowledgment")
    body_start = _find_body_start(paragraphs, toc_index)

    if abstract_cn is not None:
        state.anchor_hits["abstract_cn"] = abstract_cn
    if abstract_en is not None:
        state.anchor_hits["abstract_en"] = abstract_en
    if toc_index is not None:
        state.anchor_hits["toc"] = toc_index
    if references_index is not None:
        state.anchor_hits["references"] = references_index
    if acknowledgment_index is not None:
        state.anchor_hits["acknowledgment"] = acknowledgment_index
    if body_start is not None:
        state.anchor_hits["body_start"] = body_start

    back_start = references_index
    if acknowledgment_index is not None and (
        back_start is None or acknowledgment_index < back_start
    ):
        back_start = acknowledgment_index

    for index in range(len(paragraphs)):
        if abstract_cn is not None and index < abstract_cn:
            section = DocumentSection.COVER
        elif toc_index is not None and abstract_cn is not None and abstract_cn <= index < toc_index:
            section = DocumentSection.FRONT_MATTER
        elif body_start is not None and toc_index is not None and toc_index <= index < body_start:
            section = DocumentSection.TOC
        elif back_start is not None and index >= back_start:
            section = DocumentSection.BACK_MATTER
        elif body_start is not None and index >= body_start:
            section = DocumentSection.BODY
        else:
            section = DocumentSection.UNKNOWN
        state.section_by_index[index] = section

    return state


def section_for_record(
    state: AnchorState,
    record: ParagraphRecord,
    paragraphs: list[ParagraphRecord],
) -> DocumentSection:
    try:
        index = paragraphs.index(record)
    except ValueError:
        return DocumentSection.UNKNOWN
    return state.section_by_index.get(index, DocumentSection.UNKNOWN)
