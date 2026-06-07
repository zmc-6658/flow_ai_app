"""Internal models for Phase 3 classify pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from flow_ai.core.ast_models import SemanticRole
from flow_ai.core.enums import DocumentRegion


@dataclass(frozen=True)
class TrackResult:
    role: str
    confidence: float
    level: int | None = None
    source: str = "regex"
    semantic_role: SemanticRole | None = None
    reason_text: str = ""


@dataclass
class HygieneFlags:
    is_toc: bool = False
    is_empty: bool = False
    in_list_block: bool = False
    skip_classification: bool = False


@dataclass
class AnnotatedParagraph:
    node_id: str
    text: str
    text_length: int
    hygiene: HygieneFlags = field(default_factory=HygieneFlags)
    visual: TrackResult | None = None
    structural: TrackResult | None = None
    resolved_role: str | None = None
    resolved_level: int | None = None
    semantic_role: SemanticRole = SemanticRole.STANDARD
    region: DocumentRegion = DocumentRegion.BODY
    confidence: float = 0.0
    source: str = "unknown"
    reason_text: str = ""
    structural_level: int | None = None
    style_slot_id: str | None = None
    requires_user_review: bool = False
    breadcrumb: list[str] = field(default_factory=list)
    section_path: str = ""
    suppress_render: bool = False
