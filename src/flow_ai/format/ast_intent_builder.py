from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx import Document

from flow_ai.core.ast_models import BlockFeatures, InlineSpan, TextAlignment
from flow_ai.core.style_models import StyleIntent
from flow_ai.format.ast_reader import ParagraphRecord
from flow_ai.format.style_resolver import WordStyleResolver
from flow_ai.format.visual_fingerprint import effective_alignment, normalize_font_size_pt


@dataclass
class IntentBuildContext:

    docx_path: Path | None = None
    document: Document | None = None
    resolver: WordStyleResolver | None = None


def build_style_intent(
    record: ParagraphRecord,
    context: IntentBuildContext | None = None,
) -> StyleIntent:
    resolver_intent = _resolve_via_docx(record, context)
    if resolver_intent:
        return StyleIntent.model_validate(resolver_intent)

    intent: dict[str, Any] = {}
    features = record.features
    alignment = effective_alignment(record)
    if alignment != TextAlignment.UNKNOWN:
        intent["alignment"] = alignment.value

    size = normalize_font_size_pt(features.dominant_font_size)
    if size is None:
        size = _dominant_span_size(record.spans)
    if size is not None:
        intent["font_size_pt"] = size

    if features.bold_ratio >= 0.5:
        intent["bold"] = True
    elif features.bold_ratio <= 0.05:
        intent["bold"] = False

    if features.east_asia_font:
        intent["east_asia_font"] = features.east_asia_font
    elif features.dominant_font_family:
        intent["font_name"] = features.dominant_font_family

    if features.spacing_before_twips is not None:
        intent["space_before_pt"] = round(features.spacing_before_twips / 20.0, 2)
    if features.spacing_after_twips is not None:
        intent["space_after_pt"] = round(features.spacing_after_twips / 20.0, 2)

    first_indent = features.indent_first_line_twips
    if first_indent is not None:
        if first_indent >= 0:
            intent["first_line_indent_pt"] = round(first_indent / 20.0, 2)
        else:
            intent["hanging_indent_pt"] = round(abs(first_indent) / 20.0, 2)

    if features.style_name:
        intent["style_name"] = features.style_name

    return StyleIntent.model_validate({k: v for k, v in intent.items() if v is not None})


def _dominant_span_size(spans: tuple[InlineSpan, ...]) -> float | None:
    sizes = [
        normalize_font_size_pt(span.features.font_size_pt)
        for span in spans
        if span.features.font_size_pt is not None
    ]
    if not sizes:
        return None
    return max(sizes, key=sizes.count)


def _resolve_via_docx(
    record: ParagraphRecord,
    context: IntentBuildContext | None,
) -> dict[str, Any] | None:
    if context is None or context.document is None or record.source_index is None:
        return None
    try:
        paragraphs = list(context.document.paragraphs)
        if record.source_index < 0 or record.source_index >= len(paragraphs):
            return None
        paragraph = paragraphs[record.source_index]
        if context.resolver is None:
            context.resolver = WordStyleResolver(context.document)
        return dict(context.resolver.resolve_paragraph(paragraph).intent)
    except Exception:
        return None


def create_intent_context(docx_path: Path) -> IntentBuildContext:
    document = Document(str(docx_path))
    return IntentBuildContext(
        docx_path=docx_path,
        document=document,
        resolver=WordStyleResolver(document),
    )
