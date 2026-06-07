"""Extract visible body text from document.xml per D2/D4 (exclude table cells, w:delText)."""
from __future__ import annotations

from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}

TEXTBOX_LOCALS = frozenset({"txbxContent"})


def _tag(local: str) -> str:
    return f"{{{W_NS}}}{local}"


def _local_name(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _contains_textbox(element: ET.Element) -> bool:
    for node in element.iter():
        local = _local_name(node.tag)
        if local in TEXTBOX_LOCALS or local == "textbox":
            return True
    return False


def _append_special_char(local: str, elem: ET.Element, parts: list[str]) -> None:
    if local in ("noBreakHyphen", "softHyphen"):
        parts.append("-")
    elif local == "sym":
        char = elem.get(f"{{{W_NS}}}char") or elem.get("w:char")
        if char:
            try:
                parts.append(chr(int(char, 16)))
            except ValueError:
                pass
    elif local == "footnoteRef":
        parts.append("")


def _paragraph_visible_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for elem in paragraph.iter():
        local = _local_name(elem.tag)
        if local == "t" and elem.text:
            parts.append(elem.text)
        elif local in ("tab", "ptab"):
            parts.append(" ")
        elif local in ("br", "cr"):
            parts.append("\n")
        else:
            _append_special_char(local, elem, parts)
    return "".join(parts)


def paragraph_visible_text(paragraph: ET.Element) -> str:
    return _paragraph_visible_text(paragraph)


def _blocks_from_container(container: ET.Element) -> str:
    chunks: list[str] = []
    for child in container:
        local = _local_name(child.tag)
        if local == "p":
            chunks.append(_paragraph_visible_text(child))
        elif local == "tbl":
            continue
        elif local == "sdt":
            if _contains_textbox(child):
                continue
            content = child.find("w:sdtContent", NS)
            if content is not None:
                chunks.append(_blocks_from_container(content))
        elif local == "sectPr":
            continue
    return "".join(chunks)


def collect_body_visible_text(document_root: ET.Element) -> str:
    body = document_root.find("w:body", NS)
    if body is None:
        return ""
    return _blocks_from_container(body)
