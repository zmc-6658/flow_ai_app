from __future__ import annotations

from flow_ai.contracts.classification_contracts import ClassificationDecision
from flow_ai.core.ast_models import (
    DocumentAST,
    GeneratedAnchorNode,
    HeadingNode,
    OpaqueNode,
    ParagraphNode,
    SemanticRole,
)
from flow_ai.core.style_models import RenderPlan, RuleNode, StyleIntent


class RuleEngine:

    def __init__(self, rules: list[RuleNode]) -> None:
        self.rules = rules

    def compile_plan(
        self, ast: DocumentAST, decisions: list[ClassificationDecision]
    ) -> RenderPlan:

        decision_by_node_id = {decision.node_id: decision for decision in decisions}
        node_styles: dict[str, StyleIntent] = {}
        rule_trace: dict[str, list[str]] = {}

        for node in ast.blocks:
            decision = decision_by_node_id.get(node.id)
            trace: list[str] = []

            if self._is_suppressed(node, decision):
                trace.append("skip: suppress_render=True")
                rule_trace[node.id] = trace
                continue

            context = self._build_context(node, decision)
            matched_rules = [
                rule for rule in self.rules if rule.selector.matches(context)
            ]

            if not matched_rules:
                trace.append("no_match: no style intent assigned")
                rule_trace[node.id] = trace
                continue

            final_intent = StyleIntent()
            field_owner: dict[str, str] = {}
            for rule in sorted(matched_rules, key=lambda item: item.priority):
                applied_fields = rule.apply.model_dump(exclude_none=True)
                trace.append(
                    f"match: {rule.id} priority={rule.priority} "
                    f"fields={sorted(applied_fields)}"
                )

                for field_name in applied_fields:
                    previous_owner = field_owner.get(field_name)
                    if previous_owner is not None:
                        trace.append(
                            f"override: {field_name} {previous_owner} -> {rule.id}"
                        )
                    field_owner[field_name] = rule.id

                final_intent = final_intent.merge(rule.apply)

            node_styles[node.id] = final_intent
            winners = ", ".join(
                f"{field_name}={rule_id}"
                for field_name, rule_id in sorted(field_owner.items())
            )
            trace.append(f"final: {winners}" if winners else "final: empty intent")
            rule_trace[node.id] = trace

        return RenderPlan(node_styles=node_styles, rule_trace=rule_trace)

    def _is_suppressed(
        self,
        node: object,
        decision: ClassificationDecision | None,
    ) -> bool:
        return bool(
            decision is not None
            and decision.suppress_render
            or getattr(node, "suppress_render", False)
        )

    def _build_context(
        self,
        node: object,
        decision: ClassificationDecision | None,
    ) -> dict[str, object]:
        semantic_role = (
            decision.semantic_role
            if decision is not None
            else node.semantic_role
            if isinstance(node, HeadingNode)
            else SemanticRole.STANDARD
        )
        level = (
            node.level
            if isinstance(node, HeadingNode)
            else decision.suggested_level
            if decision is not None
            else None
        )

        return {
            "node_kind": getattr(node, "kind", None),
            "semantic_role": semantic_role,
            "level": level,
            "region": decision.region if decision is not None else None,
            "anchor_type": node.anchor_type
            if isinstance(node, GeneratedAnchorNode)
            else None,
            "opaque_type": node.opaque_type if isinstance(node, OpaqueNode) else None,
            "is_paragraph": isinstance(node, ParagraphNode),
        }
