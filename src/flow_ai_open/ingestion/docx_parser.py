from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from docx import Document

from flow_ai.core.ast_models import DocumentAST, ParseMetadata
from flow_ai.core.preservation_models import AssetStore
from flow_ai_open.ingestion.body_block_parser import BlockParseContext, BodyBlockParser
from flow_ai_open.ingestion.comment_reader import read_comments
from flow_ai_open.ingestion.coverage_report import build_coverage_report
from flow_ai_open.ingestion.document_resources import read_document_resources
from flow_ai_open.ingestion.footnote_reader import FootnoteReader
from flow_ai_open.ingestion.header_footer_reader import HeaderFooterReader


class DocxParser:

    def __init__(self) -> None:
        self.asset_store = AssetStore()
        self._ctx = BlockParseContext(asset_store=self.asset_store)
        self._block_parser = BodyBlockParser(self._ctx)

    def parse(self, docx_path: str | Path) -> DocumentAST:
        ast, _ = self.parse_with_assets(docx_path)
        return ast

    def parse_with_assets(
        self, docx_path: str | Path
    ) -> tuple[DocumentAST, AssetStore]:
        path = Path(docx_path)
        if not path.exists():
            raise FileNotFoundError(path)
        if path.suffix.lower() != ".docx":
            raise ValueError(f"需要 .docx 文件，当前输入: {path}")

        # 大文件保护：超过 100MB 的 DOCX 可能导致内存溢出
        MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
        file_size = path.stat().st_size
        if file_size > MAX_FILE_SIZE:
            raise ValueError(
                f"文件过大（{file_size / 1024 / 1024:.1f}MB），"
                f"当前上限为 {MAX_FILE_SIZE // 1024 // 1024}MB"
            )

        self.asset_store = AssetStore()
        self._ctx = BlockParseContext(asset_store=self.asset_store)
        self._block_parser = BodyBlockParser(self._ctx)

        document = Document(str(path))
        blocks = self._block_parser.parse_story_blocks(document)

        hf_reader = HeaderFooterReader(self._block_parser)
        headers, footers, sections = hf_reader.read(path, document)

        fn_reader = FootnoteReader(self._block_parser)
        footnotes, endnotes = fn_reader.read(path, document)

        comments_summary = read_comments(path, self.asset_store)
        document_resources = read_document_resources(path)

        parse_metadata = ParseMetadata(
            parse_warnings=list(self._ctx.warnings),
            comments_summary=comments_summary,
            document_resources=document_resources,
        )

        ast = DocumentAST(
            id=self._new_node_id("doc"),
            blocks=blocks,
            headers=headers,
            footers=footers,
            footnotes=footnotes,
            endnotes=endnotes,
            sections=sections,
            parse_metadata=parse_metadata,
            metadata={"source_path": str(path)},
        )

        coverage = build_coverage_report(
            path, ast, self.asset_store, warnings=list(self._ctx.warnings)
        )
        ast.parse_metadata.coverage = coverage.model_dump(mode="json")
        return ast, self.asset_store

    def _new_node_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:8]}"


if __name__ == "__main__":
    import sys

    if len(sys.argv) != 2:
        print("Usage: python -m flow_ai_open.ingestion.docx_parser <path-to-docx>")
        raise SystemExit(2)

    ast = DocxParser().parse(sys.argv[1])
    print(ast.to_persisted_json(indent=2))
