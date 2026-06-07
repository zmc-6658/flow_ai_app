from __future__ import annotations

from typing import Any

from flow_ai.contracts.classification_contracts import ClassificationDecision
from flow_ai.core.ast_models import (
    DocumentAST,
    GeneratedAnchorNode,
    HeadingNode,
    OpaqueNode,
    ParagraphNode,
)


def build_ast_projection(
    ast: DocumentAST,
    decisions: list[ClassificationDecision] | None = None,
) -> list[dict[str, Any]]:
    decision_by_node_id: dict[str, ClassificationDecision] = {}
    if decisions is not None:
        decision_by_node_id = {d.node_id: d for d in decisions}

    flat: list[dict[str, Any]] = []
    for node in ast.blocks:
        block: dict[str, Any] = {
            "id": node.id,
            "node_kind": node.kind,
            "suppress_render": node.suppress_render,
        }

        if isinstance(node, GeneratedAnchorNode):
            block["text"] = f"[{node.anchor_type.upper()}]"
        elif isinstance(node, OpaqueNode):
            block["text"] = node.text_preview or f"[{node.opaque_type.value}]"
        elif isinstance(node, (HeadingNode, ParagraphNode)):
            block["text"] = node.text
        else:
            block["text"] = ""

        if isinstance(node, HeadingNode):
            block["level"] = node.level
            block["semantic_role"] = node.semantic_role.value

        decision = decision_by_node_id.get(node.id)
        if decision is not None:
            block["region"] = decision.region.value
            if not isinstance(node, HeadingNode):
                block["semantic_role"] = decision.semantic_role.value
            if node.kind != "generated_anchor":
                block["suppress_render"] = block["suppress_render"] or decision.suppress_render

        flat.append(block)

    return flat


def build_ast_tree(
    ast: DocumentAST,
    decisions: list[ClassificationDecision] | None = None,
) -> list[dict[str, Any]]:
    flat = build_ast_projection(ast, decisions)
    return _build_tree_from_flat(flat)


def _build_tree_from_flat(flat: list[dict[str, Any]]) -> list[dict[str, Any]]:
    root: list[dict[str, Any]] = []
    stack: list[dict[str, Any]] = []

    for block in flat:
        node_kind = block["node_kind"]
        level = block.get("level")

        if node_kind == "heading" and level is not None:
            node = dict(block, children=[])

            while stack and stack[-1].get("level", 0) >= level:
                stack.pop()

            if stack:
                stack[-1]["children"].append(node)
            else:
                root.append(node)

            stack.append(node)
        else:
            if stack:
                stack[-1]["children"].append(block)
            else:
                node = dict(block, children=[])
                root.append(node)
                stack.append(node)

    _clean_empty_children(root)
    return root


def _clean_empty_children(nodes: list[dict[str, Any]]) -> None:
    for node in nodes:
        children = node.get("children")
        if children is not None and len(children) == 0:
            del node["children"]
        elif children is not None:
            _clean_empty_children(children)


def decisions_to_dicts(
    decisions: list[ClassificationDecision],
    style_assignments: dict[str, str | None] | None = None,
) -> list[dict[str, Any]]:
    assignments = style_assignments or {}
    rows: list[dict[str, Any]] = []
    for decision in decisions:
        row = decision.model_dump(mode="json")
        if decision.node_id in assignments:
            row["assigned_style_id"] = assignments[decision.node_id]
        rows.append(row)
    return rows