from __future__ import annotations

from uuid import uuid4

from flow_ai.classifier.classifier_models import (
    CandidateType,
    ClassificationDecision,
    ResolverResult,
)
from flow_ai.core.ast_models import (
    DocumentAST,
    GeneratedAnchorNode,
    HeadingNode,
    OpaqueNode,
    ParagraphNode,
)


class HeadingBinder:

    def __init__(self, min_confidence: float = 0.75) -> None:
        self.min_confidence = min_confidence

    def bind(self, ast: DocumentAST, result: ResolverResult) -> DocumentAST:

        decision_by_node_id = {decision.node_id: decision for decision in result.decisions}

        updated_blocks: list[
            HeadingNode | ParagraphNode | OpaqueNode | GeneratedAnchorNode
        ] = []
        toc_anchor_inserted = False
        toc_anchor_node_id = result.toc_anchor_node_id or result.body_start_node_id
        for node in ast.blocks:
            if (
                result.needs_toc_anchor
                and not toc_anchor_inserted
                and node.id == toc_anchor_node_id
            ):
                updated_blocks.append(
                    GeneratedAnchorNode(
                        id=f"anchor_toc_{uuid4().hex[:8]}",
                        anchor_type="toc",
                    )
                )
                toc_anchor_inserted = True

            decision = decision_by_node_id.get(node.id)

            if isinstance(node, OpaqueNode | GeneratedAnchorNode):
                updated_blocks.append(
                    node.model_copy(
                        update={"suppress_render": decision.suppress_render}
                    )
                    if decision is not None
                    else node
                )
                continue

            if isinstance(node, HeadingNode):
                updated_blocks.append(
                    node.model_copy(
                        update={
                            "semantic_role": decision.semantic_role,
                            "suppress_render": decision.suppress_render,
                        }
                    )
                    if decision is not None
                    else node
                )
                continue

            if not isinstance(node, ParagraphNode):
                updated_blocks.append(node)
                continue

            if decision is None:
                updated_blocks.append(node)
                continue

            should_bind_heading = (
                decision.candidate_type == CandidateType.HEADING
                and decision.suggested_level is not None
                and decision.confidence >= self.min_confidence
            )
            if not should_bind_heading:
                updated_blocks.append(
                    node.model_copy(update={"suppress_render": decision.suppress_render})
                )
                continue

            updated_blocks.append(
                HeadingNode(
                    id=node.id,
                    source_index=node.source_index,
                    numbering=node.numbering,
                    suppress_render=decision.suppress_render,
                    spans=node.spans,
                    features=node.features,
                    level=decision.suggested_level,
                    semantic_role=decision.semantic_role,
                )
            )

        return DocumentAST(
            id=ast.id,
            blocks=updated_blocks,
            reference_graph=ast.reference_graph,
            metadata=ast.metadata,
            headers=ast.headers,
            footers=ast.footers,
            footnotes=ast.footnotes,
            endnotes=ast.endnotes,
            sections=ast.sections,
            parse_metadata=ast.parse_metadata,
        )
