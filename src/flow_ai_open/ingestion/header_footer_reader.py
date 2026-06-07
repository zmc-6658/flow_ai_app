"""Read headers, footers, and section metadata from DOCX."""
from __future__ import annotations

import zipfile
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.text.paragraph import Paragraph
from lxml import etree

from flow_ai.core.ast_models import (
    AnyBlockNode,
    HeaderFooterKind,
    HeaderFooterRegion,
    OpaqueType,
    SectionMetadata,
)
from flow_ai_open.ingestion.body_block_parser import BodyBlockParser
from flow_ai_open.ingestion.story_part_utils import part_for_path

HEADER_PREFIX = "word/header"
FOOTER_PREFIX = "word/footer"


class HeaderFooterReader:
    def __init__(self, block_parser: BodyBlockParser) -> None:
        self._block_parser = block_parser

    def read(
        self, docx_path: Path, document: Document
    ) -> tuple[list[HeaderFooterRegion], list[HeaderFooterRegion], list[SectionMetadata]]:
        headers: list[HeaderFooterRegion] = []
        footers: list[HeaderFooterRegion] = []
        sections: list[SectionMetadata] = []
        part_map = self._relationship_targets(docx_path)

        for section_index, section in enumerate(document.sections):
            sect_el = section._sectPr
            header_refs: dict[str, str] = {}
            footer_refs: dict[str, str] = {}
            for ref in sect_el.findall(qn("w:headerReference")):
                rid = ref.get(qn("r:id"))
                if rid:
                    header_refs[self._ref_kind(ref.get(qn("w:type"))).value] = rid
            for ref in sect_el.findall(qn("w:footerReference")):
                rid = ref.get(qn("r:id"))
                if rid:
                    footer_refs[self._ref_kind(ref.get(qn("w:type"))).value] = rid

            pg_sz = sect_el.find(qn("w:pgSz"))
            pg_mar = sect_el.find(qn("w:pgMar"))
            sections.append(
                SectionMetadata(
                    section_index=section_index,
                    page_width_twips=self._attr_int(pg_sz, qn("w:w")),
                    page_height_twips=self._attr_int(pg_sz, qn("w:h")),
                    margin_top_twips=self._attr_int(pg_mar, qn("w:top")),
                    margin_bottom_twips=self._attr_int(pg_mar, qn("w:bottom")),
                    margin_left_twips=self._attr_int(pg_mar, qn("w:left")),
                    margin_right_twips=self._attr_int(pg_mar, qn("w:right")),
                    header_refs=header_refs,
                    footer_refs=footer_refs,
                )
            )

            for kind_str, rid in header_refs.items():
                part_path = part_map.get(rid)
                if not part_path:
                    continue
                story_part = part_for_path(document, part_path)
                if story_part is None:
                    continue
                blocks = self._blocks_from_story(story_part._element, story_part)
                if blocks:
                    headers.append(
                        HeaderFooterRegion(
                            section_index=section_index,
                            kind=HeaderFooterKind(kind_str),
                            region="header",
                            part_path=part_path,
                            blocks=blocks,
                        )
                    )

            for kind_str, rid in footer_refs.items():
                part_path = part_map.get(rid)
                if not part_path:
                    continue
                story_part = part_for_path(document, part_path)
                if story_part is None:
                    continue
                blocks = self._blocks_from_story(story_part._element, story_part)
                if blocks:
                    footers.append(
                        HeaderFooterRegion(
                            section_index=section_index,
                            kind=HeaderFooterKind(kind_str),
                            region="footer",
                            part_path=part_path,
                            blocks=blocks,
                        )
                    )

        self._append_zip_parts(docx_path, document, headers, footers)
        return headers, footers, sections

    def _append_zip_parts(
        self,
        docx_path: Path,
        document: Document,
        headers: list[HeaderFooterRegion],
        footers: list[HeaderFooterRegion],
    ) -> None:
        known = {h.part_path for h in headers if h.part_path} | {
            f.part_path for f in footers if f.part_path
        }
        with zipfile.ZipFile(docx_path, "r") as zf:
            for name in sorted(zf.namelist()):
                if name in known:
                    continue
                story_part = part_for_path(document, name)
                if story_part is None:
                    continue
                if name.startswith(HEADER_PREFIX) and name.endswith(".xml"):
                    root = etree.fromstring(zf.read(name))
                    blocks = self._blocks_from_story(root, story_part)
                    if blocks:
                        headers.append(
                            HeaderFooterRegion(
                                section_index=0,
                                kind=HeaderFooterKind.DEFAULT,
                                region="header",
                                part_path=name,
                                blocks=blocks,
                            )
                        )
                elif name.startswith(FOOTER_PREFIX) and name.endswith(".xml"):
                    root = etree.fromstring(zf.read(name))
                    blocks = self._blocks_from_story(root, story_part)
                    if blocks:
                        footers.append(
                            HeaderFooterRegion(
                                section_index=0,
                                kind=HeaderFooterKind.DEFAULT,
                                region="footer",
                                part_path=name,
                                blocks=blocks,
                            )
                        )

    def _blocks_from_story(self, root: etree._Element, parent) -> list[AnyBlockNode]:
        blocks: list[AnyBlockNode] = []
        for source_index, child in enumerate(root.iterchildren()):
            try:
                if isinstance(child, CT_P) or child.tag == qn("w:p"):
                    paragraph = Paragraph(child, parent)
                    blocks.extend(
                        self._block_parser._build_nodes_from_paragraph(
                            paragraph, source_index
                        )
                    )
                elif isinstance(child, CT_Tbl) or child.tag == qn("w:tbl"):
                    asset_id = self._block_parser._store_table_asset(child)
                    blocks.append(
                        self._block_parser._make_opaque_node(
                            OpaqueType.TABLE,
                            source_index,
                            "table object preserved as opaque OOXML",
                            asset_id=asset_id,
                        )
                    )
                elif child.tag == qn("w:sdt"):
                    blocks.extend(
                        self._block_parser.parse_sdt_element(
                            child, parent, source_index
                        )
                    )
                else:
                    blocks.append(
                        self._block_parser._opaque_from_unknown_element(
                            child, source_index
                        )
                    )
            except Exception as exc:
                self._block_parser._ctx.warn(
                    f"header/footer block failed at {source_index}: {exc}"
                )
        return blocks

    @staticmethod
    def _relationship_targets(docx_path: Path) -> dict[str, str]:
        rels_path = "word/_rels/document.xml.rels"
        mapping: dict[str, str] = {}
        with zipfile.ZipFile(docx_path, "r") as zf:
            try:
                root = etree.fromstring(zf.read(rels_path))
            except KeyError:
                return mapping
            for rel in root:
                rid = rel.get("Id")
                target = rel.get("Target")
                if rid and target:
                    if not target.startswith("word/"):
                        target = f"word/{target.lstrip('/')}"
                    mapping[rid] = target.replace("\\", "/")
        return mapping

    @staticmethod
    def _ref_kind(raw: str | None) -> HeaderFooterKind:
        if raw == "first":
            return HeaderFooterKind.FIRST
        if raw == "even":
            return HeaderFooterKind.EVEN
        return HeaderFooterKind.DEFAULT

    @staticmethod
    def _attr_int(element: etree._Element | None, attr_qn: str) -> int | None:
        if element is None:
            return None
        raw = element.get(attr_qn)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None
