from __future__ import annotations

from flow_ai.core.ast_models import TextAlignment

from flow_ai.format.ast_reader import ParagraphRecord
from flow_ai.format.semantic_anchor import DocumentSection
from flow_ai.format.visual_fingerprint import (
    effective_alignment,
    guess_heading_level,
    normalize_font_size_pt,
)


def compute_visual_weight(
    record: ParagraphRecord,
    block_index: int,
    section: DocumentSection,
) -> float:
    score = 1.0
    size = normalize_font_size_pt(record.features.dominant_font_size)
    if size is not None:
        score += max(0.0, (size - 12.0) * 0.5)

    if record.features.bold_ratio >= 0.5:
        score += 2.0

    if section in (DocumentSection.COVER, DocumentSection.FRONT_MATTER, DocumentSection.TOC):
        score += 1.5

    if effective_alignment(record) == TextAlignment.CENTER:
        score += 1.0

    if block_index < 120:
        score += max(0.0, (120 - block_index) / 120.0)

    return round(score, 2)
