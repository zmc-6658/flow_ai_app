from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from flow_ai.core.ast_models import TextAlignment
from flow_ai.core.style_models import StyleIntent

from flow_ai.contracts.format_catalog import (
    COMPLEX_LAYOUT_SLOTS,
    ExpectedCatalog,
    FormatCatalog,
    FormatSlotEntry,
    RENDER_HINTS,
    SectionRule,
)
from flow_ai.format.ast_intent_builder import IntentBuildContext, build_style_intent
from flow_ai.format.ast_reader import ParagraphRecord, TemplateReadResult
from flow_ai.format.format_clusterer import FormatCluster, cluster_for_record, cluster_paragraphs
from flow_ai.format.knowledge_base import KnowledgeBase
from flow_ai.format.semantic_anchor import (
    COVER_DOC_TYPE_RE,
    COVER_FOOTER_DATE_RE,
    COVER_INFO_RE,
    COVER_SCHOOL_RE,
    COVER_TITLE_RE,
    AnchorState,
    DocumentSection,
    annotate_sections,
    section_for_record,
)
from flow_ai.format.visual_fingerprint import (
    build_fingerprint,
    effective_alignment,
    fingerprint_key,
    guess_heading_level,
)
from flow_ai.format.visual_weight import compute_visual_weight

_MIN_DISCOVERED_MEMBERS = 3

H1_RE = re.compile(
    r"^(第[一二三四五六七八九十\d]+[章节篇]|[12]\s+[\u4e00-\u9fff]|\d+\s+[\u4e00-\u9fff])"
)
H2_RE = re.compile(r"^\d+\.\d+\s+\S")
H3_RE = re.compile(r"^\d+\.\d+\.\d+")
CAPTION_RE = re.compile(r"^(图|表)\s*\d")
REFERENCE_ITEM_RE = re.compile(r"^(\[\d+\]|［\d+］|\d+[.．、]\s*)")
LATIN_TERM_RE = re.compile(r"\b[A-Za-z]{2,}\b")


@dataclass(frozen=True)
class SlotSpec:

    slot_id: str
    label: str
    region: str
    notes: str
    matcher: Callable[[ParagraphRecord, AnchorState, list[ParagraphRecord]], bool]


def _default_slot_specs() -> list[SlotSpec]:
    return [
        SlotSpec(
            "cover_school_name",
            "封面-校名",
            "body",
            "校名居中",
            lambda r, s, ps: section_for_record(s, r, ps) == DocumentSection.COVER
            and COVER_SCHOOL_RE.search(r.text) is not None
            and "毕业论文" not in r.text
            and effective_alignment(r) == TextAlignment.CENTER,
        ),
        SlotSpec(
            "cover_doc_type",
            "封面-论文类型",
            "body",
            "论文类型",
            lambda r, s, ps: section_for_record(s, r, ps) == DocumentSection.COVER
            and COVER_DOC_TYPE_RE.search(r.text) is not None,
        ),
        SlotSpec(
            "cover_title",
            "封面-论文标题",
            "body",
            "论文题目",
            lambda r, s, ps: section_for_record(s, r, ps) == DocumentSection.COVER
            and (COVER_TITLE_RE.match(r.text) is not None or "论文题目" in r.text),
        ),
        SlotSpec(
            "cover_info_row",
            "封面-信息行",
            "body",
            "封面表单行",
            lambda r, s, ps: section_for_record(s, r, ps) == DocumentSection.COVER
            and COVER_INFO_RE.match(r.text) is not None,
        ),
        SlotSpec(
            "cover_footer",
            "封面-底部信息",
            "body",
            "底部院系日期",
            lambda r, s, ps: section_for_record(s, r, ps) == DocumentSection.COVER
            and (
                COVER_FOOTER_DATE_RE.search(r.text) is not None
                or ("系" in r.text and "学院" in r.text)
            ),
        ),
        SlotSpec(
            "abstract_heading",
            "摘要-大标题",
            "body",
            "摘要标题",
            lambda r, s, ps: re.match(r"^摘\s*要$", re.sub(r"\s+", "", r.text)) is not None,
        ),
        SlotSpec(
            "abstract_body",
            "摘要-正文",
            "body",
            "摘要正文",
            lambda r, s, ps: _in_abstract_cn_body(r, s, ps),
        ),
        SlotSpec(
            "abstract_keywords",
            "摘要-关键词行",
            "body",
            "关键词",
            lambda r, s, ps: r.text.strip().startswith("关键词"),
        ),
        SlotSpec(
            "abstract_heading_en",
            "英文摘要-标题",
            "body",
            "ABSTRACT",
            lambda r, s, ps: r.text.strip().upper() == "ABSTRACT",
        ),
        SlotSpec(
            "abstract_body_en",
            "英文摘要-正文",
            "body",
            "英文摘要正文",
            lambda r, s, ps: _in_abstract_en_body(r, s, ps),
        ),
        SlotSpec(
            "abstract_keywords_en",
            "英文摘要-关键词行",
            "body",
            "KEY WORDS",
            lambda r, s, ps: r.text.strip().upper().startswith("KEY WORDS"),
        ),
        SlotSpec(
            "toc_heading",
            "目录-标题",
            "body",
            "目录",
            lambda r, s, ps: re.match(r"^目\s*录$", re.sub(r"\s+", "", r.text)) is not None,
        ),
        SlotSpec(
            "toc_entry",
            "目录-条目",
            "body",
            "目录行",
            lambda r, s, ps: section_for_record(s, r, ps) == DocumentSection.TOC
            and not re.match(r"^目\s*录$", re.sub(r"\s+", "", r.text))
            and len(r.text) <= 120
            and re.search(r"\d+\s*$", r.text) is not None,
        ),
        SlotSpec(
            "heading_1",
            "一级标题",
            "body",
            "章标题",
            lambda r, s, ps: section_for_record(s, r, ps) == DocumentSection.BODY
            and (guess_heading_level(r.text) == 1 or bool(H1_RE.match(r.text))),
        ),
        SlotSpec(
            "heading_2",
            "二级标题",
            "body",
            "节标题",
            lambda r, s, ps: section_for_record(s, r, ps) == DocumentSection.BODY
            and (guess_heading_level(r.text) == 2 or bool(H2_RE.match(r.text))),
        ),
        SlotSpec(
            "heading_3",
            "三级标题",
            "body",
            "小节标题",
            lambda r, s, ps: section_for_record(s, r, ps) == DocumentSection.BODY
            and (guess_heading_level(r.text) == 3 or bool(H3_RE.match(r.text))),
        ),
        SlotSpec(
            "body",
            "正文",
            "body",
            "正文",
            lambda r, s, ps: section_for_record(s, r, ps) == DocumentSection.BODY
            and len(r.text) >= 40
            and guess_heading_level(r.text) is None
            and not CAPTION_RE.match(r.text),
        ),
        SlotSpec(
            "caption",
            "图表-说明文字",
            "body",
            "图题表题",
            lambda r, s, ps: CAPTION_RE.match(r.text.strip()) is not None,
        ),
        SlotSpec(
            "references_heading",
            "参考文献-大标题",
            "body",
            "参考文献标题",
            lambda r, s, ps: re.match(r"^参\s*考\s*文\s*献$", re.sub(r"\s+", "", r.text)) is not None,
        ),
        SlotSpec(
            "references_item",
            "参考文献-条目",
            "body",
            "参考文献条目",
            lambda r, s, ps: _is_reference_item(r, s, ps),
        ),
        SlotSpec(
            "acknowledgment_heading",
            "致谢-标题",
            "body",
            "致谢标题",
            lambda r, s, ps: re.match(r"^致\s*谢$", re.sub(r"\s+", "", r.text)) is not None,
        ),
        SlotSpec(
            "acknowledgment_body",
            "致谢-正文",
            "body",
            "致谢正文",
            lambda r, s, ps: _in_acknowledgment_body(r, s, ps),
        ),
        SlotSpec(
            "run_latin_terms",
            "英文/拉丁术语",
            "body",
            "段内英文",
            lambda r, s, ps: LATIN_TERM_RE.search(r.text) is not None
            and section_for_record(s, r, ps) == DocumentSection.BODY
            and len(r.text) >= 20,
        ),
    ]


def _is_reference_item(
    record: ParagraphRecord,
    state: AnchorState,
    paragraphs: list[ParagraphRecord],
) -> bool:
    if section_for_record(state, record, paragraphs) != DocumentSection.BACK_MATTER:
        return False
    ref_start = state.anchor_hits.get("references")
    ack_start = state.anchor_hits.get("acknowledgment")
    if ref_start is None:
        return False
    try:
        index = paragraphs.index(record)
    except ValueError:
        return False
    if index <= ref_start:
        return False
    if ack_start is not None and index >= ack_start:
        return False
    text = record.text.strip()
    if len(text) < 15:
        return False
    if REFERENCE_ITEM_RE.match(text):
        return True
    if re.search(r"\[[JDM]\]|\[EB/OL\]|\[DB/OL\]", text):
        return True
    return bool(re.search(r"\d{4}", text) and re.search(r"[\u4e00-\u9fffA-Za-z]", text))


def _in_abstract_cn_body(
    record: ParagraphRecord,
    state: AnchorState,
    paragraphs: list[ParagraphRecord],
) -> bool:
    start = state.anchor_hits.get("abstract_cn")
    end = state.anchor_hits.get("abstract_en", state.anchor_hits.get("toc", len(paragraphs)))
    if start is None:
        return False
    try:
        index = paragraphs.index(record)
    except ValueError:
        return False
    if index <= start:
        return False
    if index >= end:
        return False
    if record.text.startswith("关键词"):
        return False
    return len(record.text) >= 20 and re.search(r"[\u4e00-\u9fff]", record.text) is not None


def _in_abstract_en_body(
    record: ParagraphRecord,
    state: AnchorState,
    paragraphs: list[ParagraphRecord],
) -> bool:
    start = state.anchor_hits.get("abstract_en")
    end = state.anchor_hits.get("toc", len(paragraphs))
    if start is None:
        return False
    try:
        index = paragraphs.index(record)
    except ValueError:
        return False
    if index <= start:
        return False
    if index >= end:
        return False
    if record.text.upper().startswith("KEY WORDS"):
        return False
    return len(record.text) >= 20 and re.search(r"[A-Za-z]", record.text) is not None


def _in_acknowledgment_body(
    record: ParagraphRecord,
    state: AnchorState,
    paragraphs: list[ParagraphRecord],
) -> bool:
    start = state.anchor_hits.get("acknowledgment")
    if start is None:
        return False
    try:
        index = paragraphs.index(record)
    except ValueError:
        return False
    if index <= start:
        return False
    return len(record.text) >= 20 and not re.match(r"^致\s*谢$", re.sub(r"\s+", "", record.text))


def load_expected_catalog(path: Path) -> ExpectedCatalog:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ExpectedCatalog.model_validate(data)


def align_slots(
    read_result: TemplateReadResult,
    intent_context: IntentBuildContext | None,
    expected: ExpectedCatalog | None = None,
    knowledge_base: KnowledgeBase | None = None,
) -> FormatCatalog:
    paragraphs = read_result.paragraphs
    anchor_state = annotate_sections(paragraphs)
    clusters = cluster_paragraphs(paragraphs, intent_context)

    specs = _slot_specs_from_expected(expected) if expected else _default_slot_specs()
    slot_entries: list[FormatSlotEntry] = []
    cluster_members: dict[str, list[str]] = {c.cluster_id: [m.node_id for m in c.members] for c in clusters}

    # Track which cluster_ids have been assigned a slot, for open-set discovery
    assigned_cluster_ids: set[str] = set()

    for spec in specs:
        matched = [r for r in paragraphs if spec.matcher(r, anchor_state, paragraphs)]
        if not matched:
            entry = _empty_slot_entry(spec, expected)
            if entry is not None:
                slot_entries.append(entry)
            continue

        representative = _pick_slot_representative(matched, spec.slot_id)
        cluster = cluster_for_record(representative, clusters, intent_context)
        intent = build_style_intent(representative, intent_context)

        # Knowledge-base pre-query: if we have a high-confidence historical match, boost
        kb_slot_id: str | None = None
        kb_confidence: float | None = None
        if knowledge_base is not None:
            rep_fp_key = fingerprint_key(build_fingerprint(representative, intent))
            rep_section = section_for_record(anchor_state, representative, paragraphs).value
            kb_hit = knowledge_base.lookup(rep_fp_key, rep_section)
            if kb_hit is not None:
                kb_slot_id, kb_confidence = kb_hit

        if cluster and cluster.style_intent:
            intent = StyleIntent.model_validate(
                {**cluster.style_intent.model_dump(), **intent.model_dump(exclude_none=True)}
            )

        is_complex = spec.slot_id in COMPLEX_LAYOUT_SLOTS
        if expected:
            for slot in expected.format_slots:
                if slot.slot_id == spec.slot_id:
                    is_complex = slot.is_complex_layout

        matcher_confidence = min(1.0, 0.4 + 0.1 * len(matched))
        effective_confidence = max(matcher_confidence, kb_confidence or 0.0)
        evidence: list[str] = [
            f"matched={len(matched)}",
            f"section={section_for_record(anchor_state, representative, paragraphs).value}",
        ]
        if kb_confidence is not None:
            evidence.append(f"kb_confidence={kb_confidence:.2f}")

        slot_entries.append(
            FormatSlotEntry(
                slot_id=spec.slot_id,
                label=spec.label,
                region=spec.region,
                description=spec.notes,
                style_intent=intent,
                sample_node_ids=[r.node_id for r in matched[:5]],
                sample_texts=[r.text[:120] for r in matched[:3]],
                cluster_id=cluster.cluster_id if cluster else None,
                confidence=effective_confidence,
                evidence=evidence,
                is_complex_layout=is_complex,
                render_hint=RENDER_HINTS.get(spec.slot_id) if is_complex else None,
                source="kb+anchor" if kb_confidence is not None else "fingerprint+anchor",
            )
        )

        if cluster:
            assigned_cluster_ids.add(cluster.cluster_id)

    # Open-set discovery: clusters with enough members that were not matched by any spec
    for cluster in clusters:
        if cluster.cluster_id in assigned_cluster_ids:
            continue
        if len(cluster.members) < _MIN_DISCOVERED_MEMBERS:
            continue
        representative = cluster.representative
        if representative is None:
            continue

        intent = build_style_intent(representative, intent_context)
        if cluster.style_intent:
            intent = cluster.style_intent

        # Check knowledge base for this unknown cluster before labeling as discovered
        kb_slot_id_disc: str | None = None
        kb_confidence_disc: float | None = None
        if knowledge_base is not None:
            rep_fp_key = fingerprint_key(build_fingerprint(representative, intent))
            rep_section = section_for_record(anchor_state, representative, paragraphs).value
            kb_hit = knowledge_base.lookup(rep_fp_key, rep_section)
            if kb_hit is not None:
                kb_slot_id_disc, kb_confidence_disc = kb_hit

        disc_slot_id = kb_slot_id_disc if kb_slot_id_disc else f"discovered_{cluster.cluster_id[:8]}"
        disc_label = kb_slot_id_disc if kb_slot_id_disc else f"待确认 ({cluster.cluster_id[:8]})"
        disc_confidence = kb_confidence_disc if kb_confidence_disc is not None else 0.3

        slot_entries.append(
            FormatSlotEntry(
                slot_id=disc_slot_id,
                label=disc_label,
                region=representative.region,
                description="开放集聚类发现",
                style_intent=intent,
                sample_node_ids=[m.node_id for m in cluster.members[:5]],
                sample_texts=[m.text[:120] for m in cluster.members[:3]],
                cluster_id=cluster.cluster_id,
                confidence=disc_confidence,
                evidence=[
                    f"members={len(cluster.members)}",
                    f"section={section_for_record(anchor_state, representative, paragraphs).value}",
                    "source=cluster_discovered",
                ],
                source="cluster_discovered",
            )
        )

    def _sort_key(entry: FormatSlotEntry) -> float:
        record = _first_matching(paragraphs, entry.sample_node_ids)
        if record is None:
            return 0.0
        return compute_visual_weight(
            record,
            record.block_index,
            section_for_record(anchor_state, record, paragraphs),
        )

    slot_entries.sort(key=_sort_key, reverse=True)

    section_rules: list[SectionRule] = []
    if expected:
        section_rules = list(expected.section_rules)

    opaque_slots: list[str] = []
    for block in read_result.opaque_blocks:
        preview = (block.text_preview or "").lower()
        if "toc" in preview or block.opaque_type.value == "field":
            opaque_slots.append("toc_entry")

    return FormatCatalog(
        source_path=str(read_result.ast.metadata.get("source_path", "")),
        slots=slot_entries,
        clusters=cluster_members,
        section_rules=section_rules,
        opaque_slots=opaque_slots,
    )


def _slot_specs_from_expected(expected: ExpectedCatalog) -> list[SlotSpec]:
    defaults = {spec.slot_id: spec for spec in _default_slot_specs()}
    specs: list[SlotSpec] = []
    for slot in expected.format_slots:
        base = defaults.get(slot.slot_id)
        if base is None:
            continue
        specs.append(
            SlotSpec(
                slot_id=slot.slot_id,
                label=slot.label,
                region=slot.region,
                notes=slot.notes,
                matcher=base.matcher,
            )
        )
    return specs


def _pick_slot_representative(matched: list[ParagraphRecord], slot_id: str) -> ParagraphRecord:
    if slot_id == "body":
        return max(matched, key=lambda r: r.features.text_length)
    if slot_id in {"heading_1", "heading_2", "heading_3"}:
        return matched[0]
    if slot_id == "cover_info_row":
        return matched[0]
    return max(
        matched,
        key=lambda r: (r.features.dominant_font_size or 0.0, r.features.text_length),
    )


def _empty_slot_entry(spec: SlotSpec, expected: ExpectedCatalog | None) -> FormatSlotEntry | None:
    if spec.slot_id == "toc_entry":
        return FormatSlotEntry(
            slot_id=spec.slot_id,
            label=spec.label,
            region=spec.region,
            description=spec.notes,
            style_intent=StyleIntent(),
            confidence=0.2,
            evidence=["no_paragraph_match; toc may be field/opaque"],
            source="opaque",
        )
    return FormatSlotEntry(
        slot_id=spec.slot_id,
        label=spec.label,
        region=spec.region,
        description=spec.notes,
        style_intent=StyleIntent(),
        confidence=0.0,
        evidence=["no_match"],
        source="missing",
    )


def _first_matching(
    paragraphs: list[ParagraphRecord],
    node_ids: list[str],
) -> ParagraphRecord | None:
    id_set = set(node_ids)
    for record in paragraphs:
        if record.node_id in id_set:
            return record
    return None
