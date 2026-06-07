"""Pass 3: naked heading probe."""

from __future__ import annotations

import re

from flow_ai.classifier.pipeline_models import AnnotatedParagraph
from flow_ai.core.ast_models import SemanticRole

SENTENCE_END = ("。", ".", "！", "!", "？", "?")

NEGATIVE_PATTERNS = [
    re.compile(r"^(因此|综上所述|由此|所以|总之|然而|但是|此外)"),
    re.compile(r"^关键词[:：]"),
    re.compile(r"^(图|表|Fig|Table)\s*\d", re.IGNORECASE),
    re.compile(r"^\d+$"),
    re.compile(r"^(注|注释|备注)[:：]"),
    re.compile(r"^\[\d+\]"),
]


class NakedHeadingProbe:
    max_length: int = 25
    min_neighbor_length: int = 50

    def probe(
        self,
        para: AnnotatedParagraph,
        prev_para: AnnotatedParagraph | None,
        next_para: AnnotatedParagraph | None,
    ) -> bool:
        if para.resolved_role is not None:
            return False
        if para.hygiene.skip_classification or para.hygiene.in_list_block:
            return False
        text = para.text.strip()
        if not text or len(text) >= self.max_length:
            return False
        if text.endswith(SENTENCE_END):
            return False
        if any(p.match(text) for p in NEGATIVE_PATTERNS):
            return False
        prev_len = prev_para.text_length if prev_para else 0
        next_len = next_para.text_length if next_para else 0
        if prev_len <= self.min_neighbor_length or next_len <= self.min_neighbor_length:
            return False

        confidence = 0.45
        reasons = ["短句", "无句尾标点", "前后均为长段"]

        if next_para and re.match(r"^(本节|本章|如下|以下)", next_para.text.strip()):
            confidence += 0.10
            reasons.append("下段以引导词开头")
        if prev_para and prev_para.text.rstrip().endswith((":", "：")):
            confidence += 0.05
            reasons.append("上段以冒号结尾")

        para.resolved_role = "SUSPECTED_HEADING"
        para.resolved_level = 2
        para.confidence = min(confidence, 0.59)
        para.source = "naked_probe"
        para.reason_text = "疑似无格式标题：" + "；".join(reasons)
        para.semantic_role = SemanticRole.STANDARD
        para.requires_user_review = confidence < 0.60
        return True
