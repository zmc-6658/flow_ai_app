from __future__ import annotations

import re
from collections import Counter

from flow_ai.classifier.classifier_models import (
    CandidateType,
    ClassificationDecision,
    PatternMatch,
    PatternType,
    ResolverResult,
)
from flow_ai.core.enums import DocumentRegion
from flow_ai.core.ast_models import DocumentAST, ParagraphNode, SemanticRole


TITLE_EXCLUDED_PATTERN = re.compile(
    r"^(摘要|目录|参考文献|致谢|附录|关键词|ABSTRACT|Abstract)$",
    re.IGNORECASE,
)
SENTENCE_ENDINGS = ("。", ".", "！", "!", "？", "?")


class StructureResolver:

    LIST_LIKE_PATTERN_TYPES = {
        PatternType.CHINESE_PAREN,
        PatternType.CHINESE_DUN,
    }
    TOP_LEVEL_CANDIDATES = {
        PatternType.CHAPTER,
        PatternType.ARABIC_SINGLE,
        PatternType.CHINESE_DUN,
        PatternType.ARABIC_DECIMAL,
    }

    def resolve(
        self, ast: DocumentAST, matches: list[PatternMatch]
    ) -> ResolverResult:

        block_positions = {node.id: index for index, node in enumerate(ast.blocks)}
        match_by_node_id = {match.node_id: match for match in matches}
        ordered_matches = sorted(
            matches,
            key=lambda match: block_positions.get(match.node_id, len(ast.blocks)),
        )
        list_item_node_ids = self._detect_dense_list_items(
            ordered_matches, block_positions
        )
        hierarchy = self._infer_hierarchy(ordered_matches)

        decisions: list[ClassificationDecision] = []
        current_region = DocumentRegion.FRONT
        has_old_toc = False
        suppress_old_toc_entries = False
        body_start_node_id: str | None = None
        toc_anchor_node_id: str | None = None
        title_cn_assigned = False
        active_back_role: SemanticRole | None = None

        for node in ast.blocks:
            match = match_by_node_id.get(node.id)

            if suppress_old_toc_entries and self._is_blank_paragraph(node):
                decisions.append(
                    self._decision(
                        node_id=node.id,
                        region=current_region,
                        candidate_type=CandidateType.PARAGRAPH,
                        suppress_render=True,
                        confidence=0.99,
                        reasons=["old_toc_blank_line_suppressed"],
                    )
                )
                continue

            if (
                suppress_old_toc_entries
                and match is not None
                and match.pattern_type == PatternType.TOC_ENTRY
            ):
                decisions.append(
                    self._decision(
                        node_id=node.id,
                        region=current_region,
                        candidate_type=CandidateType.PARAGRAPH,
                        suppress_render=True,
                        confidence=0.99,
                        reasons=["old_toc_entry_suppressed"],
                    )
                )
                continue

            if suppress_old_toc_entries:
                suppress_old_toc_entries = False

            if match is None:
                front_role = self._front_matter_role(node, title_cn_assigned)
                if current_region == DocumentRegion.FRONT and front_role is not None:
                    if front_role == SemanticRole.TITLE_CN:
                        title_cn_assigned = True
                    decisions.append(
                        self._decision(
                            node_id=node.id,
                            region=current_region,
                            candidate_type=CandidateType.PARAGRAPH,
                            semantic_role=front_role,
                            confidence=0.82,
                            reasons=[f"front_matter_{front_role.value}_candidate"],
                        )
                    )
                    continue

                back_role = self._back_matter_role(
                    node, current_region, active_back_role
                )
                decisions.append(
                    self._decision(
                        node_id=node.id,
                        region=current_region,
                        candidate_type=CandidateType.PARAGRAPH,
                        semantic_role=back_role,
                        reasons=["no_probe_match"],
                    )
                )
                continue

            if match.pattern_type == PatternType.TOC_ENTRY:
                decisions.append(
                    self._decision(
                        node_id=node.id,
                        region=current_region,
                        candidate_type=CandidateType.PARAGRAPH,
                        confidence=0.6,
                        reasons=["toc_entry_signature_without_toc_title"],
                    )
                )
                continue

            if match.pattern_type == PatternType.UNNUMBERED_SPECIAL:
                decision = self._resolve_special(
                    match=match,
                    region=current_region,
                )
                if decision.semantic_role == SemanticRole.TOC and decision.candidate_type == CandidateType.HEADING:
                    has_old_toc = True
                    toc_anchor_node_id = node.id
                    suppress_old_toc_entries = True
                    decision = decision.model_copy(
                        update={
                            "suppress_render": True,
                            "reasons": decision.reasons
                            + ["old_toc_heading_replaced_by_anchor"],
                        }
                    )
                if decision.semantic_role in {
                    SemanticRole.REFERENCES,
                    SemanticRole.ACKNOWLEDGMENT,
                    SemanticRole.APPENDIX,
                } and decision.candidate_type == CandidateType.HEADING:
                    current_region = DocumentRegion.BACK
                    active_back_role = decision.semantic_role
                    decision = decision.model_copy(update={"region": current_region})
                decisions.append(decision)
                continue

            if current_region == DocumentRegion.FRONT and self._is_body_start(
                match, hierarchy
            ):
                current_region = DocumentRegion.BODY
                body_start_node_id = node.id

            if current_region == DocumentRegion.BODY and match.node_id in list_item_node_ids:
                decisions.append(
                    self._decision(
                        node_id=node.id,
                        region=current_region,
                        candidate_type=CandidateType.LIST_ITEM,
                        confidence=0.86,
                        reasons=["dense_same_pattern_sequence", "list_safety_lock"],
                    )
                )
                continue

            level = self._suggest_level(match, hierarchy)
            if current_region == DocumentRegion.BODY and level is not None:
                decisions.append(
                    self._decision(
                        node_id=node.id,
                        region=current_region,
                        candidate_type=CandidateType.HEADING,
                        suggested_level=level,
                        confidence=0.8,
                        reasons=[
                            f"pattern_type={match.pattern_type.value}",
                            f"inferred_top={hierarchy.top_pattern.value}",
                        ],
                    )
                )
                continue

            semantic_role = self._back_matter_role(node, current_region, active_back_role)
            decisions.append(
                self._decision(
                    node_id=node.id,
                    region=current_region,
                    candidate_type=CandidateType.PARAGRAPH,
                    semantic_role=semantic_role,
                    confidence=0.55,
                    reasons=["probe_match_not_valid_in_current_region"],
                )
            )

        return ResolverResult(
            decisions=decisions,
            needs_toc_anchor=True,
            toc_anchor_node_id=toc_anchor_node_id or body_start_node_id,
            body_start_node_id=body_start_node_id,
        )

    def _detect_dense_list_items(
        self,
        matches: list[PatternMatch],
        block_positions: dict[str, int],
        max_block_gap: int = 3,
    ) -> set[str]:

        list_ids: set[str] = set()
        run: list[PatternMatch] = []

        def flush() -> None:
            if len(run) >= 2 and run[0].pattern_type in self.LIST_LIKE_PATTERN_TYPES:
                list_ids.update(match.node_id for match in run)

        for match in matches:
            if not run:
                run = [match]
                continue

            previous = run[-1]
            same_pattern = match.pattern_type == previous.pattern_type
            close_enough = (
                block_positions.get(match.node_id, 10**9)
                - block_positions.get(previous.node_id, -10**9)
                <= max_block_gap
            )
            if same_pattern and close_enough:
                run.append(match)
                continue

            flush()
            run = [match]

        flush()
        return list_ids

    def _is_blank_paragraph(self, node) -> bool:

        return isinstance(node, ParagraphNode) and node.text.strip() == ""

    def _front_matter_role(
        self,
        node,
        title_cn_assigned: bool,
    ) -> SemanticRole | None:
        if not isinstance(node, ParagraphNode):
            return None

        text = node.text.strip()
        if text == "":
            return None

        compact_text = re.sub(r"\s+", "", text).lower()
        if compact_text.startswith("摘要") and len(compact_text) > 2:
            return SemanticRole.ABSTRACT_BODY
        if compact_text.startswith("关键词"):
            return SemanticRole.KEYWORDS
        if compact_text.startswith("abstract") and len(compact_text) > 8:
            return SemanticRole.ABSTRACT_BODY_EN
        if compact_text.startswith("keywords"):
            return SemanticRole.KEYWORDS_EN
        if not title_cn_assigned and self._is_title_cn_candidate(node):
            return SemanticRole.TITLE_CN
        if title_cn_assigned and self._is_title_en_candidate(node):
            return SemanticRole.TITLE_EN
        return None

    def _back_matter_role(
        self,
        node,
        region: DocumentRegion,
        active_back_role: SemanticRole | None,
    ) -> SemanticRole:
        if region != DocumentRegion.BACK or not isinstance(node, ParagraphNode):
            return SemanticRole.STANDARD

        text = node.text.strip()
        if self._is_reference_item(text):
            return SemanticRole.REFERENCES_ITEM
        if active_back_role == SemanticRole.ACKNOWLEDGMENT and text:
            return SemanticRole.ACKNOWLEDGMENT_BODY
        if active_back_role == SemanticRole.APPENDIX and text:
            return SemanticRole.APPENDIX_BODY
        return SemanticRole.STANDARD

    def _is_reference_item(self, text: str) -> bool:
        return re.match(r"^(\[\d+\]|［\d+］|\d+[.．、]\s*)", text) is not None

    def _is_title_cn_candidate(self, node) -> bool:

        if not isinstance(node, ParagraphNode):
            return False

        text = node.text.strip()
        if not (6 <= len(text) <= 80):
            return False
        if TITLE_EXCLUDED_PATTERN.match(text):
            return False
        if text.endswith(SENTENCE_ENDINGS):
            return False
        if not re.search(r"[\u4e00-\u9fff]", text):
            return False
        if re.match(r"^\s*(第[一二三四五六七八九十百零〇两]+[章部分]|\d+\.?)", text):
            return False
        if node.source_index is not None and node.source_index > 30:
            return False
        return True

    def _is_title_en_candidate(self, node) -> bool:
        if not isinstance(node, ParagraphNode):
            return False

        text = node.text.strip()
        if not (12 <= len(text) <= 180):
            return False
        if not re.search(r"[A-Za-z]", text):
            return False
        if re.search(r"[\u4e00-\u9fff]", text):
            return False
        if text.lower().startswith(("abstract", "keywords", "key words")):
            return False
        if text.endswith(SENTENCE_ENDINGS):
            return False
        if node.source_index is not None and node.source_index > 35:
            return False
        return True


    def _resolve_special(
        self,
        match: PatternMatch,
        region: DocumentRegion,
    ) -> ClassificationDecision:

        role = match.semantic_role
        if role in {SemanticRole.TOC, SemanticRole.ABSTRACT} and region == DocumentRegion.FRONT:
            return self._decision(
                node_id=match.node_id,
                region=region,
                candidate_type=CandidateType.HEADING,
                suggested_level=1,
                semantic_role=role,
                confidence=0.98,
                reasons=["front_matter_special_whitelist"],
            )

        if role in {
            SemanticRole.REFERENCES,
            SemanticRole.ACKNOWLEDGMENT,
            SemanticRole.APPENDIX,
        } and region in {DocumentRegion.BODY, DocumentRegion.BACK}:
            return self._decision(
                node_id=match.node_id,
                region=region,
                candidate_type=CandidateType.HEADING,
                suggested_level=1,
                semantic_role=role,
                confidence=0.96,
                reasons=["back_matter_special_whitelist"],
            )

        return self._decision(
            node_id=match.node_id,
            region=region,
            candidate_type=CandidateType.PARAGRAPH,
            semantic_role=role,
            confidence=0.5,
            reasons=["special_keyword_rejected_by_region_lock"],
        )

    def _is_body_start(
        self, match: PatternMatch, hierarchy: "_HierarchyInference"
    ) -> bool:

        if match.pattern_type == PatternType.CHAPTER:
            return True
        if match.pattern_type == hierarchy.top_pattern and self._suggest_level(
            match, hierarchy
        ) == 1:
            return True
        return False

    def _decision(
        self,
        node_id: str,
        region: DocumentRegion,
        candidate_type: CandidateType,
        suggested_level: int | None = None,
        semantic_role: SemanticRole = SemanticRole.STANDARD,
        suppress_render: bool = False,
        confidence: float = 0.0,
        reasons: list[str] | None = None,
    ) -> ClassificationDecision:

        return ClassificationDecision(
            node_id=node_id,
            region=region,
            candidate_type=candidate_type,
            suggested_level=suggested_level,
            semantic_role=semantic_role,
            suppress_render=suppress_render,
            confidence=confidence,
            reasons=reasons or [],
        )

    def _infer_hierarchy(self, matches: list[PatternMatch]) -> "_HierarchyInference":

        counts = Counter(
            match.pattern_type
            for match in matches
            if match.pattern_type in self.TOP_LEVEL_CANDIDATES
        )
        if not counts:
            return _HierarchyInference(top_pattern=PatternType.ARABIC_SINGLE)

        for preferred in (
            PatternType.CHAPTER,
            PatternType.ARABIC_SINGLE,
            PatternType.CHINESE_DUN,
        ):
            if counts[preferred] >= 2:
                return _HierarchyInference(top_pattern=preferred)

        decimal_depths = [
            match.marker_depth
            for match in matches
            if match.pattern_type == PatternType.ARABIC_DECIMAL
        ]
        if decimal_depths and counts[PatternType.ARABIC_DECIMAL] >= 2:
            return _HierarchyInference(
                top_pattern=PatternType.ARABIC_DECIMAL,
                min_decimal_depth=min(decimal_depths),
            )

        top_pattern = counts.most_common(1)[0][0]
        return _HierarchyInference(top_pattern=top_pattern)

    def _suggest_level(
        self, match: PatternMatch, hierarchy: "_HierarchyInference"
    ) -> int | None:

        top = hierarchy.top_pattern

        if match.pattern_type == top:
            if top == PatternType.ARABIC_DECIMAL:
                return max(1, match.marker_depth - hierarchy.min_decimal_depth + 1)
            return 1

        if match.pattern_type == PatternType.CHAPTER:
            return 1

        if match.pattern_type == PatternType.ARABIC_SINGLE:
            return 2 if top in {PatternType.CHAPTER, PatternType.CHINESE_DUN} else 1

        if match.pattern_type == PatternType.ARABIC_DECIMAL:
            if top == PatternType.CHAPTER:
                return min(9, match.marker_depth + 1)
            return min(9, match.marker_depth)

        if match.pattern_type == PatternType.CHINESE_DUN:
            return 2 if top != PatternType.CHINESE_DUN else 1

        if match.pattern_type == PatternType.CHINESE_PAREN:
            return 2 if top == PatternType.CHINESE_DUN else 3

        return None


class _HierarchyInference:

    def __init__(
        self,
        top_pattern: PatternType,
        min_decimal_depth: int = 1,
    ) -> None:
        self.top_pattern = top_pattern
        self.min_decimal_depth = min_decimal_depth
