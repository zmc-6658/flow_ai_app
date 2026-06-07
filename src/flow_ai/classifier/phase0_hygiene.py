"""Pass 0: document hygiene — TOC lock, empty paragraphs, list blocks."""

from __future__ import annotations

import re

from flow_ai.classifier.pipeline_models import AnnotatedParagraph, HygieneFlags
from flow_ai.core.ast_models import DocumentAST, GeneratedAnchorNode, OpaqueNode, ParagraphNode


TOC_ENTRY_PATTERN = re.compile(r"(?:[\t ]+|\.{2,}|。{2,}|…{1,})\d+\s*$")


def build_paragraph_list(ast: DocumentAST) -> list[AnnotatedParagraph]:
    paragraphs: list[AnnotatedParagraph] = []
    for node in ast.blocks:
        if isinstance(node, OpaqueNode | GeneratedAnchorNode):
            paragraphs.append(
                AnnotatedParagraph(
                    node_id=node.id,
                    text="",
                    text_length=0,
                    hygiene=HygieneFlags(skip_classification=True),
                )
            )
            continue
        if isinstance(node, ParagraphNode):
            text = node.text
            paragraphs.append(
                AnnotatedParagraph(
                    node_id=node.id,
                    text=text,
                    text_length=len(text.strip()),
                )
            )
            continue
        paragraphs.append(
            AnnotatedParagraph(
                node_id=getattr(node, "id", "unknown"),
                text="",
                text_length=0,
                hygiene=HygieneFlags(skip_classification=True),
            )
        )
    return paragraphs


def apply_hygiene_by_id(
    paragraphs: list[AnnotatedParagraph],
    toc_markers: list[str],
) -> None:
    toc_patterns = [re.compile(p, re.IGNORECASE) for p in toc_markers]
    in_toc = False

    for para in paragraphs:
        if para.hygiene.skip_classification:
            continue
        text = para.text.strip()
        if not text:
            para.hygiene.is_empty = True
            continue

        if any(p.match(text) for p in toc_patterns):
            in_toc = True
            para.hygiene.is_toc = True
            para.hygiene.skip_classification = True
            continue

        if in_toc:
            if _is_heading_like(text):
                in_toc = False
            else:
                para.hygiene.is_toc = True
                para.hygiene.skip_classification = True
                if TOC_ENTRY_PATTERN.search(text):
                    from flow_ai.core.ast_models import SemanticRole

                    para.resolved_role = "TOC_ENTRY"
                    para.semantic_role = SemanticRole.TOC_ENTRY
                    para.confidence = 0.99
                    para.source = "toc_lock"
                    para.reason_text = "目录区段落"
                    para.suppress_render = True
                continue

    _mark_list_blocks(paragraphs)


def _is_heading_like(text: str) -> bool:
    return bool(
        re.match(r"^\s*第[一二三四五六七八九十百]+[章部分]", text)
        or re.match(r"^\s*\d+\.\d+\s+[\u4e00-\u9fff]", text)
        or re.match(r"^\s*[一二三四五六七八九十]+[、]", text)
    )


def _mark_list_blocks(paragraphs: list[AnnotatedParagraph]) -> None:
    list_pattern = re.compile(r"^\s*(?:\d+\.|（\d+）)\s")
    i = 0
    while i < len(paragraphs):
        if list_pattern.match(paragraphs[i].text):
            j = i
            while j < len(paragraphs) and list_pattern.match(paragraphs[j].text):
                paragraphs[j].hygiene.in_list_block = True
                j += 1
            i = j
        else:
            i += 1
