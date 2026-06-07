from __future__ import annotations

import sys
from pathlib import Path

if __package__ in (None, ""):
    sys.path.append(str(Path(__file__).resolve().parents[2]))

from flow_ai.classifier.heading_binder import HeadingBinder
from flow_ai.classifier.pattern_probe import PatternProbe
from flow_ai.classifier.run_classifier import load_ast_dump
from flow_ai.classifier.structure_resolver import StructureResolver
from flow_ai.core.ast_models import DocumentAST, HeadingNode


class RegexClassifier:

    def classify(self, ast: DocumentAST) -> DocumentAST:

        matches = PatternProbe().probe(ast)
        decisions = StructureResolver().resolve(ast, matches)
        return HeadingBinder().bind(ast, decisions)


if __name__ == "__main__":
    ast_path = Path(__file__).resolve().parents[2] / "ast_dump.json"
    ast = load_ast_dump(ast_path)
    classified = RegexClassifier().classify(ast)

    for node in classified.blocks:
        if isinstance(node, HeadingNode):
            print(f"[H{node.level}] (id: {node.id}) {node.text}")
