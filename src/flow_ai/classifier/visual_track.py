"""Pass 1A: visual track — content_role_kb / format_slot_kb lookup."""

from __future__ import annotations

from flow_ai.classifier.pipeline_models import TrackResult
from flow_ai.core.ast_models import ParagraphNode, SemanticRole
from flow_ai.format.ast_reader import ParagraphRecord
from flow_ai.format.knowledge_base import KnowledgeBase
from flow_ai.format.visual_fingerprint import build_fingerprint, fingerprint_key


_SLOT_TO_ROLE: dict[str, tuple[str, SemanticRole | None, int | None]] = {
    "heading_1": ("HEADING_1", SemanticRole.STANDARD, 1),
    "heading_2": ("HEADING_2", SemanticRole.STANDARD, 2),
    "heading_3": ("HEADING_3", SemanticRole.STANDARD, 3),
    "heading_4": ("HEADING_4", SemanticRole.STANDARD, 4),
    "abstract_title": ("ABSTRACT_ANCHOR", SemanticRole.ABSTRACT, 1),
    "abstract_body": ("ABSTRACT_BODY", SemanticRole.ABSTRACT_BODY, None),
    "body_text": ("BODY", SemanticRole.BODY, None),
}


class VisualTrack:
    def __init__(self, kb: KnowledgeBase | None = None, section: str = "body") -> None:
        self._kb = kb
        self._section = section

    def probe(self, node: ParagraphNode) -> TrackResult | None:
        if self._kb is None:
            return None
        record = ParagraphRecord(
            node_id=node.id,
            region=self._section,
            block_index=node.source_index or 0,
            source_index=node.source_index,
            text=node.text.strip(),
            features=node.features,
            spans=tuple(node.spans),
        )
        fp = fingerprint_key(build_fingerprint(record))

        content_hit = self._kb.lookup_content_role(fp, self._section)
        if content_hit is not None:
            role_name, conf = content_hit
            return TrackResult(
                role=role_name,
                confidence=conf,
                level=_level_from_role(role_name),
                source="content_role_kb",
                semantic_role=_semantic_from_role(role_name),
                reason_text="知识库内容角色命中",
            )

        slot_hit = self._kb.lookup(fp, self._section)
        if slot_hit is not None:
            slot_id, conf = slot_hit
            mapped = _SLOT_TO_ROLE.get(slot_id)
            if mapped is not None:
                role_name, sem, level = mapped
                return TrackResult(
                    role=role_name,
                    confidence=conf,
                    level=level,
                    source="format_slot_kb",
                    semantic_role=sem,
                    reason_text=f"格式槽位 {slot_id} 命中",
                )
        return None


def _level_from_role(role: str) -> int | None:
    if role.startswith("HEADING_"):
        try:
            return int(role.split("_")[1])
        except (IndexError, ValueError):
            return None
    return None


def _semantic_from_role(role: str) -> SemanticRole | None:
    mapping = {
        "ABSTRACT_ANCHOR": SemanticRole.ABSTRACT,
        "ABSTRACT_BODY": SemanticRole.ABSTRACT_BODY,
        "BODY": SemanticRole.BODY,
        "REFERENCES_ANCHOR": SemanticRole.REFERENCES,
        "ACK_ANCHOR": SemanticRole.ACKNOWLEDGMENT,
    }
    return mapping.get(role)
