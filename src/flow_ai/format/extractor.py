from __future__ import annotations

from pathlib import Path

from flow_ai.contracts.format_catalog import FormatCatalog
from flow_ai.core.ast_models import DocumentAST
from flow_ai.format.ast_intent_builder import create_intent_context
from flow_ai.format.ast_reader import read_paragraphs_from_ast
from flow_ai.format.knowledge_base import KnowledgeBase
from flow_ai.format.slot_aligner import align_slots, load_expected_catalog


def extract_format_catalog(
    ast: DocumentAST,
    template_path: str | Path | None = None,
    expected_catalog_path: str | Path | None = None,
    knowledge_base: KnowledgeBase | None = None,
) -> FormatCatalog:
    read_result = read_paragraphs_from_ast(ast)
    if template_path is not None:
        read_result.ast.metadata["source_path"] = str(Path(template_path).resolve())

    intent_context = None
    if template_path is not None:
        intent_context = create_intent_context(Path(template_path))

    expected = None
    if expected_catalog_path is not None:
        expected = load_expected_catalog(Path(expected_catalog_path))

    return align_slots(read_result, intent_context, expected, knowledge_base=knowledge_base)
