from __future__ import annotations

import json
import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from flow_ai.classifier.evidence_classifier import EvidenceClassifier
from flow_ai.classifier.phase3_pipeline import Phase3Pipeline
from flow_ai.classifier.heading_binder import HeadingBinder
from flow_ai.format.knowledge_base import KnowledgeBase, _DEFAULT_DB_PATH
from flow_ai.classifier.classifier_models import DraftDecisionSidecar, ResolverResult
from flow_ai.core.ast_models import (
    DocumentAST,
    GeneratedAnchorNode,
    HeadingNode,
    ParagraphNode,
)


def load_ast_dump(path: Path) -> DocumentAST:

    return DocumentAST.from_persisted_json_file(path)


def run_pipeline(ast: DocumentAST, kb: KnowledgeBase | None = None) -> tuple[DocumentAST, ResolverResult]:

    pipeline = Phase3Pipeline(kb=kb or KnowledgeBase(_DEFAULT_DB_PATH))
    _, result = pipeline.run(ast)
    return HeadingBinder().bind(ast, result), result


def run_draft_classifier(ast: DocumentAST) -> tuple[DraftDecisionSidecar, ResolverResult]:

    return EvidenceClassifier().classify(ast)


def save_draft_decisions(
    sidecar: DraftDecisionSidecar,
    output_path: Path,
) -> None:

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps([d.model_dump(mode="json") for d in sidecar.decisions], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run(ast: DocumentAST) -> DocumentAST:

    classified_ast, _ = run_pipeline(ast)
    return classified_ast


def print_outline(ast: DocumentAST, result: ResolverResult) -> None:

    decision_by_node_id = {decision.node_id: decision for decision in result.decisions}
    for node in ast.blocks:
        if isinstance(node, GeneratedAnchorNode):
            print(
                f"[ANCHOR] type={node.anchor_type} id={node.id} suppress={node.suppress_render}"
            )
            continue

        decision = decision_by_node_id.get(node.id)
        region = decision.region.value if decision is not None else "unknown"
        role = (
            node.semantic_role.value
            if isinstance(node, HeadingNode)
            else decision.semantic_role.value
            if decision is not None
            else "standard"
        )

        if isinstance(node, HeadingNode):
            print(
                f"[{region.upper()}][H{node.level}][role={role}][suppress={node.suppress_render}] "
                f"(id: {node.id}) {node.text}"
            )
            continue

        if isinstance(node, ParagraphNode) and node.suppress_render:
            preview = node.text.replace("\n", " ")[:80]
            print(
                f"[{region.upper()}][SUPPRESS][role={role}][suppress=True] "
                f"(id: {node.id}) {preview}"
            )


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parents[2]
    ast_path = project_root / "ast_dump.json"
    output_path = project_root / "outputs" / "draft_decisions.json"
    ast = load_ast_dump(ast_path)
    draft_sidecar, resolver_result = run_draft_classifier(ast)
    save_draft_decisions(draft_sidecar, output_path)
    print(f"Saved draft decisions: {output_path}")
    print(f"Draft decision count: {len(draft_sidecar.decisions)}")
