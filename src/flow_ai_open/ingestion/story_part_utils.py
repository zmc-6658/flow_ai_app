"""Resolve OOXML story parts (header/footer/footnotes) for python-docx Paragraph parents."""
from __future__ import annotations

from docx import Document
from docx.oxml.ns import qn
from docx.parts.story import StoryPart

FOOTNOTES_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/footnotes"
)
ENDNOTES_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/endnotes"
)


def normalize_part_path(part_path: str) -> str:
    path = part_path.replace("\\", "/")
    if not path.startswith("/"):
        path = f"/{path}"
    return path


def part_for_path(document: Document, part_path: str) -> StoryPart | None:
    target = normalize_part_path(part_path)
    for part in document.part.package.iter_parts():
        if str(part.partname).replace("\\", "/") == target:
            if isinstance(part, StoryPart):
                return part
            return part  # HeaderPart/FooterPart/FootnotesPart subclass StoryPart
    return None


def footnotes_part(document: Document) -> StoryPart | None:
    return _related_story_part(document, FOOTNOTES_REL)


def endnotes_part(document: Document) -> StoryPart | None:
    return _related_story_part(document, ENDNOTES_REL)


def _related_story_part(document: Document, reltype: str) -> StoryPart | None:
    try:
        part = document.part.part_related_by(reltype)
    except KeyError:
        return None
    return part
