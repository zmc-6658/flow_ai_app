"""Read footnotes and endnotes from DOCX."""
from __future__ import annotations

import zipfile
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.text.paragraph import Paragraph
from lxml import etree

from flow_ai.core.ast_models import AnyBlockNode, FootnoteBlock, OpaqueType
from flow_ai_open.ingestion.body_block_parser import BodyBlockParser
from flow_ai_open.ingestion.story_part_utils import endnotes_part, footnotes_part

SKIP_NOTE_IDS = frozenset({"-1", "0"})


class FootnoteReader:
    def __init__(self, block_parser: BodyBlockParser) -> None:
        self._block_parser = block_parser

    def read(
        self, docx_path: Path, document: Document
    ) -> tuple[list[FootnoteBlock], list[FootnoteBlock]]:
        footnotes = self._read_part(
            docx_path, "word/footnotes.xml", "footnote", footnotes_part(document)
        )
        endnotes = self._read_part(
            docx_path, "word/endnotes.xml", "endnote", endnotes_part(document)
        )
        return footnotes, endnotes

    def _read_part(
        self,
        docx_path: Path,
        part_name: str,
        tag_local: str,
        story_part,
    ) -> list[FootnoteBlock]:
        results: list[FootnoteBlock] = []
        with zipfile.ZipFile(docx_path, "r") as zf:
            try:
                root = etree.fromstring(zf.read(part_name))
            except KeyError:
                return results

            for note_el in root.iter(qn(f"w:{tag_local}")):
                note_id = note_el.get(qn("w:id"))
                if note_id is None or note_id in SKIP_NOTE_IDS:
                    continue
                blocks = self._blocks_from_note(note_el, story_part)
                results.append(
                    FootnoteBlock(
                        note_id=str(note_id),
                        note_kind="footnote" if tag_local == "footnote" else "endnote",
                        blocks=blocks,
                    )
                )
        return results

    def _blocks_from_note(
        self, note_el: etree._Element, story_part
    ) -> list[AnyBlockNode]:
        if story_part is None:
            return []

        blocks: list[AnyBlockNode] = []
        for source_index, child in enumerate(note_el.iterchildren()):
            try:
                if isinstance(child, CT_P) or child.tag == qn("w:p"):
                    try:
                        paragraph = Paragraph(child, story_part)
                        blocks.extend(
                            self._block_parser._build_nodes_from_paragraph(
                                paragraph, source_index
                            )
                        )
                    except Exception as exc:
                        blocks.extend(
                            self._block_parser._build_nodes_from_xml_paragraph(
                                child,
                                source_index,
                                warning=f"footnote block failed at {source_index}: {exc}",
                            )
                        )
                elif isinstance(child, CT_Tbl) or child.tag == qn("w:tbl"):
                    asset_id = self._block_parser._store_table_asset(child)
                    blocks.append(
                        self._block_parser._make_opaque_node(
                            OpaqueType.TABLE,
                            source_index,
                            "table in note preserved as opaque OOXML",
                            asset_id=asset_id,
                        )
                    )
                elif child.tag == qn("w:sdt"):
                    blocks.extend(
                        self._block_parser.parse_sdt_element(
                            child, story_part, source_index
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
                    f"footnote block failed at {source_index}: {exc}"
                )
        return blocks
