from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from flow_ai.core.ast_models import NodeID, SemanticRole, StrictASTModel


class PageBreakDecision(StrEnum):

    KEEP = "keep"
    MIGRATE = "migrate"
    DELETE = "delete"


class TocVisualProfile(StrictASTModel):

    has_dot_leader: bool = True
    page_number_alignment: str = Field(default="right")
    right_tab_twips: int | None = Field(default=None, ge=0)
    entry_styles: dict[int, str] = Field(
        default_factory=lambda: {1: "TOC 1", 2: "TOC 2", 3: "TOC 3"}
    )


class FrontMatterProfile(StrictASTModel):

    semantic_role: SemanticRole
    prefix_label: str
    label_font_bold: bool = True
    label_font_name: str | None = None
    label_font_size_pt: float | None = Field(default=None, gt=0)
    content_style: str = "FlowBody"
    no_first_line_indent: bool = True


class ReferenceProfile(StrictASTModel):

    entry_style: str = "FlowReferencesItem"
    right_indent_pt: float | None = 24.0
    line_spacing_pt: float | None = 23.0


class AcknowledgmentProfile(StrictASTModel):

    body_style: str = "FlowAcknowledgmentBody"
    first_line_indent_pt: float | None = 24.0
    right_indent_pt: float | None = 24.0
    line_spacing_pt: float | None = 23.0


class RenderProfiles(StrictASTModel):

    toc_visual: TocVisualProfile = Field(default_factory=TocVisualProfile)
    front_matter: dict[SemanticRole, FrontMatterProfile] = Field(default_factory=dict)
    reference: ReferenceProfile = Field(default_factory=ReferenceProfile)
    acknowledgment: AcknowledgmentProfile = Field(default_factory=AcknowledgmentProfile)
    page_break_decisions: dict[NodeID, PageBreakDecision] = Field(default_factory=dict)

    @classmethod
    def fallback(cls) -> "RenderProfiles":
        return cls(
            front_matter={
                SemanticRole.ABSTRACT_BODY: FrontMatterProfile(
                    semantic_role=SemanticRole.ABSTRACT_BODY,
                    prefix_label="摘要",
                    label_font_name="黑体",
                    label_font_size_pt=14.0,
                    content_style="FlowAbstractBody",
                ),
                SemanticRole.KEYWORDS: FrontMatterProfile(
                    semantic_role=SemanticRole.KEYWORDS,
                    prefix_label="关键词",
                    label_font_name="黑体",
                    label_font_size_pt=14.0,
                    content_style="FlowKeywords",
                ),
                SemanticRole.ABSTRACT_BODY_EN: FrontMatterProfile(
                    semantic_role=SemanticRole.ABSTRACT_BODY_EN,
                    prefix_label="ABSTRACT",
                    label_font_name="Times New Roman",
                    label_font_size_pt=14.0,
                    content_style="FlowAbstractBodyEN",
                ),
                SemanticRole.KEYWORDS_EN: FrontMatterProfile(
                    semantic_role=SemanticRole.KEYWORDS_EN,
                    prefix_label="KEY WORDS",
                    label_font_name="Times New Roman",
                    label_font_size_pt=14.0,
                    content_style="FlowKeywordsEN",
                ),
            }
        )
