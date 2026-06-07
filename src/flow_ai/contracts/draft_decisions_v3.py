from __future__ import annotations

from pydantic import Field

from flow_ai.core.ast_models import NodeID, SemanticRole, StrictASTModel
from flow_ai.core.enums import DocumentRegion


class DraftClassificationDecision(StrictASTModel):
    node_id: NodeID
    region: DocumentRegion
    candidate_type: str = Field(default="paragraph", description="Tentative candidate type before final resolution.")
    suggested_level: int | None = Field(default=None, ge=1, le=9)
    semantic_role: SemanticRole = Field(default=SemanticRole.STANDARD)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)


class DraftDecisionSidecar(StrictASTModel):
    decisions: list[DraftClassificationDecision] = Field(default_factory=list)
    needs_review: bool = Field(default=True, description="Whether any decision has low confidence and needs user review.")
    low_confidence_ids: list[NodeID] = Field(default_factory=list, description="Node IDs with confidence below threshold.")
