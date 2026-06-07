from __future__ import annotations

from pathlib import Path
from typing import Any

from flow_ai.contracts.format_catalog import FormatCatalog, FormatSlotEntry
from flow_ai.format.knowledge_base import KnowledgeBase
from flow_ai_open.adapters.core_adapter import CoreAdapter
from flow_ai_open.ingestion.docx_parser import DocxParser

_shared_kb: KnowledgeBase | None = None


def _get_kb() -> KnowledgeBase:
    global _shared_kb
    if _shared_kb is None:
        _shared_kb = KnowledgeBase()
    return _shared_kb


def extract_format_catalog(
    template_path: str | Path,
    expected_catalog_path: str | Path | None = None,
    use_knowledge_base: bool = True,
) -> FormatCatalog:
    path = Path(template_path)
    ast, _ = DocxParser().parse_with_assets(path)
    adapter = CoreAdapter()
    kb = _get_kb() if use_knowledge_base else None
    return adapter.extract_format_catalog(
        ast,
        template_path=path,
        expected_catalog_path=expected_catalog_path,
        knowledge_base=kb,
    )


def catalog_to_rule_definitions(catalog: FormatCatalog) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    for slot in catalog.slots:
        rule: dict[str, Any] = {
            "id": slot.slot_id,
            "selector": _slot_selector(slot.slot_id, slot.region),
            "apply": slot.style_intent.model_dump(mode="json", exclude_none=True),
            "priority": _slot_priority(slot),
        }
        rules.append(rule)
    return rules


def catalog_to_profile_entries(catalog: FormatCatalog) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for slot in catalog.slots:
        entry: dict[str, Any] = {
            "id": slot.slot_id,
            "label": slot.label,
            "description": slot.description,
            "selector": {"format_slot_id": slot.slot_id},
            "intent": slot.style_intent.model_dump(mode="json", exclude_none=True),
            "readable": _readable_from_intent(slot),
            "sample": {
                "text": slot.sample_texts[0] if slot.sample_texts else "",
                "node_ids": slot.sample_node_ids,
            },
            "confidence": slot.confidence,
            "evidence": slot.evidence,
            "cluster_id": slot.cluster_id,
            "source": slot.source,
        }
        if slot.is_complex_layout:
            entry["is_complex_layout"] = True
        if slot.render_hint:
            entry["render_hint"] = slot.render_hint
        entries.append(entry)
    return entries


def _readable_from_intent(slot: FormatSlotEntry) -> list[str]:
    intent = slot.style_intent
    readable: list[str] = []
    if intent.alignment:
        readable.append(f"对齐: {intent.alignment.value}")
    if intent.font_size_pt:
        readable.append(f"字号: {intent.font_size_pt}pt")
    if intent.bold is True:
        readable.append("加粗")
    if intent.line_spacing_multiple:
        readable.append(f"行距: {intent.line_spacing_multiple}倍")
    if intent.east_asia_font or intent.font_name:
        readable.append(f"字体: {intent.east_asia_font or intent.font_name}")
    return readable or [slot.description or slot.label]


def _slot_to_semantic_role(slot_id: str) -> str | None:
    mapping = {
        "abstract_heading": "abstract",
        "abstract_body": "abstract_body",
        "abstract_keywords": "keywords",
        "abstract_heading_en": "abstract_body_en",
        "abstract_body_en": "abstract_body_en",
        "abstract_keywords_en": "keywords_en",
        "toc_heading": "toc",
        "toc_entry": "toc_entry",
        "heading_1": "standard",
        "heading_2": "standard",
        "heading_3": "standard",
        "body": "body",
        "caption": "figure_caption",
        "references_heading": "references",
        "references_item": "references_item",
        "acknowledgment_heading": "acknowledgment",
        "acknowledgment_body": "acknowledgment_body",
        "cover_title": "title_cn",
    }
    return mapping.get(slot_id)


def _slot_selector(slot_id: str, region: str) -> dict[str, Any]:
    selector: dict[str, Any] = {}
    semantic = _slot_to_semantic_role(slot_id)
    if semantic is not None:
        selector["semantic_role"] = semantic
    if region == "body":
        selector["region"] = "body"
    if slot_id.startswith("heading_"):
        try:
            selector["level"] = int(slot_id.split("_")[1])
        except (IndexError, ValueError):
            pass
    return selector


def _slot_priority(slot: FormatSlotEntry) -> int:
    if slot.slot_id.startswith("heading"):
        return 10
    if slot.slot_id.startswith("cover"):
        return 8
    return 5
