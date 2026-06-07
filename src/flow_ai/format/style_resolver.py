from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from docx.document import Document as DocumentObject
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Length
from docx.styles.style import _ParagraphStyle, _CharacterStyle
from docx.text.paragraph import Paragraph


ALIGNMENT_TO_VALUE = {
    WD_ALIGN_PARAGRAPH.LEFT: "left",
    WD_ALIGN_PARAGRAPH.CENTER: "center",
    WD_ALIGN_PARAGRAPH.RIGHT: "right",
    WD_ALIGN_PARAGRAPH.JUSTIFY: "justify",
    WD_ALIGN_PARAGRAPH.DISTRIBUTE: "distribute",
}


@dataclass(frozen=True)
class ResolvedStyle:

    intent: dict[str, Any]
    sources: dict[str, str]
    style_chain: list[str]


class WordStyleResolver:

    def __init__(self, document: DocumentObject) -> None:
        self.document = document
        self.default_paragraph_properties = self._doc_default_paragraph_properties()
        self.default_run_properties = self._doc_default_run_properties()

    def resolve_paragraph(self, paragraph: Paragraph) -> ResolvedStyle:
        intent: dict[str, Any] = {}
        sources: dict[str, str] = {}
        style_chain = self._style_chain(paragraph.style)

        self._resolve_paragraph_format(paragraph, intent, sources, style_chain)
        self._resolve_run_format(paragraph, intent, sources, style_chain)
        return ResolvedStyle(
            intent={key: value for key, value in intent.items() if value is not None},
            sources=sources,
            style_chain=[style.name for style in style_chain if style is not None],
        )

    def _resolve_paragraph_format(
        self,
        paragraph: Paragraph,
        intent: dict[str, Any],
        sources: dict[str, str],
        style_chain: list[_ParagraphStyle],
    ) -> None:
        paragraph_format = paragraph.paragraph_format
        style_formats = [style.paragraph_format for style in style_chain]

        alignment = self._first_value(
            [paragraph.alignment]
            + [style_format.alignment for style_format in style_formats],
            self._xml_alignment(self.default_paragraph_properties),
        )
        if alignment in ALIGNMENT_TO_VALUE:
            intent["alignment"] = ALIGNMENT_TO_VALUE[alignment]
            sources["alignment"] = self._source_name(
                paragraph.alignment, "direct paragraph", style_chain, "style/default"
            )

        for field_name, attr_name in (
            ("space_before_pt", "space_before"),
            ("space_after_pt", "space_after"),
            ("first_line_indent_pt", "first_line_indent"),
            ("left_indent_pt", "left_indent"),
            ("right_indent_pt", "right_indent"),
        ):
            value = self._first_value(
                [getattr(paragraph_format, attr_name)]
                + [getattr(style_format, attr_name) for style_format in style_formats],
                self._xml_length(self.default_paragraph_properties, attr_name),
            )
            if value is not None:
                point_value = round(float(value.pt), 2)
                if field_name == "first_line_indent_pt" and point_value < 0:
                    intent["hanging_indent_pt"] = abs(point_value)
                    sources["hanging_indent_pt"] = "paragraph/style/default"
                else:
                    intent[field_name] = point_value
                    sources[field_name] = "paragraph/style/default"

        line_spacing = self._first_value(
            [paragraph_format.line_spacing]
            + [style_format.line_spacing for style_format in style_formats],
            self._xml_line_spacing(self.default_paragraph_properties),
        )
        self._put_line_spacing(intent, sources, line_spacing)

        for field_name, attr_name in (
            ("page_break_before", "page_break_before"),
            ("keep_with_next", "keep_with_next"),
        ):
            value = self._first_value(
                [getattr(paragraph_format, attr_name)]
                + [getattr(style_format, attr_name) for style_format in style_formats],
                self._xml_on_off(self.default_paragraph_properties, attr_name),
            )
            if value is not None:
                intent[field_name] = bool(value)
                sources[field_name] = "paragraph/style/default"

        outline_level = self._first_value(
            [self._xml_outline_level(paragraph._p.pPr)]
            + [self._xml_outline_level(style._element.pPr) for style in style_chain],
            self._xml_outline_level(self.default_paragraph_properties),
        )
        if outline_level is not None:
            intent["outline_level"] = outline_level
            sources["outline_level"] = "paragraph/style/default"

    def _resolve_run_format(
        self,
        paragraph: Paragraph,
        intent: dict[str, Any],
        sources: dict[str, str],
        style_chain: list[_ParagraphStyle],
    ) -> None:
        non_empty_runs = [run for run in paragraph.runs if run.text.strip()]
        paragraph_style_fonts = [style.font for style in style_chain]
        default_fonts = [self.default_run_properties]

        for font_field, attr_name in (
            ("font_name", "name"),
            ("font_size_pt", "size"),
            ("bold", "bold"),
        ):
            values: list[Any] = []
            for run in non_empty_runs:
                values.append(getattr(run.font, attr_name))
                if run.style is not None:
                    values.extend(
                        getattr(style.font, attr_name)
                        for style in self._character_style_chain(run.style)
                    )
            values.extend(getattr(font, attr_name) for font in paragraph_style_fonts)
            values.append(self._xml_run_property(attr_name, default_fonts[0]))

            value = self._most_common_non_none(values)
            if value is None:
                continue
            if font_field == "font_size_pt":
                intent[font_field] = round(float(value.pt), 2)
            else:
                intent[font_field] = bool(value) if font_field == "bold" else value
            sources[font_field] = "run/style/default"

        xml_font_values = self._resolve_xml_fonts(non_empty_runs, style_chain)
        for key, value in xml_font_values.items():
            if value is not None:
                intent[key] = value
                sources[key] = "rFonts inheritance"

        if "east_asia_font" not in intent and "font_name" in intent:
            intent["east_asia_font"] = intent["font_name"]
        if "ascii_font" not in intent and "font_name" in intent:
            intent["ascii_font"] = intent["font_name"]
        if "hansi_font" not in intent and "font_name" in intent:
            intent["hansi_font"] = intent["font_name"]

    def _resolve_xml_fonts(
        self, runs: list[Any], style_chain: list[_ParagraphStyle]
    ) -> dict[str, str | None]:
        buckets: dict[str, list[str | None]] = {
            "east_asia_font": [],
            "ascii_font": [],
            "hansi_font": [],
        }
        xml_attrs = {
            "east_asia_font": "w:eastAsia",
            "ascii_font": "w:ascii",
            "hansi_font": "w:hAnsi",
        }

        for run in runs:
            rpr = run._element.rPr
            r_fonts = rpr.rFonts if rpr is not None else None
            for key, attr in xml_attrs.items():
                buckets[key].append(r_fonts.get(qn(attr)) if r_fonts is not None else None)

        for style in style_chain:
            r_fonts = self._r_fonts(style._element.rPr)
            for key, attr in xml_attrs.items():
                buckets[key].append(r_fonts.get(qn(attr)) if r_fonts is not None else None)

        default_r_fonts = self._r_fonts(self.default_run_properties)
        for key, attr in xml_attrs.items():
            buckets[key].append(
                default_r_fonts.get(qn(attr)) if default_r_fonts is not None else None
            )

        return {key: self._most_common_non_none(values) for key, values in buckets.items()}

    def _style_chain(self, style: Any) -> list[_ParagraphStyle]:
        chain: list[_ParagraphStyle] = []
        while style is not None:
            chain.append(style)
            style = style.base_style
        return chain

    def _character_style_chain(self, style: Any) -> list[_CharacterStyle]:
        chain: list[_CharacterStyle] = []
        while style is not None:
            chain.append(style)
            style = style.base_style
        return chain

    def _doc_default_paragraph_properties(self) -> Any | None:
        doc_defaults = self.document.styles.element.find(qn("w:docDefaults"))
        if doc_defaults is None:
            return None
        paragraph_defaults = doc_defaults.find(qn("w:pPrDefault"))
        if paragraph_defaults is None:
            return None
        return paragraph_defaults.find(qn("w:pPr"))

    def _doc_default_run_properties(self) -> Any | None:
        doc_defaults = self.document.styles.element.find(qn("w:docDefaults"))
        if doc_defaults is None:
            return None
        run_defaults = doc_defaults.find(qn("w:rPrDefault"))
        if run_defaults is None:
            return None
        return run_defaults.find(qn("w:rPr"))

    def _xml_alignment(self, ppr: Any | None) -> WD_ALIGN_PARAGRAPH | None:
        if ppr is None:
            return None
        jc = ppr.find(qn("w:jc"))
        if jc is None:
            return None
        value = jc.get(qn("w:val"))
        reverse = {enum_value.value: enum_value for enum_value in ALIGNMENT_TO_VALUE}
        return reverse.get(value)

    def _xml_length(self, ppr: Any | None, attr_name: str) -> Length | None:
        if ppr is None:
            return None
        spacing = ppr.find(qn("w:spacing"))
        ind = ppr.find(qn("w:ind"))
        attr_map = {
            "space_before": (spacing, "w:before"),
            "space_after": (spacing, "w:after"),
            "first_line_indent": (ind, "w:firstLine"),
            "left_indent": (ind, "w:left"),
            "right_indent": (ind, "w:right"),
        }
        element, attr = attr_map[attr_name]
        if element is None:
            return None
        value = element.get(qn(attr))
        if value is None:
            return None
        return Length(int(value) * 635)

    def _xml_line_spacing(self, ppr: Any | None) -> float | Length | None:
        if ppr is None:
            return None
        spacing = ppr.find(qn("w:spacing"))
        if spacing is None:
            return None
        value = spacing.get(qn("w:line"))
        rule = spacing.get(qn("w:lineRule"))
        if value is None:
            return None
        if rule == "auto" or rule is None:
            return round(int(value) / 240, 3)
        return Length(int(value) * 635)

    def _xml_on_off(self, ppr: Any | None, attr_name: str) -> bool | None:
        if ppr is None:
            return None
        tag = {
            "page_break_before": "w:pageBreakBefore",
            "keep_with_next": "w:keepNext",
        }[attr_name]
        element = ppr.find(qn(tag))
        if element is None:
            return None
        value = element.get(qn("w:val"))
        return value not in {"0", "false", "False"}

    def _xml_outline_level(self, ppr: Any | None) -> int | None:
        if ppr is None:
            return None
        outline = ppr.find(qn("w:outlineLvl"))
        if outline is None:
            return None
        value = outline.get(qn("w:val"))
        return int(value) if value is not None else None

    def _xml_run_property(self, attr_name: str, rpr: Any | None) -> Any | None:
        if rpr is None:
            return None
        if attr_name == "name":
            r_fonts = self._r_fonts(rpr)
            return r_fonts.get(qn("w:ascii")) if r_fonts is not None else None
        if attr_name == "size":
            size = rpr.find(qn("w:sz"))
            value = size.get(qn("w:val")) if size is not None else None
            return Length(int(value) * 6350) if value is not None else None
        if attr_name == "bold":
            bold = rpr.find(qn("w:b"))
            if bold is None:
                return None
            value = bold.get(qn("w:val"))
            return value not in {"0", "false", "False"}
        return None

    def _r_fonts(self, rpr: Any | None) -> Any | None:
        if rpr is None:
            return None
        return rpr.find(qn("w:rFonts"))

    def _put_line_spacing(
        self, intent: dict[str, Any], sources: dict[str, str], value: Any
    ) -> None:
        if value is None:
            return
        if isinstance(value, float):
            intent["line_spacing_multiple"] = round(value, 3)
            sources["line_spacing_multiple"] = "paragraph/style/default"
            return
        if isinstance(value, Length):
            intent["line_spacing_pt"] = round(float(value.pt), 2)
            sources["line_spacing_pt"] = "paragraph/style/default"

    def _first_value(self, values: Iterable[Any], default: Any = None) -> Any:
        for value in values:
            if value is not None:
                return value
        return default

    def _most_common_non_none(self, values: Iterable[Any]) -> Any:
        counts: dict[Any, int] = {}
        for value in values:
            if value is None:
                continue
            counts[value] = counts.get(value, 0) + 1
        if not counts:
            return None
        return max(counts, key=counts.get)

    def _source_name(
        self,
        direct_value: Any,
        direct_name: str,
        style_chain: list[_ParagraphStyle],
        fallback_name: str,
    ) -> str:
        if direct_value is not None:
            return direct_name
        if style_chain:
            return " -> ".join(style.name for style in style_chain)
        return fallback_name
