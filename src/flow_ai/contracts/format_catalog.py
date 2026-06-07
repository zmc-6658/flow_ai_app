from __future__ import annotations

from flow_ai.core.ast_models import StrictASTModel
from flow_ai.core.style_models import StyleIntent


COMPLEX_LAYOUT_SLOTS: frozenset[str] = frozenset({"cover_info_row"})

RENDER_HINTS: dict[str, str] = {
    "cover_info_row": "cover_info_row_template",
}


class ExpectedFormatSlot(StrictASTModel):

    slot_id: str
    label: str
    region: str
    notes: str
    is_complex_layout: bool = False
    render_hint: str | None = None


class SectionRule(StrictASTModel):

    rule_id: str
    notes: str


class ExpectedCatalog(StrictASTModel):

    source_docx: str
    format_slots: list[ExpectedFormatSlot]
    section_rules: list[SectionRule] = []


class FormatSlotEntry(StrictASTModel):

    slot_id: str
    label: str
    region: str
    description: str = ""
    style_intent: StyleIntent
    sample_node_ids: list[str] = []
    sample_texts: list[str] = []
    cluster_id: str | None = None
    confidence: float = 0.0
    evidence: list[str] = []
    is_complex_layout: bool = False
    render_hint: str | None = None
    source: str = "fingerprint"


class FormatCatalog(StrictASTModel):

    source_path: str
    slots: list[FormatSlotEntry]
    clusters: dict[str, list[str]] = {}
    section_rules: list[SectionRule] = []
    opaque_slots: list[str] = []

    def slot_by_id(self, slot_id: str) -> FormatSlotEntry | None:
        for slot in self.slots:
            if slot.slot_id == slot_id:
                return slot
        return None

    def slot_ids(self) -> set[str]:
        return {slot.slot_id for slot in self.slots}
