from __future__ import annotations

import math
import re
from enum import StrEnum

from flow_ai.core.ast_models import BlockFeatures, TextAlignment
from flow_ai.core.style_models import StyleIntent

from flow_ai.format.ast_reader import ParagraphRecord


def guess_heading_level(text: str) -> int | None:
    compact = re.sub(r"\s+", "", text)
    if re.match(r"^第[一二三四五六七八九十\d]+[章节篇]", compact):
        return 1
    if re.match(r"^[12]\s*[\u4e00-\u9fff]", text) or re.match(r"^\d+\s+[\u4e00-\u9fff]", text):
        return 1
    if re.match(r"^\d+\.\d+\.\d+", text):
        return 3
    if re.match(r"^\d+\.\d+", text):
        return 2
    return None

FONT_SIZE_TOLERANCE = 0.25


class FontSizeBucket(StrEnum):

    XL = "XL"
    L = "L"
    M = "M"
    S = "S"
    UNKNOWN = "UNKNOWN"


class IndentBucket(StrEnum):

    NONE = "none"
    FIRST_LINE = "first_line"
    HANGING = "hanging"


class SpacingBucket(StrEnum):

    NONE = "none"
    SMALL = "small"
    LARGE = "large"


COVER_INFO_RE = re.compile(r"^\s*(专\s*业|班\s*级|姓\s*名|学\s*号|指导教师)")


def normalize_font_size_pt(size: float | None) -> float | None:
    if size is None or size <= 0:
        return None
    return round(size * 2) / 2.0


def font_size_bucket(size: float | None) -> FontSizeBucket:
    normalized = normalize_font_size_pt(size)
    if normalized is None:
        return FontSizeBucket.UNKNOWN

    if normalized >= 18.0 or _near(normalized, 18.0, above=True):
        return FontSizeBucket.XL
    if normalized >= 15.0 or _near(normalized, 15.0):
        return FontSizeBucket.L
    if normalized >= 10.5 or _near(normalized, 12.0):
        return FontSizeBucket.M
    return FontSizeBucket.S


def _near(value: float, target: float, above: bool = False) -> bool:
    if above:
        return target - FONT_SIZE_TOLERANCE <= value < target + 1.0
    return math.isclose(value, target, abs_tol=FONT_SIZE_TOLERANCE)


def effective_alignment(record: ParagraphRecord) -> TextAlignment:
    alignment = record.features.alignment
    if alignment != TextAlignment.UNKNOWN:
        return alignment
    text = record.text.strip()
    if COVER_INFO_RE.match(text):
        return TextAlignment.LEFT
    if record.features.bold_ratio >= 0.9 and len(text) <= 80:
        if "摘要" in text or text.upper() == "ABSTRACT" or text == "目录":
            return TextAlignment.CENTER
        if "学院" in text or "毕业论文" in text:
            return TextAlignment.CENTER
    if re.match(r"^论文题目", text):
        return TextAlignment.CENTER
    if re.match(r"^\d{4}\s*年", text):
        return TextAlignment.CENTER
    return TextAlignment.LEFT


def indent_bucket(features: BlockFeatures) -> IndentBucket:
    first = features.indent_first_line_twips
    if first is None or first == 0:
        return IndentBucket.NONE
    if first > 0:
        return IndentBucket.FIRST_LINE
    return IndentBucket.HANGING


def spacing_bucket(features: BlockFeatures) -> SpacingBucket:
    before = features.spacing_before_twips or 0
    after = features.spacing_after_twips or 0
    total = before + after
    if total <= 0:
        return SpacingBucket.NONE
    if total <= 240:
        return SpacingBucket.SMALL
    return SpacingBucket.LARGE


def bold_dominant(features: BlockFeatures) -> bool:
    return features.bold_ratio >= 0.5


def build_fingerprint(
    record: ParagraphRecord,
    intent: StyleIntent | None = None,
) -> tuple[str, ...]:
    alignment = effective_alignment(record)
    if alignment == TextAlignment.UNKNOWN and intent and intent.alignment is not None:
        alignment = intent.alignment

    size = record.features.dominant_font_size
    if size is None and intent and intent.font_size_pt is not None:
        size = intent.font_size_pt

    heading_tier = _heading_tier(record, intent)

    return (
        record.region,
        alignment.value,
        font_size_bucket(size).value,
        "bold" if bold_dominant(record.features) else "normal",
        indent_bucket(record.features).value,
        spacing_bucket(record.features).value,
        heading_tier,
    )


def _heading_tier(record: ParagraphRecord, intent: StyleIntent | None) -> str:
    level = guess_heading_level(record.text)
    if level is not None:
        return f"h{level}"
    if intent is not None and intent.outline_level is not None:
        return f"h{intent.outline_level + 1}"
    if record.heading_level is not None:
        return f"h{record.heading_level}"
    return "none"


def fingerprint_key(fingerprint: tuple[str, ...]) -> str:
    return "|".join(fingerprint)
