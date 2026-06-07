"""Pass 2: arbitration matrix."""

from __future__ import annotations

from dataclasses import dataclass

from flow_ai.classifier.pipeline_models import AnnotatedParagraph, TrackResult


@dataclass
class ArbitrationOutcome:
    role: str | None
    level: int | None
    confidence: float
    source: str
    reason_text: str
    structural_level: int | None = None
    style_slot_id: str | None = None
    requires_user_review: bool = False


def _heading_level(result: TrackResult | None) -> int | None:
    if result is None:
        return None
    if result.level is not None:
        return result.level
    if result.role.startswith("HEADING_"):
        try:
            return int(result.role.split("_")[1])
        except (IndexError, ValueError):
            return None
    return None


def _role_family(role: str) -> str:
    if role.startswith("HEADING"):
        return "HEADING"
    if role.endswith("_ANCHOR"):
        return "ANCHOR"
    if role == "LIST_ITEM" or role.startswith("LIST"):
        return "LIST"
    return role


def arbitrate_role(
    visual: TrackResult | None,
    structural: TrackResult | None,
    *,
    next_para_long: bool = False,
) -> ArbitrationOutcome:
    if visual is None and structural is None:
        return ArbitrationOutcome(
            role=None,
            level=None,
            confidence=0.0,
            source="unknown",
            reason_text="双轨均未命中",
        )

    if visual is not None and structural is not None:
        v_level = _heading_level(visual)
        s_level = _heading_level(structural)

        if visual.role == structural.role or (
            v_level is not None and v_level == s_level and _role_family(visual.role) == _role_family(structural.role)
        ):
            conf = max(visual.confidence, structural.confidence)
            return ArbitrationOutcome(
                role=structural.role,
                level=s_level or v_level,
                confidence=conf,
                source="arbitration_agree",
                reason_text=structural.reason_text or visual.reason_text,
                structural_level=s_level,
                style_slot_id=visual.role if visual.source == "format_slot_kb" else None,
            )

        gap = abs((v_level or 0) - (s_level or 0))

        if structural.role == "LIST_ITEM" and visual.role.startswith("HEADING"):
            if next_para_long:
                return _from_visual(visual, structural)
            return _from_structural(structural, visual)

        if gap >= 2:
            if structural.confidence >= 0.85:
                return _from_structural(structural, visual, split=True)
            if visual.confidence >= 0.88:
                return _from_visual(visual, structural, split=True)
            return ArbitrationOutcome(
                role=None,
                level=None,
                confidence=0.0,
                source="arbitration_gap",
                reason_text="层级冲突且置信度不足",
                requires_user_review=True,
            )

        if structural.confidence >= 0.85:
            return _from_structural(structural, visual, split=True)

        if visual.confidence >= 0.88:
            return _from_visual(visual, structural)

        return _from_structural(structural, visual)

    if structural is not None:
        return _from_structural(structural, visual)
    return _from_visual(visual, structural)


def _from_structural(
    structural: TrackResult,
    visual: TrackResult | None,
    *,
    split: bool = False,
) -> ArbitrationOutcome:
    level = _heading_level(structural)
    style_slot = None
    if split and visual is not None and visual.source == "format_slot_kb":
        style_slot = visual.role
    return ArbitrationOutcome(
        role=structural.role,
        level=level,
        confidence=structural.confidence,
        source="regex" if structural.source == "regex" else structural.source,
        reason_text=structural.reason_text,
        structural_level=level,
        style_slot_id=style_slot,
    )


def _from_visual(
    visual: TrackResult,
    structural: TrackResult | None,
    *,
    split: bool = False,
) -> ArbitrationOutcome:
    level = _heading_level(visual)
    struct_level = _heading_level(structural) if structural else level
    return ArbitrationOutcome(
        role=visual.role,
        level=level,
        confidence=visual.confidence,
        source=visual.source,
        reason_text=visual.reason_text,
        structural_level=struct_level if split else level,
        style_slot_id=visual.role if visual.source == "format_slot_kb" else None,
    )


def apply_arbitration(para: AnnotatedParagraph, outcome: ArbitrationOutcome) -> None:
    if outcome.role is None:
        return
    para.resolved_role = outcome.role
    para.resolved_level = outcome.level
    para.confidence = outcome.confidence
    para.source = outcome.source
    para.reason_text = outcome.reason_text
    para.structural_level = outcome.structural_level
    para.style_slot_id = outcome.style_slot_id
    para.requires_user_review = outcome.requires_user_review
    if para.semantic_role.value == "standard" and para.structural and para.structural.semantic_role:
        para.semantic_role = para.structural.semantic_role
