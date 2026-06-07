from __future__ import annotations

from pathlib import Path

from flow_ai.classifier.run_classifier import load_ast_dump, run_draft_classifier, run_pipeline
from flow_ai.contracts.classification_contracts import ResolverResult
from flow_ai.contracts.draft_decisions_v3 import DraftDecisionSidecar
from flow_ai.contracts.error_codes import ErrorCode
from flow_ai.contracts.format_catalog import FormatCatalog
from flow_ai.contracts.status_shell import StatusShell
from flow_ai.core.ast_models import DocumentAST
from flow_ai.format.extractor import extract_format_catalog as run_format_catalog
from flow_ai.format.knowledge_base import KnowledgeBase


class CoreAdapter:

    @staticmethod
    def load_ast_dump(path: str | Path) -> DocumentAST:
        return load_ast_dump(Path(path))

    def classify(self, ast: DocumentAST) -> StatusShell[ResolverResult]:
        classified_ast, result = run_pipeline(ast)
        return StatusShell(data=result)

    def draft_classify(
        self, ast: DocumentAST
    ) -> StatusShell[DraftDecisionSidecar]:
        sidecar, result = run_draft_classifier(ast)
        return StatusShell(data=sidecar)

    def classify_ast(
        self, ast: DocumentAST
    ) -> tuple[DocumentAST, StatusShell[ResolverResult]]:
        classified_ast, result = run_pipeline(ast)
        return classified_ast, StatusShell(data=result)

    def extract_format_catalog(
        self,
        ast: DocumentAST,
        template_path: str | Path | None = None,
        expected_catalog_path: str | Path | None = None,
        knowledge_base: KnowledgeBase | None = None,
    ) -> FormatCatalog:
        return run_format_catalog(ast, template_path, expected_catalog_path, knowledge_base=knowledge_base)
