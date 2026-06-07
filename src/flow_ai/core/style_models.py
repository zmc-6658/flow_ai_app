from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from flow_ai.core.enums import DocumentRegion
from flow_ai.core.ast_models import OpaqueType, SemanticRole, StrictASTModel, TextAlignment


class StyleIntent(StrictASTModel):

    font_name: str | None = Field(default=None)
    east_asia_font: str | None = Field(default=None)
    ascii_font: str | None = Field(default=None)
    hansi_font: str | None = Field(default=None)
    font_size_pt: float | None = Field(default=None, gt=0, le=72)
    bold: bool | None = Field(default=None)
    alignment: TextAlignment | None = Field(default=None)
    space_before_pt: float | None = Field(default=None, ge=0)
    space_after_pt: float | None = Field(default=None, ge=0)
    first_line_indent_pt: float | None = Field(default=None)
    hanging_indent_pt: float | None = Field(default=None, ge=0)
    left_indent_pt: float | None = Field(default=None)
    right_indent_pt: float | None = Field(default=None)
    line_spacing: float | None = Field(default=None, gt=0)
    line_spacing_multiple: float | None = Field(default=None, gt=0)
    line_spacing_pt: float | None = Field(default=None, gt=0)
    page_break_before: bool | None = Field(default=None)
    keep_with_next: bool | None = Field(default=None)
    style_name: str | None = Field(
        default=None,
        description="Renderer-created paragraph style name, never a template dependency.",
    )
    outline_level: int | None = Field(
        default=None,
        ge=0,
        le=8,
        description="Word outline level where 0 means level-1 heading.",
    )
    generated_anchor_type: str | None = Field(
        default=None,
        description="Virtual renderer action such as generating a table of contents.",
    )
    generated_anchor_text: str | None = Field(default=None)
    opaque_placeholder_text: str | None = Field(default=None)

    def merge(self, other: "StyleIntent") -> "StyleIntent":

        merged = self.model_dump()
        merged.update(other.model_dump(exclude_none=True))
        return StyleIntent.model_validate(merged)


class RuleSelector(StrictASTModel):

    node_kind: str | None = Field(default=None)
    semantic_role: SemanticRole | None = Field(default=None)
    level: int | None = Field(default=None, ge=1, le=9)
    region: DocumentRegion | None = Field(default=None)
    anchor_type: str | None = Field(default=None)
    opaque_type: OpaqueType | None = Field(default=None)

    def matches(self, context: dict[str, Any]) -> bool:

        for field_name, expected in self.model_dump(exclude_none=True).items():
            if context.get(field_name) != expected:
                return False
        return True


class RuleNode(StrictASTModel):

    id: str = Field(min_length=1, description="Stable rule identifier for tracing.")
    selector: RuleSelector = Field(default_factory=RuleSelector)
    apply: StyleIntent
    priority: int = Field(
        default=0,
        description="Higher priority rules override lower priority intent fields.",
    )

    @field_validator("id")
    @classmethod
    def id_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("RuleNode.id 不能为空")
        return value


class RenderPlan(StrictASTModel):

    node_styles: dict[str, StyleIntent] = Field(default_factory=dict)
    rule_trace: dict[str, list[str]] = Field(default_factory=dict)
