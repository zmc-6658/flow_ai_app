"""Shared body block parsing for docx ingestion (body, headers, footnotes)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from docx.document import Document as DocumentObject
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_UNDERLINE
from docx.oxml.ns import qn
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph
from docx.text.run import Run
from lxml import etree

from flow_ai.core.ast_models import (
    AnyBlockNode,
    BlockFeatures,
    InlineFeatures,
    InlineSpan,
    OpaqueNode,
    OpaqueType,
    ParagraphNode,
    TextAlignment,
)
from flow_ai.core.preservation_models import AssetBlob, AssetStore

if TYPE_CHECKING:
    from docx.parts.story import StoryPart

VML_IMAGE_DATA = "{urn:schemas-microsoft-com:vml}imagedata"
RELATIONSHIP_ID = (
    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
)

KNOWN_BLOCK_TAGS = frozenset(
    {
        qn("w:p"),
        qn("w:tbl"),
        qn("w:sdt"),
        qn("w:customXml"),
        qn("w:altChunk"),
        qn("w:sectPr"),
    }
)

TEXTBOX_TAGS = frozenset(
    {
        qn("w:txbxContent"),
        "{http://schemas.microsoft.com/office/word/2010/wordprocessingShape}txbx",
        "{urn:schemas-microsoft-com:vml}textbox",
    }
)
SDT_TAGS = frozenset({qn("w:sdt")})
FIELD_SKIP_TAGS = frozenset({qn("w:fldChar"), qn("w:instrText")})


@dataclass(frozen=True)
class RunEvent:
    text: str
    features: InlineFeatures


@dataclass(frozen=True)
class OpaqueEvent:
    opaque_type: OpaqueType
    text_preview: str
    asset_id: str | None = None


ParserEvent = RunEvent | OpaqueEvent


@dataclass
class BlockParseContext:
    asset_store: AssetStore
    warnings: list[str] = field(default_factory=list)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


class BodyBlockParser:
    def __init__(self, ctx: BlockParseContext) -> None:
        self._ctx = ctx

    @property
    def asset_store(self) -> AssetStore:
        return self._ctx.asset_store

    def parse_story_blocks(
        self,
        parent: DocumentObject | _Cell | StoryPart,
        *,
        start_index: int = 0,
    ) -> list[AnyBlockNode]:
        blocks: list[AnyBlockNode] = []
        for offset, item in enumerate(self._iter_block_items(parent)):
            source_index = start_index + offset
            try:
                if isinstance(item, Paragraph):
                    blocks.extend(
                        self._build_nodes_from_paragraph(item, source_index)
                    )
                elif isinstance(item, Table):
                    asset_id = self._store_table_asset(item._element)
                    blocks.append(
                        self._make_opaque_node(
                            OpaqueType.TABLE,
                            source_index,
                            "table object preserved as opaque OOXML",
                            asset_id=asset_id,
                        )
                    )
                elif isinstance(item, etree._Element):
                    blocks.append(self._opaque_from_unknown_element(item, source_index))
            except Exception as exc:
                self._ctx.warn(
                    f"block parse failed at index {source_index}: {exc}"
                )
        return blocks

    def _iter_block_items(
        self, parent: DocumentObject | _Cell | StoryPart
    ) -> list[Paragraph | Table | etree._Element]:
        if isinstance(parent, DocumentObject):
            body = parent.element.body
        elif isinstance(parent, _Cell):
            body = parent._tc
        else:
            body = parent._element

        items: list[Paragraph | Table | etree._Element] = []
        for child in body.iterchildren():
            if child.tag == qn("w:sectPr"):
                continue
            if isinstance(child, CT_P):
                items.append(Paragraph(child, parent))
            elif isinstance(child, CT_Tbl):
                items.append(Table(child, parent))
            elif child.tag == qn("w:sdt"):
                items.extend(self._iter_sdt_items(child, parent))
            else:
                items.append(child)
        return items

    def _iter_sdt_items(
        self, sdt_element: etree._Element, parent
    ) -> list[Paragraph | Table | etree._Element]:
        if self._contains_textbox(sdt_element):
            return [sdt_element]
        content = sdt_element.find(qn("w:sdtContent"))
        if content is None:
            return [sdt_element]
        items: list[Paragraph | Table | etree._Element] = []
        for child in content.iterchildren():
            if isinstance(child, CT_P):
                items.append(Paragraph(child, parent))
            elif isinstance(child, CT_Tbl):
                items.append(Table(child, parent))
            elif child.tag == qn("w:sdt"):
                items.extend(self._iter_sdt_items(child, parent))
            else:
                items.append(child)
        return items if items else [sdt_element]

    def parse_sdt_element(
        self, sdt_element: etree._Element, parent, source_index: int
    ) -> list[AnyBlockNode]:
        blocks: list[AnyBlockNode] = []
        for offset, item in enumerate(self._iter_sdt_items(sdt_element, parent)):
            idx = source_index + offset
            if isinstance(item, Paragraph):
                blocks.extend(self._build_nodes_from_paragraph(item, idx))
            elif isinstance(item, Table):
                asset_id = self._store_table_asset(item._element)
                blocks.append(
                    self._make_opaque_node(
                        OpaqueType.TABLE,
                        idx,
                        "table object preserved as opaque OOXML",
                        asset_id=asset_id,
                    )
                )
            elif isinstance(item, etree._Element):
                blocks.append(self._opaque_from_unknown_element(item, idx))
        return blocks

    def _opaque_from_unknown_element(
        self, element: etree._Element, source_index: int
    ) -> OpaqueNode:
        tag = element.tag
        if tag in SDT_TAGS or self._contains_textbox(element):
            opaque_type = OpaqueType.TEXTBOX if self._contains_textbox(element) else OpaqueType.SDT
            label = "textbox preserved as opaque OOXML" if opaque_type == OpaqueType.TEXTBOX else "SDT preserved as opaque OOXML"
        else:
            local = tag.split("}")[-1] if "}" in tag else tag
            opaque_type = OpaqueType.UNKNOWN
            label = f"unknown block w:{local} preserved as opaque OOXML"
        asset_id = self._store_generic_ooxml_asset(element, opaque_type)
        return self._make_opaque_node(opaque_type, source_index, label, asset_id=asset_id)

    def _contains_textbox(self, element: etree._Element) -> bool:
        for child in element.iter():
            if child.tag in TEXTBOX_TAGS:
                return True
        return False

    def _build_nodes_from_paragraph(
        self, paragraph: Paragraph, source_index: int
    ) -> list[ParagraphNode | OpaqueNode]:
        nodes: list[ParagraphNode | OpaqueNode] = []
        pending_spans: list[InlineSpan] = []
        events = self._walk_paragraph_events(paragraph)

        def flush_text_node(force_empty: bool = False) -> None:
            if not pending_spans and not force_empty:
                return
            nodes.append(
                ParagraphNode(
                    id=self._new_node_id("p"),
                    source_index=source_index,
                    spans=list(pending_spans),
                    features=self._build_block_features(paragraph, pending_spans),
                )
            )
            pending_spans.clear()

        for event in events:
            if isinstance(event, RunEvent):
                if event.text == "":
                    continue
                self._append_compressed_span(pending_spans, event.text, event.features)
            elif isinstance(event, OpaqueEvent):
                flush_text_node()
                nodes.append(
                    self._make_opaque_node(
                        event.opaque_type,
                        source_index,
                        event.text_preview,
                        asset_id=event.asset_id,
                    )
                )

        flush_text_node()
        if not nodes:
            flush_text_node(force_empty=True)

        nodes = self._reconcile_paragraph_text(paragraph, nodes)
        return nodes

    def _reconcile_paragraph_text(
        self, paragraph: Paragraph, nodes: list[ParagraphNode | OpaqueNode]
    ) -> list[ParagraphNode | OpaqueNode]:
        from flow_ai_open.ingestion.body_text import paragraph_visible_text

        xml_text = paragraph_visible_text(paragraph._element)
        if not xml_text:
            return nodes

        built = "".join(node.text for node in nodes if isinstance(node, ParagraphNode))
        if self._normalize_visible_text(built) == self._normalize_visible_text(xml_text):
            return nodes

        if not any(isinstance(node, OpaqueNode) for node in nodes):
            features = nodes[0].features if nodes and isinstance(nodes[0], ParagraphNode) else BlockFeatures(
                text_length=len(xml_text)
            )
            return [
                ParagraphNode(
                    id=self._new_node_id("p"),
                    source_index=nodes[0].source_index if nodes else 0,
                    spans=[InlineSpan(text=xml_text)],
                    features=features.model_copy(update={"text_length": len(xml_text)}),
                )
            ]

        return self._reconcile_mixed_nodes(nodes, xml_text)

    def _reconcile_mixed_nodes(
        self,
        nodes: list[ParagraphNode | OpaqueNode],
        xml_text: str,
    ) -> list[ParagraphNode | OpaqueNode]:
        text_indices = [i for i, node in enumerate(nodes) if isinstance(node, ParagraphNode)]
        if not text_indices:
            return nodes

        result = list(nodes)
        cursor = 0
        for seq, idx in enumerate(text_indices):
            node = nodes[idx]
            if seq == len(text_indices) - 1:
                chunk = xml_text[cursor:]
            else:
                next_text = nodes[text_indices[seq + 1]].text
                if next_text and next_text in xml_text[cursor:]:
                    split_at = xml_text.index(next_text, cursor)
                    chunk = xml_text[cursor:split_at]
                    cursor = split_at
                elif node.text and node.text in xml_text[cursor:]:
                    start = xml_text.index(node.text, cursor)
                    chunk = xml_text[start : start + len(node.text)]
                    cursor = start + len(chunk)
                else:
                    chunk = node.text
            if not chunk:
                continue
            result[idx] = ParagraphNode(
                id=node.id,
                source_index=node.source_index,
                spans=[InlineSpan(text=chunk)],
                features=node.features.model_copy(update={"text_length": len(chunk)}),
            )
        return result

    @staticmethod
    def _normalize_visible_text(text: str) -> str:
        import re

        return re.sub(r"\s+", " ", text).strip()

    def _build_nodes_from_xml_paragraph(
        self,
        paragraph_element: etree._Element,
        source_index: int,
        *,
        warning: str | None = None,
    ) -> list[ParagraphNode]:
        if warning:
            self._ctx.warn(warning)
        from flow_ai_open.ingestion.body_text import paragraph_visible_text

        text = paragraph_visible_text(paragraph_element)
        if not text:
            return []
        return [
            ParagraphNode(
                id=self._new_node_id("p"),
                source_index=source_index,
                spans=[InlineSpan(text=text)],
                features=BlockFeatures(text_length=len(text)),
            )
        ]

    def _walk_paragraph_events(self, paragraph: Paragraph) -> list[ParserEvent]:
        return list(self._walk_element_events(paragraph._element, paragraph))

    def _walk_element_events(
        self, element: etree._Element, paragraph: Paragraph
    ) -> list[ParserEvent]:
        tag = element.tag

        if tag == qn("w:del"):
            self._store_deletion_asset(element)
            return []
        if tag == qn("w:ins"):
            events: list[ParserEvent] = []
            for child in element.iterchildren():
                events.extend(self._walk_element_events(child, paragraph))
            return events
        if tag == qn("w:r"):
            return self._events_from_run_element(element, paragraph)
        if tag in (qn("w:tab"), qn("w:ptab")):
            return [RunEvent(text=" ", features=InlineFeatures())]
        if tag == qn("w:tbl"):
            return [
                OpaqueEvent(
                    opaque_type=OpaqueType.TABLE,
                    text_preview="table object preserved as opaque OOXML",
                    asset_id=self._store_table_asset(element),
                )
            ]
        if tag in SDT_TAGS:
            if self._contains_textbox(element):
                return [
                    OpaqueEvent(
                        opaque_type=OpaqueType.TEXTBOX,
                        text_preview="textbox preserved as opaque OOXML",
                        asset_id=self._store_generic_ooxml_asset(element, OpaqueType.TEXTBOX),
                    )
                ]
            sdt_content = element.find(qn("w:sdtContent"))
            if sdt_content is not None:
                events: list[ParserEvent] = []
                for child in sdt_content.iterchildren():
                    events.extend(self._walk_element_events(child, paragraph))
                if events:
                    return events
            return [
                OpaqueEvent(
                    opaque_type=OpaqueType.SDT,
                    text_preview="SDT preserved as opaque OOXML",
                    asset_id=self._store_generic_ooxml_asset(element, OpaqueType.SDT),
                )
            ]
        if tag in FIELD_SKIP_TAGS:
            return []
        if tag == qn("w:fldSimple"):
            events = []
            for child in element.iterchildren():
                events.extend(self._walk_element_events(child, paragraph))
            return events
        if tag in (qn("w:drawing"), qn("w:pict")):
            asset_id = self._store_image_asset(element, paragraph)
            return [
                OpaqueEvent(
                    opaque_type=OpaqueType.IMAGE,
                    text_preview="image object preserved as opaque OOXML",
                    asset_id=asset_id,
                )
            ]
        if tag in (qn("m:oMath"), qn("m:oMathPara")):
            return [
                OpaqueEvent(
                    opaque_type=OpaqueType.EQUATION,
                    text_preview="equation object preserved as opaque OOXML",
                    asset_id=self._store_equation_asset(element),
                )
            ]

        events = []
        for child in element.iterchildren():
            events.extend(self._walk_element_events(child, paragraph))
        return events

    def _events_from_run_element(
        self, run_element: etree._Element, paragraph: Paragraph
    ) -> list[ParserEvent]:
        try:
            run = Run(run_element, paragraph)
            features = self._features_for_run(run)
        except AttributeError:
            features = InlineFeatures()

        events: list[ParserEvent] = []

        for child in run_element.iterchildren():
            tag = child.tag
            if tag == qn("w:t"):
                text = child.text or ""
                if text:
                    events.append(RunEvent(text=text, features=features))
            elif tag in (qn("w:tab"), qn("w:ptab")):
                events.append(RunEvent(text=" ", features=features))
            elif tag in (qn("w:noBreakHyphen"), qn("w:softHyphen")):
                events.append(RunEvent(text="-", features=features))
            elif tag == qn("w:sym"):
                char = child.get(qn("w:char"))
                if char:
                    try:
                        events.append(
                            RunEvent(text=chr(int(char, 16)), features=features)
                        )
                    except ValueError:
                        pass
            elif tag in (qn("w:br"), qn("w:cr")):
                events.append(RunEvent(text="\n", features=features))
            elif tag in (qn("w:drawing"), qn("w:pict")):
                asset_id = self._store_image_asset(child, paragraph)
                events.append(
                    OpaqueEvent(
                        opaque_type=OpaqueType.IMAGE,
                        text_preview="image object preserved as opaque OOXML",
                        asset_id=asset_id,
                    )
                )
            elif tag in (qn("m:oMath"), qn("m:oMathPara")):
                events.append(
                    OpaqueEvent(
                        opaque_type=OpaqueType.EQUATION,
                        text_preview="equation object preserved as opaque OOXML",
                        asset_id=self._store_equation_asset(child),
                    )
                )
            elif tag == qn("w:del"):
                self._store_deletion_asset(child)
                continue
            elif tag in SDT_TAGS:
                if self._contains_textbox(child):
                    events.append(
                        OpaqueEvent(
                            opaque_type=OpaqueType.TEXTBOX,
                            text_preview="textbox preserved as opaque OOXML",
                            asset_id=self._store_generic_ooxml_asset(
                                child, OpaqueType.TEXTBOX
                            ),
                        )
                    )
                else:
                    sdt_content = child.find(qn("w:sdtContent"))
                    if sdt_content is not None:
                        for sub in sdt_content.iterchildren():
                            events.extend(self._walk_element_events(sub, paragraph))
                    else:
                        events.append(
                            OpaqueEvent(
                                opaque_type=OpaqueType.SDT,
                                text_preview="SDT preserved as opaque OOXML",
                                asset_id=self._store_generic_ooxml_asset(
                                    child, OpaqueType.SDT
                                ),
                            )
                        )
            elif tag in FIELD_SKIP_TAGS:
                continue
            elif tag == qn("w:fldSimple"):
                events.extend(self._walk_element_events(child, paragraph))
            else:
                events.extend(self._walk_element_events(child, paragraph))

        return events

    def _append_compressed_span(
        self, spans: list[InlineSpan], text: str, features: InlineFeatures
    ) -> None:
        if spans and spans[-1].features == features:
            last = spans[-1]
            spans[-1] = InlineSpan(text=last.text + text, features=features)
            return
        spans.append(InlineSpan(text=text, features=features))

    def _features_for_run(self, run: Run) -> InlineFeatures:
        try:
            font_size = run.font.size.pt if run.font.size is not None else None
            east_asia = None
            r_pr = run._element.find(qn("w:rPr"))
            if r_pr is not None:
                r_fonts = r_pr.find(qn("w:rFonts"))
                if r_fonts is not None:
                    east_asia = r_fonts.get(qn("w:eastAsia"))
            return InlineFeatures(
                bold=run.bold,
                italic=run.italic,
                underline=self._normalize_underline(run.underline),
                font_family=run.font.name,
                font_size_pt=font_size,
            )
        except AttributeError:
            return InlineFeatures()

    def _normalize_underline(self, value) -> bool | None:
        if value is None:
            return None
        if value is True:
            return True
        if value is False:
            return False
        if value == WD_UNDERLINE.NONE:
            return False
        return True

    def _build_block_features(
        self, paragraph: Paragraph, spans: list[InlineSpan]
    ) -> BlockFeatures:
        total_chars = sum(len(span.text) for span in spans)
        bold_chars = self._count_chars_with_flag(spans, "bold")
        italic_chars = self._count_chars_with_flag(spans, "italic")
        underline_chars = self._count_chars_with_flag(spans, "underline")
        font_sizes = [
            span.features.font_size_pt
            for span in spans
            if span.features.font_size_pt is not None
        ]
        p_pr = paragraph._element.find(qn("w:pPr"))
        spacing_before = spacing_after = indent_left = indent_first = None
        num_id = ilvl = style_id = east_asia = None
        if p_pr is not None:
            spacing = p_pr.find(qn("w:spacing"))
            if spacing is not None:
                spacing_before = self._int_attr(spacing, qn("w:before"))
                spacing_after = self._int_attr(spacing, qn("w:after"))
            ind = p_pr.find(qn("w:ind"))
            if ind is not None:
                indent_left = self._int_attr(ind, qn("w:left"))
                indent_first = self._int_attr(ind, qn("w:firstLine"))
            num_pr = p_pr.find(qn("w:numPr"))
            if num_pr is not None:
                num_id_el = num_pr.find(qn("w:numId"))
                ilvl_el = num_pr.find(qn("w:ilvl"))
                if num_id_el is not None:
                    num_id = self._int_attr(num_id_el, qn("w:val"))
                if ilvl_el is not None:
                    ilvl = self._int_attr(ilvl_el, qn("w:val"))
            p_style = p_pr.find(qn("w:pStyle"))
            if p_style is not None:
                style_id = p_style.get(qn("w:val"))

        east_asia_font = None
        try:
            for run in paragraph.runs:
                r_pr = run._element.find(qn("w:rPr"))
                if r_pr is not None:
                    r_fonts = r_pr.find(qn("w:rFonts"))
                    if r_fonts is not None:
                        east_asia_font = r_fonts.get(qn("w:eastAsia")) or east_asia_font
        except AttributeError:
            pass

        try:
            alignment = self._map_alignment(paragraph.alignment)
        except AttributeError:
            alignment = TextAlignment.UNKNOWN

        try:
            style_name = paragraph.style.name if paragraph.style is not None else None
        except AttributeError:
            style_name = None

        return BlockFeatures(
            bold_ratio=self._ratio(bold_chars, total_chars),
            italic_ratio=self._ratio(italic_chars, total_chars),
            underline_ratio=self._ratio(underline_chars, total_chars),
            dominant_font_size=self._dominant_value(font_sizes),
            font_size_variance=self._variance(font_sizes),
            dominant_font_family=self._dominant_value(
                [
                    span.features.font_family
                    for span in spans
                    if span.features.font_family is not None
                ]
            ),
            alignment=alignment,
            text_length=total_chars,
            style_name=style_name,
            style_id=style_id,
            spacing_before_twips=spacing_before,
            spacing_after_twips=spacing_after,
            indent_left_twips=indent_left,
            indent_first_line_twips=indent_first,
            num_id=num_id,
            ilvl=ilvl,
            east_asia_font=east_asia_font,
        )

    @staticmethod
    def _int_attr(element: etree._Element, attr: str) -> int | None:
        raw = element.get(attr)
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    def _count_chars_with_flag(self, spans: list[InlineSpan], flag_name: str) -> int:
        count = 0
        for span in spans:
            if getattr(span.features, flag_name) is True:
                count += len(span.text)
        return count

    def _make_opaque_node(
        self,
        opaque_type: OpaqueType,
        source_index: int,
        text_preview: str,
        *,
        asset_id: str | None = None,
    ) -> OpaqueNode:
        blob_id = asset_id or self._new_node_id(f"blob_{opaque_type.value}")
        if not self.asset_store.has(blob_id):
            self.asset_store.add(
                AssetBlob(
                    id=blob_id,
                    opaque_type=opaque_type,
                    xml=f"<placeholder opaque_type='{opaque_type.value}'/>",
                )
            )
        return OpaqueNode(
            id=self._new_node_id(opaque_type.value),
            source_index=source_index,
            opaque_type=opaque_type,
            raw_ooxml_ref=blob_id,
            text_preview=f"{text_preview}; blob={blob_id}",
        )

    def _store_image_asset(
        self, image_element: etree._Element, paragraph: Paragraph
    ) -> str:
        relationship_id = self._image_relationship_id(image_element)
        asset_id = self._new_node_id("asset_image")
        payload = None
        content_type = None
        filename = None
        if relationship_id is not None:
            image_part = paragraph.part.related_parts.get(relationship_id)
            if image_part is not None:
                payload = image_part.blob
                partname = str(getattr(image_part, "partname", ""))
                content_type = getattr(image_part, "content_type", None)
                filename = Path(partname).name if partname else None
            else:
                self._ctx.warn(
                    f"image relationship {relationship_id} not resolved; storing drawing XML"
                )
        else:
            self._ctx.warn("image without relationship id; storing drawing XML")

        self.asset_store.add(
            AssetBlob(
                id=asset_id,
                opaque_type=OpaqueType.IMAGE,
                payload=payload,
                xml=etree.tostring(paragraph._element, encoding="unicode"),
                content_type=content_type,
                filename=filename,
                source_relationship_id=relationship_id,
            )
        )
        return asset_id

    def _image_relationship_id(self, image_element: etree._Element) -> str | None:
        for blip in image_element.iter(qn("a:blip")):
            relationship_id = blip.get(qn("r:embed")) or blip.get(qn("r:link"))
            if relationship_id:
                return relationship_id
        for image_data in image_element.iter(VML_IMAGE_DATA):
            relationship_id = image_data.get(RELATIONSHIP_ID)
            if relationship_id:
                return relationship_id
        return None

    def _store_table_asset(self, table_element: etree._Element) -> str:
        asset_id = self._new_node_id("asset_table")
        self.asset_store.add(
            AssetBlob(
                id=asset_id,
                opaque_type=OpaqueType.TABLE,
                xml=etree.tostring(table_element, encoding="unicode"),
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.table+xml",
            )
        )
        return asset_id

    def _store_equation_asset(self, element: etree._Element) -> str:
        asset_id = self._new_node_id("asset_equation")
        self.asset_store.add(
            AssetBlob(
                id=asset_id,
                opaque_type=OpaqueType.EQUATION,
                xml=etree.tostring(element, encoding="unicode"),
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.math+xml",
            )
        )
        return asset_id

    def _store_generic_ooxml_asset(
        self, element: etree._Element, opaque_type: OpaqueType
    ) -> str:
        asset_id = self._new_node_id(f"asset_{opaque_type.value}")
        self.asset_store.add(
            AssetBlob(
                id=asset_id,
                opaque_type=opaque_type,
                xml=etree.tostring(element, encoding="unicode"),
            )
        )
        return asset_id

    def _store_deletion_asset(self, element: etree._Element) -> None:
        asset_id = self._new_node_id("asset_del")
        self.asset_store.add(
            AssetBlob(
                id=asset_id,
                opaque_type=OpaqueType.GENERIC,
                xml=etree.tostring(element, encoding="unicode"),
            )
        )

    def _map_alignment(self, alignment: WD_ALIGN_PARAGRAPH | None) -> TextAlignment:
        if alignment is None:
            return TextAlignment.UNKNOWN
        mapping = {
            WD_ALIGN_PARAGRAPH.LEFT: TextAlignment.LEFT,
            WD_ALIGN_PARAGRAPH.CENTER: TextAlignment.CENTER,
            WD_ALIGN_PARAGRAPH.RIGHT: TextAlignment.RIGHT,
            WD_ALIGN_PARAGRAPH.JUSTIFY: TextAlignment.JUSTIFY,
            WD_ALIGN_PARAGRAPH.DISTRIBUTE: TextAlignment.DISTRIBUTE,
        }
        return mapping.get(alignment, TextAlignment.UNKNOWN)

    def _new_node_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid4().hex[:8]}"

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        if denominator == 0:
            return 0.0
        return round(numerator / denominator, 6)

    @staticmethod
    def _dominant_value(values: list):
        if not values:
            return None
        counts: dict = {}
        for value in values:
            counts[value] = counts.get(value, 0) + 1
        return max(counts, key=counts.get)

    @staticmethod
    def _variance(values: list[float]) -> float | None:
        if not values:
            return None
        mean = sum(values) / len(values)
        return round(sum((value - mean) ** 2 for value in values) / len(values), 6)
