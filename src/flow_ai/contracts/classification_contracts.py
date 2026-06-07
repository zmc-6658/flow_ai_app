from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from flow_ai.core.ast_models import NodeID, SemanticRole, StrictASTModel
from flow_ai.core.enums import DocumentRegion
from flow_ai.core.profile_models import PageBreakDecision


class PatternType(StrEnum):
    ARABIC_SINGLE = "arabic_single"
    ARABIC_DECIMAL = "arabic_decimal"
    CHINESE_DUN = "chinese_dun"
    CHINESE_PAREN = "chinese_paren"
    CHAPTER = "chapter"
    UNNUMBERED_SPECIAL = "unnumbered_special"
    TOC_ENTRY = "toc_entry"


class CandidateType(StrEnum):
    HEADING = "heading"
    LIST_ITEM = "list_item"
    PARAGRAPH = "paragraph"


class PatternMatch(StrictASTModel):
    node_id: NodeID
    text: str = Field(default="", description="Normalized paragraph text snapshot.")
    raw_marker: str = Field(description="Matched marker text, such as '1.1' or '（一）'.")
    pattern_type: PatternType
    marker_depth: int = Field(ge=1, description="Structural marker depth, e.g. '1.1.1' has depth 3.")
    semantic_role: SemanticRole = Field(default=SemanticRole.STANDARD, description="Potential role for unnumbered special matches.")
    has_toc_page_trailing: bool = Field(default=False, description="Whether the paragraph looks like a stale TOC entry with page number.")


class ClassificationDecision(StrictASTModel):
    node_id: NodeID
    region: DocumentRegion
    candidate_type: CandidateType
    suggested_level: int | None = Field(default=None, ge=1, le=9, description="Heading level when candidate_type is heading.")
    semantic_role: SemanticRole = Field(default=SemanticRole.STANDARD, description="Special role attached when this decision becomes a HeadingNode.")
    suppress_render: bool = Field(default=False, description="Preserve node in AST but ask renderer to skip it.")
    page_break_decision: PageBreakDecision | None = Field(default=None, description="Confirmed handling for a source page break adjacent to this node.")
    confidence: float = Field(default=0.0, ge=0.0, le=1.0, description="Resolver confidence for the decision.")
    reasons: list[str] = Field(default_factory=list, description="Human-readable evidence used to make the decision.")
    reason_text: str | None = Field(default=None, description="User-facing Chinese explanation for UI tooltip.")
    source: str | None = Field(default=None, description="Decision origin: visual, regex, arbitration, probe, stack, etc.")
    requires_user_review: bool = Field(default=False, description="Frontend should prompt user confirmation.")
    structural_level: int | None = Field(default=None, ge=1, le=9, description="Tree structural level from regex track.")
    style_slot_id: str | None = Field(default=None, description="Phase 2 format slot for rendering style.")
    breadcrumb: list[str] = Field(default_factory=list, description="Section breadcrumb labels.")
    section_path: str | None = Field(default=None, description="Flat section path for O(1) ancestor checks.")


class LeafRef(StrictASTModel):
    para_id: NodeID
    injected_role: str
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class ContentNode(StrictASTModel):
    node_type: str = Field(description="chapter | section | front_matter | back_matter | toc")
    heading_para_id: NodeID
    heading_level: int = Field(default=0, ge=0, le=9)
    section_path: str = Field(default="")
    children: list["ContentNode | LeafRef"] = Field(default_factory=list)


ContentNode.model_rebuild()


class DocumentContentTree(StrictASTModel):
    root: list[ContentNode] = Field(default_factory=list)


class ResolverResult(StrictASTModel):
    decisions: list[ClassificationDecision] = Field(default_factory=list)
    needs_toc_anchor: bool = True
    toc_anchor_node_id: NodeID | None = Field(default=None, description="Node before which HeadingBinder should insert the virtual TOC anchor.")
    body_start_node_id: NodeID | None = Field(default=None, description="First node considered BODY; used for virtual TOC anchor insertion.")
    content_tree: DocumentContentTree | None = Field(default=None, description="Reference tree for frontend navigation; optional.")
