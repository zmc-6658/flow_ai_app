"""Pass 4: context stack injection and content tree builder."""

from __future__ import annotations

from dataclasses import dataclass, field

from flow_ai.classifier.pipeline_models import AnnotatedParagraph
from flow_ai.contracts.classification_contracts import (
    ContentNode,
    DocumentContentTree,
    LeafRef,
)
from flow_ai.core.ast_models import SemanticRole
from flow_ai.core.enums import DocumentRegion

INJECTION_MAP: dict[str, tuple[str, SemanticRole]] = {
    "FRONT_MATTER": ("ABSTRACT_BODY", SemanticRole.ABSTRACT_BODY),
    "CHAPTER": ("CHAPTER_BODY", SemanticRole.BODY),
    "SECTION": ("SECTION_BODY", SemanticRole.BODY),
    "ROOT": ("FRONT_MATTER_BODY", SemanticRole.BODY),
}

ANCHOR_ROLES = {
    "ABSTRACT_ANCHOR",
    "TOC_ANCHOR",
    "REFERENCES_ANCHOR",
    "ACK_ANCHOR",
    "APPENDIX_ANCHOR",
    "BACK_ANCHOR",
}

HEADING_ROLES = {"HEADING_1", "HEADING_2", "HEADING_3", "HEADING_4", "SUSPECTED_HEADING"}


@dataclass
class StackFrame:
    role: str
    heading_level: float
    anchor_id: str
    anchor_confidence: float
    section_label: str
    paragraphs_since_anchor: int = 0


class ContextStack:
    def __init__(self) -> None:
        self._stack: list[StackFrame] = [
            StackFrame("ROOT", 0, "ROOT", 1.0, "ROOT"),
        ]
        self._tree_root: list[ContentNode] = []
        self._current_chapter: ContentNode | None = None
        self._current_section: ContentNode | None = None

    @property
    def breadcrumb(self) -> list[str]:
        return [frame.section_label for frame in self._stack]

    @property
    def section_path(self) -> str:
        return "/".join(self.breadcrumb)

    def process(self, para: AnnotatedParagraph) -> None:
        if para.hygiene.skip_classification and para.resolved_role != "TOC_ENTRY":
            return

        role = para.resolved_role
        if role in ANCHOR_ROLES or role in HEADING_ROLES:
            self._push_anchor(para, role)
            para.breadcrumb = list(self.breadcrumb)
            para.section_path = self.section_path
            if self._stack:
                self._stack[-1].paragraphs_since_anchor = 0
            return

        if role is None:
            self._inject(para)

        para.breadcrumb = list(self.breadcrumb)
        para.section_path = self.section_path
        if self._stack:
            self._stack[-1].paragraphs_since_anchor += 1

    def _push_anchor(self, para: AnnotatedParagraph, role: str) -> None:
        level = self._anchor_level(role, para.resolved_level)
        frame_role = self._frame_role(role)

        if frame_role == "FRONT_MATTER":
            self._stack = [self._stack[0]]
        else:
            while len(self._stack) > 1 and self._stack[-1].heading_level >= level:
                self._stack.pop()

        label = self._section_label(role, para.text)
        self._stack.append(
            StackFrame(
                role=frame_role,
                heading_level=level,
                anchor_id=para.node_id,
                anchor_confidence=para.confidence,
                section_label=label,
            )
        )
        self._update_tree(para, role, level, label)

    def _inject(self, para: AnnotatedParagraph) -> None:
        top = self._stack[-1]
        injected_role, sem = INJECTION_MAP.get(top.role, ("BODY", SemanticRole.BODY))

        if top.role == "CHAPTER" and top.paragraphs_since_anchor == 0:
            if 50 <= para.text_length <= 300:
                injected_role = "CHAPTER_INTRO"
                sem = SemanticRole.BODY

        decay = 0.02 * min(top.paragraphs_since_anchor, 10)
        conf = max(top.anchor_confidence - decay, 0.60)

        para.resolved_role = injected_role
        para.semantic_role = sem
        para.confidence = conf
        para.source = "stack_injection"
        para.reason_text = f"栈顶 {top.section_label} 区间灌注"

        if top.role == "ROOT":
            para.region = DocumentRegion.FRONT
        elif top.role == "FRONT_MATTER":
            para.region = DocumentRegion.FRONT
        else:
            para.region = DocumentRegion.BODY

    def _anchor_level(self, role: str, resolved_level: int | None) -> float:
        if role in ANCHOR_ROLES:
            return 0.5
        if role == "HEADING_1" or role == "SUSPECTED_HEADING" and resolved_level == 1:
            return 1.0
        if role == "HEADING_2" or resolved_level == 2:
            return 2.0
        if role == "HEADING_3" or resolved_level == 3:
            return 3.0
        if role == "HEADING_4" or resolved_level == 4:
            return 4.0
        return float(resolved_level or 2)

    def _frame_role(self, role: str) -> str:
        if role in ANCHOR_ROLES:
            return "FRONT_MATTER"
        if role.startswith("HEADING_1") or role == "SUSPECTED_HEADING":
            return "CHAPTER"
        if role.startswith("HEADING_"):
            return "SECTION"
        return "CHAPTER"

    def _section_label(self, role: str, text: str) -> str:
        snippet = text.strip()[:12].replace(" ", "")
        if role.startswith("HEADING"):
            return f"H{role.split('_')[-1]}_{snippet}"
        return f"SEC_{snippet}"

    def _update_tree(
        self,
        para: AnnotatedParagraph,
        role: str,
        level: float,
        label: str,
    ) -> None:
        node_type = "front_matter" if role in ANCHOR_ROLES else "chapter" if level <= 1 else "section"
        node = ContentNode(
            node_type=node_type,
            heading_para_id=para.node_id,
            heading_level=int(level) if level >= 1 else 0,
            section_path=self.section_path,
            children=[],
        )
        if level <= 1 or role in ANCHOR_ROLES:
            self._tree_root.append(node)
            self._current_chapter = node
            self._current_section = None
        elif self._current_chapter is not None:
            self._current_chapter.children.append(node)
            self._current_section = node
        else:
            self._tree_root.append(node)

    def build_tree(self, paragraphs: list[AnnotatedParagraph]) -> DocumentContentTree:
        for para in paragraphs:
            if para.resolved_role and para.resolved_role not in HEADING_ROLES | ANCHOR_ROLES | {"TOC_ENTRY"}:
                leaf = LeafRef(para_id=para.node_id, injected_role=para.resolved_role, confidence=para.confidence)
                if self._current_section is not None:
                    self._current_section.children.append(leaf)
                elif self._current_chapter is not None:
                    self._current_chapter.children.append(leaf)
        return DocumentContentTree(root=self._tree_root)
