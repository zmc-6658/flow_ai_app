from __future__ import annotations

from dataclasses import dataclass, field

from flow_ai.core.ast_models import (
    AnyBlockNode,
    DocumentAST,
    InlineSpan,
)
from flow_ai.core.ast_models import BlockFeatures


@dataclass(frozen=True)
class ParagraphRecord:

    node_id: str
    region: str
    block_index: int
    source_index: int | None
    text: str
    features: BlockFeatures
    spans: tuple[InlineSpan, ...] = field(default_factory=tuple)
    heading_level: int | None = None


@dataclass
class TemplateReadResult:

    ast: DocumentAST
    paragraphs: list[ParagraphRecord]
    opaque_blocks: list[AnyBlockNode]


def read_paragraphs_from_ast(ast: DocumentAST) -> TemplateReadResult:
    paragraphs: list[ParagraphRecord] = []

    for block_index, block in enumerate(ast.blocks):
        paragraphs.extend(_records_from_block(block, "body", block_index))

    for hf_region in (*ast.headers, *ast.footers):
        region_name = hf_region.region
        for block_index, block in enumerate(hf_region.blocks):
            paragraphs.extend(
                _records_from_block(block, region_name, block_index)
            )

    opaque_blocks = [b for b in ast.blocks if b.kind == "opaque"]
    return TemplateReadResult(ast=ast, paragraphs=paragraphs, opaque_blocks=opaque_blocks)


def _records_from_block(
    block: AnyBlockNode,
    region: str,
    block_index: int,
) -> list[ParagraphRecord]:
    if block.kind not in ("paragraph", "heading"):
        return []
    text = block.text.strip()
    if not text:
        return []
    heading_level = block.level if block.kind == "heading" else None
    return [
        ParagraphRecord(
            node_id=block.id,
            region=region,
            block_index=block_index,
            source_index=block.source_index,
            text=text,
            features=block.features,
            spans=tuple(block.spans),
            heading_level=heading_level,
        )
    ]
