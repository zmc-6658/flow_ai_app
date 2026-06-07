from __future__ import annotations

import re

from flow_ai.classifier.classifier_models import (
    CandidateType,
    ClassificationDecision,
    DraftClassificationDecision,
    DraftDecisionSidecar,
    EvidenceItem,
    PatternMatch,
    PatternType,
    ResolverResult,
)
from flow_ai.core.enums import DocumentRegion
from flow_ai.classifier.pattern_probe import PatternProbe
from flow_ai.classifier.structure_resolver import StructureResolver
from flow_ai.core.ast_models import (
    DocumentAST,
    GeneratedAnchorNode,
    HeadingNode,
    OpaqueNode,
    ParagraphNode,
    SemanticRole,
)


class EvidenceClassifier:

    def classify(self, ast: DocumentAST) -> tuple[DraftDecisionSidecar, ResolverResult]:
        matches = PatternProbe().probe(ast)
        result = StructureResolver().resolve(ast, matches)
        return self.build_sidecar(ast, matches, result), result

    def build_sidecar(
        self,
        ast: DocumentAST,
        matches: list[PatternMatch],
        result: ResolverResult,
    ) -> DraftDecisionSidecar:
        match_by_node_id = {match.node_id: match for match in matches}
        decision_by_node_id = {decision.node_id: decision for decision in result.decisions}
        draft_decisions: dict[str, DraftClassificationDecision] = {}

        for node in ast.blocks:
            decision = decision_by_node_id.get(node.id)
            match = match_by_node_id.get(node.id)
            evidence = self._collect_evidence(node, decision, match)
            semantic_role = self._draft_role(node, decision, match)
            confidence = self._confidence(node, decision, semantic_role)

            draft_decisions[node.id] = DraftClassificationDecision(
                node_id=node.id,
                region=decision.region if decision is not None else DocumentRegion.BODY,
                candidate_type=decision.candidate_type.value if decision is not None else "paragraph",
                suggested_level=decision.suggested_level if decision is not None else None,
                semantic_role=SemanticRole(semantic_role) if self._is_valid_role(semantic_role) else SemanticRole.STANDARD,
                confidence=confidence,
                reasons=[self._format_evidence(item) for item in evidence],
            )

        return DraftDecisionSidecar(decisions=list(draft_decisions.values()))

    def _collect_evidence(
        self,
        node: object,
        decision: ClassificationDecision | None,
        match: PatternMatch | None,
    ) -> list[EvidenceItem]:
        evidence: list[EvidenceItem] = []

        evidence.append(
            EvidenceItem(
                source="node",
                label=f"kind={getattr(node, 'kind', type(node).__name__)}",
                detail=f"source_index={getattr(node, 'source_index', None)}",
                weight=0.0,
            )
        )

        if isinstance(node, ParagraphNode):
            features = node.features
            evidence.extend(
                [
                    EvidenceItem(
                        source="physical",
                        label="text_length",
                        detail=str(features.text_length),
                        weight=0.0,
                    ),
                    EvidenceItem(
                        source="physical",
                        label="alignment",
                        detail=features.alignment.value,
                        weight=0.1 if features.alignment.value != "unknown" else 0.0,
                    ),
                ]
            )
            if features.dominant_font_size is not None:
                evidence.append(
                    EvidenceItem(
                        source="physical",
                        label="dominant_font_size",
                        detail=f"{features.dominant_font_size}pt",
                        weight=0.1,
                    )
                )
            if features.bold_ratio > 0:
                evidence.append(
                    EvidenceItem(
                        source="physical",
                        label="bold_ratio",
                        detail=f"{features.bold_ratio:.2f}",
                        weight=min(features.bold_ratio, 1.0) * 0.2,
                    )
                )

        if match is not None:
            evidence.append(
                EvidenceItem(
                    source="pattern_probe",
                    label=match.pattern_type.value,
                    detail=f"marker='{match.raw_marker}', depth={match.marker_depth}",
                    weight=0.35,
                )
            )
            if match.semantic_role != SemanticRole.STANDARD:
                evidence.append(
                    EvidenceItem(
                        source="pattern_probe",
                        label="semantic_keyword",
                        detail=match.semantic_role.value,
                        weight=0.4,
                    )
                )

        if decision is not None:
            for reason in decision.reasons:
                evidence.append(
                    EvidenceItem(
                        source="structure_resolver",
                        label=reason,
                        detail=(
                            f"region={decision.region.value}, "
                            f"candidate={decision.candidate_type.value}"
                        ),
                        weight=0.2,
                    )
                )

        return evidence

    def _draft_role(
        self,
        node: object,
        decision: ClassificationDecision | None,
        match: PatternMatch | None,
    ) -> str:
        if isinstance(node, OpaqueNode):
            return f"opaque_{node.opaque_type.value}"
        if isinstance(node, GeneratedAnchorNode):
            return f"generated_{node.anchor_type}"
        if isinstance(node, HeadingNode):
            return f"heading_{node.level}"
        if decision is None:
            return "unknown"
        if decision.suppress_render:
            return "suppressed"
        sniffed_role = self._sniff_text_role(node, decision)
        if sniffed_role is not None:
            return sniffed_role
        if decision.semantic_role != SemanticRole.STANDARD:
            return decision.semantic_role.value
        if (
            decision.candidate_type == CandidateType.HEADING
            and decision.suggested_level is not None
        ):
            if (
                match is not None
                and match.pattern_type == PatternType.ARABIC_DECIMAL
                and match.marker_depth >= 2
            ):
                return f"heading_{min(match.marker_depth, 9)}"
            return f"heading_{decision.suggested_level}"
        if decision.candidate_type == CandidateType.LIST_ITEM:
            return "list_item"
        if decision.region == DocumentRegion.BODY:
            return SemanticRole.BODY.value
        if decision.region == DocumentRegion.BACK:
            return "back_paragraph"
        if decision.region == DocumentRegion.FRONT:
            return "front_paragraph"
        return "paragraph"

    def _sniff_text_role(
        self,
        node: object,
        decision: ClassificationDecision,
    ) -> str | None:
        if not isinstance(node, ParagraphNode):
            return None

        text = node.text.strip()
        compact_text = re.sub(r"\s+", "", text).lower()
        if decision.region == DocumentRegion.FRONT:
            if compact_text.startswith("摘要") and len(compact_text) > 2:
                return SemanticRole.ABSTRACT_BODY.value
            if compact_text.startswith("abstract") and len(compact_text) > 8:
                return SemanticRole.ABSTRACT_BODY.value
            if compact_text.startswith("关键词") or compact_text.startswith("keywords"):
                return SemanticRole.KEYWORDS.value
        if decision.region == DocumentRegion.BACK:
            if re.match(r"^(\[\d+\]|［\d+］|\d+[.．、]\s*)", text):
                return SemanticRole.REFERENCES_ITEM.value
            if decision.semantic_role == SemanticRole.ACKNOWLEDGMENT:
                return SemanticRole.ACKNOWLEDGMENT_BODY.value
            if decision.semantic_role == SemanticRole.APPENDIX:
                return SemanticRole.APPENDIX_BODY.value
        if re.match(r"^(图|Figure)\s*\d+", text, re.IGNORECASE):
            return SemanticRole.FIGURE_CAPTION.value
        if re.match(r"^(表|Table)\s*\d+", text, re.IGNORECASE):
            return SemanticRole.TABLE_CAPTION.value
        return None

    def _confidence(
        self,
        node: object,
        decision: ClassificationDecision | None,
        semantic_role: str,
    ) -> float:
        if isinstance(node, OpaqueNode | GeneratedAnchorNode):
            return 1.0
        if decision is None:
            return 0.2
        if semantic_role in {
            SemanticRole.ABSTRACT_BODY.value,
            SemanticRole.KEYWORDS.value,
        }:
            return max(decision.confidence, 0.72)
        if semantic_role == SemanticRole.REFERENCES_ITEM.value:
            return max(decision.confidence, 0.8)
        if semantic_role in {
            SemanticRole.FIGURE_CAPTION.value,
            SemanticRole.TABLE_CAPTION.value,
        }:
            return max(decision.confidence, 0.7)
        if semantic_role in {"body", "front_paragraph", "back_paragraph"}:
            return max(decision.confidence, 0.65 if semantic_role == "body" else 0.45)
        return decision.confidence

    def _text_preview(self, node: object, limit: int = 120) -> str:
        if isinstance(node, ParagraphNode):
            return node.text.replace("\n", " ")[:limit]
        if isinstance(node, OpaqueNode):
            return node.text_preview[:limit]
        if isinstance(node, GeneratedAnchorNode):
            return f"generated anchor: {node.anchor_type}"
        return ""

    @staticmethod
    def _is_valid_role(role_str: str) -> bool:
        try:
            SemanticRole(role_str)
            return True
        except ValueError:
            return False

    def _format_evidence(self, evidence: EvidenceItem) -> str:
        detail = f": {evidence.detail}" if evidence.detail else ""
        return f"[{evidence.source}] {evidence.label}{detail}"
