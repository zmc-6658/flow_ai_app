"""Pass 1B: structural track — regex + numPr signals."""

from __future__ import annotations

import re
from dataclasses import dataclass

from flow_ai.classifier.pipeline_models import AnnotatedParagraph, TrackResult
from flow_ai.core.ast_models import NumberingScheme, ParagraphNode, SemanticRole


@dataclass(frozen=True)
class StructuralRule:
    name: str
    pattern: re.Pattern[str]
    role: str
    level: int | None
    confidence: float
    semantic_role: SemanticRole | None = None


@dataclass(frozen=True)
class DocTypeConfig:
    doc_type: str
    structural_rules: tuple[StructuralRule, ...]
    special_anchors: tuple[StructuralRule, ...]
    toc_markers: tuple[str, ...]


class StructuralTrack:
    def __init__(self, config: DocTypeConfig) -> None:
        self._config = config
        self._rules = config.structural_rules + config.special_anchors

    def probe(self, node: ParagraphNode, para: AnnotatedParagraph) -> TrackResult | None:
        text = para.text.strip()
        if not text:
            return None

        for rule in self._rules:
            m = rule.pattern.match(text)
            if m is None:
                continue
            reason = f"结构匹配：{rule.name}"
            return TrackResult(
                role=rule.role,
                confidence=rule.confidence,
                level=rule.level,
                source="regex",
                semantic_role=rule.semantic_role,
                reason_text=reason,
            )

        numpr = self._numpr_signal(node)
        if numpr is not None:
            return numpr
        return None

    def _numpr_signal(self, node: ParagraphNode) -> TrackResult | None:
        if node.numbering is None or node.numbering.scheme == NumberingScheme.NONE:
            return None
        raw = node.numbering.raw_text or node.numbering.computed_value
        if not raw:
            return TrackResult(
                role="LIST_L0",
                confidence=0.75,
                level=1,
                source="numpr",
                reason_text="Word 自动编号",
            )
        depth = raw.count(".") + 1
        return TrackResult(
            role=f"LIST_L{min(depth - 1, 3)}",
            confidence=0.75,
            level=min(depth, 4),
            source="numpr",
            reason_text=f"自动编号 {raw}",
        )


def parse_config(raw: dict) -> DocTypeConfig:
    def _rules(key: str) -> tuple[StructuralRule, ...]:
        items = raw.get(key, [])
        out: list[StructuralRule] = []
        for item in items:
            sem = item.get("semantic_role")
            out.append(
                StructuralRule(
                    name=item.get("name", item["role"]),
                    pattern=re.compile(item["pattern"], re.IGNORECASE),
                    role=item["role"],
                    level=item.get("level"),
                    confidence=float(item["confidence"]),
                    semantic_role=SemanticRole(sem) if sem else None,
                )
            )
        return tuple(out)

    return DocTypeConfig(
        doc_type=raw.get("doc_type", "thesis"),
        structural_rules=_rules("structural_rules"),
        special_anchors=_rules("special_anchors"),
        toc_markers=tuple(raw.get("toc_markers", [])),
    )
