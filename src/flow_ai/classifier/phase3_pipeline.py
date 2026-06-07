"""Phase 3 orchestrator: dual-track → arbitration → probe → stack → decisions."""

from __future__ import annotations

from flow_ai.classifier.arbitration import apply_arbitration, arbitrate_role
from flow_ai.classifier.context_stack import ContextStack
from flow_ai.classifier.doc_type_router import detect_doc_type, load_doc_type_config
from flow_ai.classifier.naked_probe import NakedHeadingProbe
from flow_ai.classifier.phase0_hygiene import apply_hygiene_by_id, build_paragraph_list
from flow_ai.classifier.pipeline_models import AnnotatedParagraph
from flow_ai.classifier.structural_track import StructuralTrack
from flow_ai.classifier.visual_track import VisualTrack
from flow_ai.contracts.classification_contracts import (
    CandidateType,
    ClassificationDecision,
    DocumentContentTree,
    ResolverResult,
)
from flow_ai.core.ast_models import DocumentAST, ParagraphNode, SemanticRole
from flow_ai.core.enums import DocumentRegion
from flow_ai.format.knowledge_base import KnowledgeBase

HEADING_ROLE_PREFIX = ("HEADING_", "SUSPECTED_HEADING", "ABSTRACT_ANCHOR", "REFERENCES_ANCHOR", "ACK_ANCHOR")


class Phase3Pipeline:
    def __init__(self, kb: KnowledgeBase | None = None) -> None:
        self._kb = kb

    def run(self, ast: DocumentAST) -> tuple[list[AnnotatedParagraph], ResolverResult]:
        doc_type = detect_doc_type(ast)
        config = load_doc_type_config(doc_type)
        structural = StructuralTrack(config)
        visual = VisualTrack(self._kb)

        paragraphs = build_paragraph_list(ast)
        apply_hygiene_by_id(paragraphs, list(config.toc_markers))

        para_by_id = {p.node_id: p for p in paragraphs}
        block_paragraphs = [
            para_by_id[node.id]
            for node in ast.blocks
            if isinstance(node, ParagraphNode) and node.id in para_by_id
        ]

        for idx, node in enumerate(ast.blocks):
            if not isinstance(node, ParagraphNode):
                continue
            para = para_by_id[node.id]
            if para.hygiene.skip_classification and para.resolved_role:
                continue
            if para.hygiene.skip_classification:
                continue

            para.structural = structural.probe(node, para)
            para.visual = visual.probe(node)

            next_long = False
            if idx + 1 < len(ast.blocks):
                nxt = ast.blocks[idx + 1]
                if isinstance(nxt, ParagraphNode):
                    next_long = len(nxt.text.strip()) > 50

            outcome = arbitrate_role(para.visual, para.structural, next_para_long=next_long)
            apply_arbitration(para, outcome)
            if para.structural and para.structural.semantic_role and para.semantic_role == SemanticRole.STANDARD:
                if para.resolved_role and para.resolved_role.endswith("_ANCHOR"):
                    para.semantic_role = para.structural.semantic_role

        probe = NakedHeadingProbe()
        for i, para in enumerate(block_paragraphs):
            if para.resolved_role is not None:
                continue
            prev_p = block_paragraphs[i - 1] if i > 0 else None
            next_p = block_paragraphs[i + 1] if i + 1 < len(block_paragraphs) else None
            probe.probe(para, prev_p, next_p)

        stack = ContextStack()
        for para in block_paragraphs:
            stack.process(para)

        content_tree = stack.build_tree(block_paragraphs)
        decisions = self._to_decisions(ast, paragraphs)
        body_start = _find_body_start(decisions)
        result = ResolverResult(
            decisions=decisions,
            needs_toc_anchor=True,
            toc_anchor_node_id=body_start,
            body_start_node_id=body_start,
            content_tree=content_tree,
        )
        return paragraphs, result

    def _to_decisions(
        self,
        ast: DocumentAST,
        paragraphs: list[AnnotatedParagraph],
    ) -> list[ClassificationDecision]:
        by_id = {p.node_id: p for p in paragraphs}
        decisions: list[ClassificationDecision] = []
        for node in ast.blocks:
            para = by_id.get(node.id)
            if para is None:
                continue
            decisions.append(_annotated_to_decision(para))
        return decisions


def _annotated_to_decision(para: AnnotatedParagraph) -> ClassificationDecision:
    role = para.resolved_role or "BODY"
    candidate_type = CandidateType.PARAGRAPH
    suggested_level = None

    if role.startswith("HEADING_") or role == "SUSPECTED_HEADING":
        candidate_type = CandidateType.HEADING
        suggested_level = para.resolved_level or para.structural_level
        if role.startswith("HEADING_"):
            try:
                suggested_level = int(role.split("_")[1])
            except (IndexError, ValueError):
                pass
    elif role.endswith("_ANCHOR"):
        candidate_type = CandidateType.HEADING
        suggested_level = 1
    elif role == "LIST_ITEM":
        candidate_type = CandidateType.LIST_ITEM

    reasons = [para.source]
    if para.reason_text:
        reasons.append(para.reason_text)

    return ClassificationDecision(
        node_id=para.node_id,
        region=para.region,
        candidate_type=candidate_type,
        suggested_level=suggested_level,
        semantic_role=para.semantic_role,
        suppress_render=para.suppress_render,
        confidence=para.confidence,
        reasons=reasons,
        reason_text=para.reason_text or None,
        source=para.source,
        requires_user_review=para.requires_user_review,
        structural_level=para.structural_level,
        style_slot_id=para.style_slot_id,
        breadcrumb=para.breadcrumb,
        section_path=para.section_path or None,
    )


def _find_body_start(decisions: list[ClassificationDecision]) -> str | None:
    for d in decisions:
        if d.region == DocumentRegion.BODY and d.candidate_type == CandidateType.HEADING:
            return d.node_id
    for d in decisions:
        if d.region == DocumentRegion.BODY:
            return d.node_id
    return decisions[0].node_id if decisions else None
