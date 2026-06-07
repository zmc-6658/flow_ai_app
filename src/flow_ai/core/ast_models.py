from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


NodeID: TypeAlias = Annotated[
    str,
    Field(
        min_length=1,
        description="Globally unique, stable node identifier within a DocumentAST.",
    ),
]


class StrictASTModel(BaseModel):

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
        str_strip_whitespace=False,
    )


class TextAlignment(StrEnum):

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"
    DISTRIBUTE = "distribute"
    UNKNOWN = "unknown"


class OpaqueType(StrEnum):

    TABLE = "table"
    EQUATION = "equation"
    IMAGE = "image"
    UNKNOWN = "unknown"
    TEXTBOX = "textbox"
    SDT = "sdt"
    FIELD = "field"
    GENERIC = "generic"


class SemanticRole(StrEnum):

    STANDARD = "standard"
    TITLE_CN = "title_cn"
    TITLE_EN = "title_en"
    AUTHOR_INFO = "author_info"
    TOC = "toc"
    TOC_ENTRY = "toc_entry"
    ABSTRACT = "abstract"
    ABSTRACT_BODY = "abstract_body"
    ABSTRACT_BODY_EN = "abstract_body_en"
    KEYWORDS = "keywords"
    KEYWORDS_EN = "keywords_en"
    REFERENCES = "references"
    REFERENCES_ITEM = "references_item"
    ACKNOWLEDGMENT = "acknowledgment"
    ACKNOWLEDGMENT_BODY = "acknowledgment_body"
    APPENDIX = "appendix"
    APPENDIX_BODY = "appendix_body"
    FIGURE_CAPTION = "figure_caption"
    TABLE_CAPTION = "table_caption"
    BODY = "body"


class NumberingScheme(StrEnum):

    NONE = "none"
    GLOBAL = "global"
    CHAPTER_LOCAL = "chapter_local"
    CUSTOM = "custom"


class NumberingState(StrEnum):

    UNRESOLVED = "unresolved"
    COMPUTED = "computed"
    FROZEN = "frozen"


class ReferenceTargetType(StrEnum):

    HEADING = "heading"
    FIGURE = "figure"
    TABLE = "table"
    EQUATION = "equation"
    REFERENCE = "reference"
    UNKNOWN = "unknown"


class InlineFeatures(StrictASTModel):

    bold: bool | None = Field(
        default=None,
        description="Whether this span appears bold in the source, if known.",
    )
    italic: bool | None = Field(
        default=None,
        description="Whether this span appears italic in the source, if known.",
    )
    underline: bool | None = Field(
        default=None,
        description="Whether this span appears underlined in the source, if known.",
    )
    font_family: str | None = Field(
        default=None,
        description="Source font family for this span, if available.",
    )
    font_size_pt: float | None = Field(
        default=None,
        gt=0,
        le=72,
        description="Source font size in points for this span, if available.",
    )


class InlineSpan(StrictASTModel):

    text: str = Field(description="Literal text content represented by this span.")
    features: InlineFeatures = Field(
        default_factory=InlineFeatures,
        description="Source formatting evidence for this normalized span.",
    )

    @field_validator("text")
    @classmethod
    def text_must_not_be_empty(cls, value: str) -> str:

        if value == "":
            raise ValueError("InlineSpan.text 不能为空")
        return value


class BlockFeatures(StrictASTModel):

    bold_ratio: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Ratio of source characters that appear bold.",
    )
    italic_ratio: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Ratio of source characters that appear italic.",
    )
    underline_ratio: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Ratio of source characters that appear underlined.",
    )
    dominant_font_size: float | None = Field(
        default=None,
        gt=0,
        description="Most common source font size in points, if detectable.",
    )
    font_size_variance: float | None = Field(
        default=None,
        ge=0.0,
        description="Variance of detected source font sizes within the block.",
    )
    dominant_font_family: str | None = Field(
        default=None,
        description="Most common source font family, if detectable.",
    )
    alignment: TextAlignment = Field(
        default=TextAlignment.UNKNOWN,
        description="Paragraph alignment evidence from the source document.",
    )
    text_length: int = Field(
        default=0,
        ge=0,
        description="Character length of the normalized block text.",
    )
    style_name: str | None = Field(
        default=None,
        description="Original Word paragraph style name used only as evidence.",
    )
    style_id: str | None = Field(
        default=None,
        description="Word internal style identifier (w:style w:val), if available.",
    )
    spacing_before_twips: int | None = Field(
        default=None,
        ge=0,
        description="Paragraph spacing before in twips, if available.",
    )
    spacing_after_twips: int | None = Field(
        default=None,
        ge=0,
        description="Paragraph spacing after in twips, if available.",
    )
    indent_left_twips: int | None = Field(
        default=None,
        description="Left indent in twips, if available.",
    )
    indent_first_line_twips: int | None = Field(
        default=None,
        description="First-line indent in twips, if available.",
    )
    num_id: int | None = Field(
        default=None,
        ge=0,
        description="Numbering definition id (numId), if present.",
    )
    ilvl: int | None = Field(
        default=None,
        ge=0,
        description="Numbering level (ilvl), if present.",
    )
    east_asia_font: str | None = Field(
        default=None,
        description="East Asia font from w:rFonts w:eastAsia, if available.",
    )


class Numbering(StrictASTModel):

    scheme: NumberingScheme = Field(
        default=NumberingScheme.NONE,
        description="Scope used by renderers to compute the displayed number.",
    )
    state: NumberingState = Field(
        default=NumberingState.UNRESOLVED,
        description="Whether the number is pending, computed, or intentionally frozen.",
    )
    raw_text: str | None = Field(
        default=None,
        description="Numbering text observed in the source document, if any.",
    )
    computed_value: str | None = Field(
        default=None,
        description="Renderer-computed value such as '1-1'; not source text.",
    )
    scope_node_id: NodeID | None = Field(
        default=None,
        description="Node that defines this numbering scope, usually a chapter heading.",
    )


class CrossReference(StrictASTModel):

    id: NodeID = Field(description="Globally unique ID for this reference edge.")
    source_node_id: NodeID = Field(description="Node containing the reference text.")
    target_node_id: NodeID | None = Field(
        default=None,
        description="Resolved target node ID, or None while unresolved.",
    )
    target_type: ReferenceTargetType = Field(
        default=ReferenceTargetType.UNKNOWN,
        description="Expected target category used during resolution.",
    )
    raw_text: str = Field(
        description="Original reference text, such as '图 1-1' or '(2-3)'.",
    )
    confidence: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Classifier confidence that this is a real cross-reference.",
    )

    @model_validator(mode="before")
    @classmethod
    def strip_computed_fields(cls, data: Any) -> Any:

        if isinstance(data, dict):
            data = dict(data)
            data.pop("is_resolved", None)
        return data

    @computed_field
    @property
    def is_resolved(self) -> bool:

        return self.target_node_id is not None


class ReferenceGraph(StrictASTModel):

    references: list[CrossReference] = Field(
        default_factory=list,
        description="All candidate and confirmed cross-reference edges.",
    )

    @model_validator(mode="before")
    @classmethod
    def strip_computed_fields(cls, data: Any) -> Any:

        if isinstance(data, dict):
            data = dict(data)
            data.pop("outgoing_by_node_id", None)
            data.pop("incoming_by_node_id", None)
        return data

    @computed_field
    @property
    def outgoing_by_node_id(self) -> dict[str, list[str]]:

        graph: dict[str, list[str]] = {}
        for reference in self.references:
            graph.setdefault(reference.source_node_id, []).append(reference.id)
        return graph

    @computed_field
    @property
    def incoming_by_node_id(self) -> dict[str, list[str]]:

        graph: dict[str, list[str]] = {}
        for reference in self.references:
            if reference.target_node_id is not None:
                graph.setdefault(reference.target_node_id, []).append(reference.id)
        return graph


class BlockNode(StrictASTModel):

    id: NodeID
    kind: str = Field(description="Discriminator used for polymorphic block parsing.")
    source_index: int | None = Field(
        default=None,
        ge=0,
        description="Physical order index from the source document, if available.",
    )
    numbering: Numbering | None = Field(
        default=None,
        description="Dynamic numbering metadata attached to this block, if any.",
    )
    suppress_render: bool = Field(
        default=False,
        description="Renderer hint: preserve this node in AST but skip physical output.",
    )


class ParagraphNode(BlockNode):

    kind: Literal["paragraph"] = "paragraph"
    spans: list[InlineSpan] = Field(
        default_factory=list,
        description="Normalized inline text spans preserving source evidence.",
    )
    features: BlockFeatures = Field(
        default_factory=BlockFeatures,
        description="Aggregated classifier evidence for this paragraph.",
    )

    @computed_field
    @property
    def text(self) -> str:

        return "".join(span.text for span in self.spans)


class HeadingNode(ParagraphNode):

    kind: Literal["heading"] = "heading"
    level: int = Field(
        ge=1,
        le=9,
        description="Logical heading level. H1 is 1, H2 is 2, and so on.",
    )
    semantic_role: SemanticRole = Field(
        default=SemanticRole.STANDARD,
        description="Special section role used by renderers and TOC generation.",
    )


class OpaqueNode(BlockNode):

    kind: Literal["opaque"] = "opaque"
    opaque_type: OpaqueType = Field(
        description="Kind of complex object represented by this node.",
    )
    raw_ooxml_ref: NodeID = Field(
        description="ID of the preserved raw OOXML blob in external blob storage.",
    )
    text_preview: str = Field(
        default="",
        description="Best-effort human-readable preview for review and debugging.",
    )


class GeneratedAnchorNode(BlockNode):

    kind: Literal["generated_anchor"] = "generated_anchor"
    anchor_type: str = Field(
        default="toc",
        description="Virtual anchor type. The MVP uses 'toc'.",
    )
    source_index: None = Field(
        default=None,
        description="Generated nodes do not correspond to a physical source block.",
    )


AnyBlockNode: TypeAlias = Annotated[
    HeadingNode | ParagraphNode | OpaqueNode | GeneratedAnchorNode,
    Field(discriminator="kind"),
]


class HeaderFooterKind(StrEnum):

    DEFAULT = "default"
    FIRST = "first"
    EVEN = "even"


class HeaderFooterRegion(StrictASTModel):

    section_index: int = Field(ge=0, description="Zero-based section index.")
    kind: HeaderFooterKind = Field(description="Header/footer variant for this section.")
    region: Literal["header", "footer"] = Field(description="Whether this bundle is header or footer.")
    part_path: str | None = Field(
        default=None,
        description="OOXML part path such as word/header1.xml.",
    )
    blocks: list[AnyBlockNode] = Field(
        default_factory=list,
        description="Blocks parsed from this header/footer part.",
    )


class SectionMetadata(StrictASTModel):

    section_index: int = Field(ge=0)
    page_width_twips: int | None = None
    page_height_twips: int | None = None
    margin_top_twips: int | None = None
    margin_bottom_twips: int | None = None
    margin_left_twips: int | None = None
    margin_right_twips: int | None = None
    header_refs: dict[str, str] = Field(
        default_factory=dict,
        description="Header variant (default/first/even) to relationship id.",
    )
    footer_refs: dict[str, str] = Field(
        default_factory=dict,
        description="Footer variant (default/first/even) to relationship id.",
    )


class FootnoteBlock(StrictASTModel):

    note_id: str = Field(description="Footnote/endnote id from OOXML.")
    note_kind: Literal["footnote", "endnote"] = Field(
        description="Whether this block is a footnote or endnote.",
    )
    blocks: list[AnyBlockNode] = Field(
        default_factory=list,
        description="Content blocks inside this note.",
    )


class CommentSummary(StrictASTModel):

    comment_id: str
    author: str | None = None
    text: str = ""
    date: str | None = None


class ParseMetadata(StrictASTModel):

    parse_warnings: list[str] = Field(default_factory=list)
    comments_summary: list[CommentSummary] = Field(default_factory=list)
    document_resources: dict[str, Any] = Field(default_factory=dict)
    coverage: dict[str, Any] | None = None


class DocumentAST(StrictASTModel):

    id: NodeID
    blocks: list[AnyBlockNode] = Field(
        default_factory=list,
        description="Document blocks in physical reading order (body only).",
    )
    headers: list[HeaderFooterRegion] = Field(
        default_factory=list,
        description="Header regions across all sections (Scheme A).",
    )
    footers: list[HeaderFooterRegion] = Field(
        default_factory=list,
        description="Footer regions across all sections (Scheme A).",
    )
    footnotes: list[FootnoteBlock] = Field(
        default_factory=list,
        description="Footnote content blocks.",
    )
    endnotes: list[FootnoteBlock] = Field(
        default_factory=list,
        description="Endnote content blocks.",
    )
    sections: list[SectionMetadata] = Field(
        default_factory=list,
        description="Per-section layout and header/footer references.",
    )
    parse_metadata: ParseMetadata | None = Field(
        default=None,
        description="Parse-time warnings, comments summary, and document resources.",
    )
    reference_graph: ReferenceGraph = Field(
        default_factory=ReferenceGraph,
        description="Global cross-reference graph for numbering and validation.",
    )
    metadata: dict[str, str] = Field(
        default_factory=dict,
        description="Optional document metadata such as title, author, or source path.",
    )

    @model_validator(mode="before")
    @classmethod
    def strip_legacy_computed_fields(cls, data: Any) -> Any:

        if not isinstance(data, dict):
            return data

        normalized = dict(data)
        normalized["blocks"] = [
            cls._strip_block_computed_fields(block)
            for block in normalized.get("blocks", [])
        ]
        for region_key in ("headers", "footers"):
            normalized[region_key] = cls._strip_region_blocks(
                normalized.get(region_key, [])
            )
        for note_key in ("footnotes", "endnotes"):
            normalized[note_key] = cls._strip_note_blocks(
                normalized.get(note_key, [])
            )
        return normalized

    @field_validator("blocks")
    @classmethod
    def block_ids_must_be_unique(cls, value: list[AnyBlockNode]) -> list[AnyBlockNode]:

        ids = [block.id for block in value]
        duplicates = {node_id for node_id in ids if ids.count(node_id) > 1}
        if duplicates:
            raise ValueError(f"存在重复的块节点 ID: {sorted(duplicates)}")
        return value

    def to_persisted_dict(self) -> dict[str, Any]:

        return self.model_dump(
            mode="json",
            exclude={
                "blocks": {"__all__": {"text"}},
                "headers": {"__all__": {"blocks": {"__all__": {"text"}}}},
                "footers": {"__all__": {"blocks": {"__all__": {"text"}}}},
                "footnotes": {"__all__": {"blocks": {"__all__": {"text"}}}},
                "endnotes": {"__all__": {"blocks": {"__all__": {"text"}}}},
                "reference_graph": {
                    "outgoing_by_node_id": True,
                    "incoming_by_node_id": True,
                    "references": {"__all__": {"is_resolved"}},
                },
            },
        )

    def to_persisted_json(self, *, indent: int | None = None) -> str:

        return json.dumps(
            self.to_persisted_dict(),
            ensure_ascii=False,
            indent=indent,
        )

    def write_persisted_json(
        self,
        path: str | Path,
        *,
        indent: int | None = 2,
        encoding: str = "utf-8",
    ) -> None:

        Path(path).write_text(
            self.to_persisted_json(indent=indent),
            encoding=encoding,
        )

    @classmethod
    def from_persisted_dict(cls, data: dict[str, Any]) -> "DocumentAST":

        return cls.model_validate(data)

    @classmethod
    def from_persisted_json(cls, payload: str | bytes) -> "DocumentAST":

        if isinstance(payload, bytes):
            payload = cls._decode_json_bytes(payload)
        return cls.model_validate_json(payload)

    @classmethod
    def from_persisted_json_file(cls, path: str | Path) -> "DocumentAST":

        return cls.from_persisted_json(Path(path).read_bytes())

    @staticmethod
    def _strip_block_computed_fields(block: Any) -> Any:
        if isinstance(block, dict):
            block = dict(block)
            block.pop("text", None)
        return block

    @classmethod
    def _strip_region_blocks(cls, regions: Any) -> Any:
        if not isinstance(regions, list):
            return regions
        stripped: list[Any] = []
        for region in regions:
            if not isinstance(region, dict):
                stripped.append(region)
                continue
            copy = dict(region)
            copy["blocks"] = [
                cls._strip_block_computed_fields(block)
                for block in copy.get("blocks", [])
            ]
            stripped.append(copy)
        return stripped

    @classmethod
    def _strip_note_blocks(cls, notes: Any) -> Any:
        if not isinstance(notes, list):
            return notes
        stripped: list[Any] = []
        for note in notes:
            if not isinstance(note, dict):
                stripped.append(note)
                continue
            copy = dict(note)
            copy["blocks"] = [
                cls._strip_block_computed_fields(block)
                for block in copy.get("blocks", [])
            ]
            stripped.append(copy)
        return stripped

    @staticmethod
    def _decode_json_bytes(payload: bytes) -> str:
        for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be"):
            try:
                return payload.decode(encoding)
            except UnicodeDecodeError:
                continue
        raise UnicodeDecodeError(
            "unknown", payload, 0, 1, "unsupported DocumentAST JSON encoding"
        )

