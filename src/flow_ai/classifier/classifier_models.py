from __future__ import annotations

from pydantic import Field

from flow_ai.contracts.classification_contracts import (
    CandidateType,
    ClassificationDecision,
    PatternMatch,
    PatternType,
    ResolverResult,
)
from flow_ai.contracts.draft_decisions_v3 import (
    DraftClassificationDecision,
    DraftDecisionSidecar,
)
from flow_ai.core.ast_models import StrictASTModel


class EvidenceItem(StrictASTModel):
    source: str = Field(description="Subsystem or heuristic that produced the evidence.")
    label: str = Field(description="Short evidence label.")
    detail: str = Field(default="", description="Human-readable detail for review UI.")
    weight: float = Field(
        default=0.0,
        ge=-1.0,
        le=1.0,
        description="Signed local contribution, not a final confidence.",
    )


__all__ = [
    "CandidateType",
    "ClassificationDecision",
    "DraftClassificationDecision",
    "DraftDecisionSidecar",
    "EvidenceItem",
    "PatternMatch",
    "PatternType",
    "ResolverResult",
]
