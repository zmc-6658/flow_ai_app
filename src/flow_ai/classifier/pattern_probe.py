from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Pattern

from flow_ai.classifier.classifier_models import PatternMatch, PatternType
from flow_ai.core.ast_models import (
    DocumentAST,
    GeneratedAnchorNode,
    HeadingNode,
    OpaqueNode,
    ParagraphNode,
    SemanticRole,
)


SENTENCE_ENDINGS = ("。", ".", "！", "!", "？", "?")
TOC_PAGE_TRAILING_PATTERN = re.compile(r"(?:[\t ]+|\.{2,}|。{2,}|…{1,})\d+\s*$")


@dataclass(frozen=True)
class ProbeRule:

    pattern_type: PatternType
    pattern: Pattern[str]


class PatternProbe:

    rules: tuple[ProbeRule, ...] = (
        ProbeRule(
            pattern_type=PatternType.TOC_ENTRY,
            pattern=TOC_PAGE_TRAILING_PATTERN,
        ),
        ProbeRule(
            pattern_type=PatternType.UNNUMBERED_SPECIAL,
            pattern=re.compile(
                r"^\s*(?P<marker>目\s*录|前\s*言|摘\s*要|Abstract|参\s*考\s*文\s*献|致\s*谢|附\s*录)\s*$",
                re.IGNORECASE,
            ),
        ),
        ProbeRule(
            pattern_type=PatternType.CHAPTER,
            pattern=re.compile(
                r"^\s*(?P<marker>第[一二三四五六七八九十百零〇两]+[章部分])"
            ),
        ),
        ProbeRule(
            pattern_type=PatternType.ARABIC_DECIMAL,
            pattern=re.compile(
                r"^\s*(?P<marker>\d+(?:\.\d+)+\.?)\s*[\u4e00-\u9fffA-Za-z]"
            ),
        ),
        ProbeRule(
            pattern_type=PatternType.CHINESE_PAREN,
            pattern=re.compile(
                r"^\s*(?P<marker>[（\(][一二三四五六七八九十]+[）\)])\s*[\u4e00-\u9fffA-Za-z]"
            ),
        ),
        ProbeRule(
            pattern_type=PatternType.ARABIC_SINGLE,
            pattern=re.compile(r"^\s*(?P<marker>\d+\.?)\s+[\u4e00-\u9fffA-Za-z]"),
        ),
        ProbeRule(
            pattern_type=PatternType.CHINESE_DUN,
            pattern=re.compile(
                r"^\s*(?P<marker>[一二三四五六七八九十]+[、\s]+)[\u4e00-\u9fffA-Za-z]"
            ),
        ),
    )

    def probe(self, ast: DocumentAST) -> list[PatternMatch]:

        matches: list[PatternMatch] = []
        for node in ast.blocks:
            if isinstance(node, OpaqueNode | HeadingNode | GeneratedAnchorNode):
                continue
            if not isinstance(node, ParagraphNode):
                continue
            text = node.text
            match = self._match_node(node, text)
            if match is not None:
                matches.append(match)
        return matches

    def _match_node(self, node: ParagraphNode, text: str) -> PatternMatch | None:

        for rule in self.rules:
            match = (
                rule.pattern.search(text)
                if rule.pattern_type == PatternType.TOC_ENTRY
                else rule.pattern.match(text)
            )
            if match is None:
                continue
            if rule.pattern_type != PatternType.TOC_ENTRY and not self._passes_physical_qa(
                node, text
            ):
                continue
            raw_marker = (
                text.strip()
                if rule.pattern_type == PatternType.TOC_ENTRY
                else match.group("marker")
            )
            return PatternMatch(
                node_id=node.id,
                text=text,
                raw_marker=raw_marker.strip(),
                pattern_type=rule.pattern_type,
                marker_depth=self._marker_depth(rule.pattern_type, raw_marker),
                semantic_role=self._semantic_role(rule.pattern_type, raw_marker),
                has_toc_page_trailing=TOC_PAGE_TRAILING_PATTERN.search(text) is not None,
            )
        return None

    def _passes_physical_qa(self, node: ParagraphNode, text: str) -> bool:

        if node.features.text_length > 60:
            return False
        if text.strip() == "":
            return False
        if text.rstrip().endswith(SENTENCE_ENDINGS):
            return False
        if TOC_PAGE_TRAILING_PATTERN.search(text):
            return False
        return True

    def _marker_depth(self, pattern_type: PatternType, raw_marker: str) -> int:

        if pattern_type == PatternType.ARABIC_DECIMAL:
            return len(raw_marker.rstrip(".").split("."))
        return 1

    def _semantic_role(
        self, pattern_type: PatternType, raw_marker: str
    ) -> SemanticRole:

        if pattern_type != PatternType.UNNUMBERED_SPECIAL:
            return SemanticRole.STANDARD

        normalized = re.sub(r"\s+", "", raw_marker).lower()
        if normalized in {"目录", "tableofcontents"}:
            return SemanticRole.TOC
        if normalized in {"摘要", "abstract"}:
            return SemanticRole.ABSTRACT
        if normalized == "参考文献":
            return SemanticRole.REFERENCES
        if normalized == "致谢":
            return SemanticRole.ACKNOWLEDGMENT
        if normalized == "附录":
            return SemanticRole.APPENDIX
        return SemanticRole.STANDARD
