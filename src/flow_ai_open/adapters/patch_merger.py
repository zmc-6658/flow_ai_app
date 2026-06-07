from __future__ import annotations

from typing import Literal

from pydantic import Field

from flow_ai.contracts.classification_contracts import (
    CandidateType,
    ClassificationDecision,
)
from flow_ai.contracts.error_codes import ErrorCode
from flow_ai.contracts.status_shell import StatusShell
from flow_ai.core.ast_models import NodeID, SemanticRole, StrictASTModel
from flow_ai.core.enums import DocumentRegion


ConfirmationType = Literal["explicit_edit", "verify_adopted"]


class EngineSuggestionPayload(StrictASTModel):
    assigned_style_id: str | None = None
    semantic_role: SemanticRole | None = None


class DecisionPatch(StrictASTModel):

    node_id: NodeID
    candidate_type: CandidateType | None = None
    suggested_level: int | None = Field(
        default=None, ge=1, le=9, description="New heading level, or None to keep."
    )
    semantic_role: SemanticRole | None = None
    suppress_render: bool | None = None
    assigned_style_id: str | None = None
    region: DocumentRegion | None = None
    confirmation_type: ConfirmationType | None = None
    target_base_role_id: str | None = None
    engine_suggestion: EngineSuggestionPayload | None = None
    start: int | None = Field(default=None, ge=0)
    end: int | None = Field(default=None, ge=0)


class PatchMerger:

    def merge(
        self,
        original: list[ClassificationDecision],
        patches: list[DecisionPatch],
    ) -> StatusShell[list[ClassificationDecision]]:
        patch_map: dict[NodeID, DecisionPatch] = {p.node_id: p for p in patches}
        unknown_ids = [p.node_id for p in patches if p.node_id not in {d.node_id for d in original}]
        if unknown_ids:
            return StatusShell(
                data=None,
                error_code=ErrorCode.PATCH_CONFLICT,
                message=f"补丁中包含未知节点: {unknown_ids}",
            )

        merged: list[ClassificationDecision] = []
        for decision in original:
            patch = patch_map.get(decision.node_id)
            if patch is None:
                merged.append(decision)
                continue
            merged.append(self._apply_patch(decision, patch))
        return StatusShell(data=merged)

    @staticmethod
    def _apply_patch(
        decision: ClassificationDecision, patch: DecisionPatch
    ) -> ClassificationDecision:
        update: dict = {}
        if patch.candidate_type is not None:
            update["candidate_type"] = patch.candidate_type
        if patch.suggested_level is not None:
            update["suggested_level"] = patch.suggested_level
        if patch.semantic_role is not None:
            update["semantic_role"] = patch.semantic_role
        if patch.suppress_render is not None:
            update["suppress_render"] = patch.suppress_render
        if patch.region is not None:
            update["region"] = patch.region
        if not update:
            return decision
        return decision.model_copy(update=update)
