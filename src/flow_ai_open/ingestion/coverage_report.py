"""Parse coverage report: compare OOXML inventory with DocumentAST."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from pydantic import Field

from flow_ai.core.ast_models import (
    DocumentAST,
    HeadingNode,
    OpaqueNode,
    ParagraphNode,
    StrictASTModel,
)
from flow_ai_open.ingestion.ooxml_inventory import inventory_from_docx


class ParseCoverageReport(StrictASTModel):
    source: str = ""
    unmapped_elements: list[str] = Field(default_factory=list)
    text_checksum_by_region: dict[str, str] = Field(default_factory=dict)
    expected_checksum_by_region: dict[str, str] = Field(default_factory=dict)
    opaque_inventory: list[dict[str, str]] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        if self.unmapped_elements:
            return False
        for region, expected in self.expected_checksum_by_region.items():
            if self.text_checksum_by_region.get(region) != expected:
                return False
        return True


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _checksum(text: str) -> str:
    return hashlib.sha256(_normalize_text(text).encode("utf-8")).hexdigest()


def _block_text(block) -> str:
    if isinstance(block, (ParagraphNode, HeadingNode)):
        return block.text
    return ""


def _region_text(blocks) -> str:
    return "".join(_block_text(b) for b in blocks)


def _collect_opaque(ast: DocumentAST, asset_store) -> list[dict[str, str]]:
    inventory: list[dict[str, str]] = []

    def scan(blocks, region: str) -> None:
        for block in blocks:
            if isinstance(block, OpaqueNode):
                asset = asset_store.get(block.raw_ooxml_ref)
                inventory.append(
                    {
                        "node_id": block.id,
                        "region": region,
                        "opaque_type": block.opaque_type.value,
                        "has_payload": str(asset is not None and asset.payload is not None),
                        "has_xml": str(asset is not None and asset.xml is not None),
                    }
                )

    scan(ast.blocks, "body")
    for hf in ast.headers:
        scan(hf.blocks, f"header:{hf.section_index}:{hf.kind}")
    for hf in ast.footers:
        scan(hf.blocks, f"footer:{hf.section_index}:{hf.kind}")
    for note in ast.footnotes:
        scan(note.blocks, f"footnote:{note.note_id}")
    for note in ast.endnotes:
        scan(note.blocks, f"endnote:{note.note_id}")
    return inventory


def build_coverage_report(
    docx_path: str | Path,
    ast: DocumentAST,
    asset_store,
    *,
    warnings: list[str] | None = None,
) -> ParseCoverageReport:
    path = Path(docx_path)
    baseline = inventory_from_docx(path)

    body_text = _region_text(ast.blocks)
    header_text = _region_text(
        [b for region in ast.headers for b in region.blocks]
    )
    footer_text = _region_text(
        [b for region in ast.footers for b in region.blocks]
    )
    footnote_text = _region_text(
        [b for note in ast.footnotes for b in note.blocks]
    )
    endnote_text = _region_text(
        [b for note in ast.endnotes for b in note.blocks]
    )

    text_checksum_by_region = {
        "body": _checksum(body_text),
        "header": _checksum(header_text),
        "footer": _checksum(footer_text),
        "footnote": _checksum(footnote_text),
        "endnote": _checksum(endnote_text),
    }
    expected_checksum_by_region = {
        "body": baseline["body"]["text_checksum"],
        "header": baseline["headers"]["text_checksum"],
        "footer": baseline["footers"]["text_checksum"],
        "footnote": baseline["footnotes"]["text_checksum"],
        "endnote": baseline["endnotes"]["text_checksum"],
    }

    unmapped: list[str] = []
    for region, expected in expected_checksum_by_region.items():
        if expected and text_checksum_by_region.get(region) != expected:
            unmapped.append(f"text_checksum_mismatch:{region}")

    parse_warnings = list(warnings or [])
    if ast.parse_metadata is not None:
        parse_warnings.extend(ast.parse_metadata.parse_warnings)

    return ParseCoverageReport(
        source=path.name,
        unmapped_elements=unmapped,
        text_checksum_by_region=text_checksum_by_region,
        expected_checksum_by_region=expected_checksum_by_region,
        opaque_inventory=_collect_opaque(ast, asset_store),
        warnings=parse_warnings,
    )
