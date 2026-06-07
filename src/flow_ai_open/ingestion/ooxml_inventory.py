"""从 DOCX OOXML 包统计元素清单与文本 checksum（baseline / coverage 共用）。"""
from __future__ import annotations

import hashlib
import re
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

NS = {"w": W_NS, "m": M_NS, "r": R_NS}


def _tag(local: str) -> str:
    return f"{{{W_NS}}}{local}"


def _m_tag(local: str) -> str:
    return f"{{{M_NS}}}{local}"


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _text_checksum(text: str) -> str:
    normalized = _normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


from flow_ai_open.ingestion.body_text import collect_body_visible_text


def _collect_w_t_text(root: ET.Element) -> str:
    parts: list[str] = []
    for elem in root.iter():
        if elem.tag == _tag("t") and elem.text:
            parts.append(elem.text)
        elif elem.tag == _tag("tab"):
            parts.append(" ")
        elif elem.tag in (_tag("br"), _tag("cr")):
            parts.append("\n")
    return "".join(parts)


def _count_by_tag(root: ET.Element, local: str) -> int:
    tag = _tag(local)
    return sum(1 for elem in root.iter() if elem.tag == tag)


def _read_xml_from_zip(zf: zipfile.ZipFile, part: str) -> ET.Element | None:
    try:
        raw = zf.read(part)
    except KeyError:
        return None
    return ET.fromstring(raw)


def _header_footer_parts(zf: zipfile.ZipFile) -> list[str]:
    return sorted(
        name
        for name in zf.namelist()
        if name.startswith("word/header") and name.endswith(".xml")
        or name.startswith("word/footer") and name.endswith(".xml")
    )


def inventory_from_docx(docx_path: str | Path) -> dict[str, Any]:
    path = Path(docx_path)
    with zipfile.ZipFile(path, "r") as zf:
        document = _read_xml_from_zip(zf, "word/document.xml")
        footnotes = _read_xml_from_zip(zf, "word/footnotes.xml")
        endnotes = _read_xml_from_zip(zf, "word/endnotes.xml")
        comments = _read_xml_from_zip(zf, "word/comments.xml")

        body_text = ""
        body_p = body_tbl = body_sect = 0
        if document is not None:
            body = document.find("w:body", NS)
            if body is not None:
                for child in body:
                    local = child.tag.split("}")[-1] if "}" in child.tag else child.tag
                    if local == "p":
                        body_p += 1
                    elif local == "tbl":
                        body_tbl += 1
                    elif local == "sectPr":
                        body_sect += 1
            body_text = collect_body_visible_text(document)

        header_parts = [p for p in _header_footer_parts(zf) if "/header" in p]
        footer_parts = [p for p in _header_footer_parts(zf) if "/footer" in p]

        header_texts: list[str] = []
        footer_texts: list[str] = []
        for part in header_parts:
            xml = _read_xml_from_zip(zf, part)
            if xml is not None:
                header_texts.append(_collect_w_t_text(xml))
        for part in footer_parts:
            xml = _read_xml_from_zip(zf, part)
            if xml is not None:
                footer_texts.append(_collect_w_t_text(xml))

        footnote_text = ""
        footnote_count = 0
        if footnotes is not None:
            footnote_count = max(0, len(footnotes.findall(".//w:footnote", NS)) - 2)
            footnote_text = _collect_w_t_text(footnotes)

        endnote_text = ""
        endnote_count = 0
        if endnotes is not None:
            endnote_count = max(0, len(endnotes.findall(".//w:endnote", NS)) - 2)
            endnote_text = _collect_w_t_text(endnotes)

        comment_count = 0
        comment_text = ""
        if comments is not None:
            comment_count = len(comments.findall(".//w:comment", NS))
            comment_text = _collect_w_t_text(comments)

        drawing_count = 0
        omath_count = 0
        if document is not None:
            drawing_count = len(document.findall(".//w:drawing", NS)) + len(
                document.findall(".//w:pict", NS)
            )
            omath_count = len(document.findall(".//m:oMath", NS)) + len(
                document.findall(".//m:oMathPara", NS)
            )

        return {
            "source": path.name,
            "body": {
                "paragraphs": body_p,
                "tables": body_tbl,
                "sections": body_sect,
                "text_checksum": _text_checksum(body_text),
                "text_length": len(_normalize_text(body_text)),
            },
            "headers": {
                "parts": len(header_parts),
                "text_checksum": _text_checksum("".join(header_texts)),
            },
            "footers": {
                "parts": len(footer_parts),
                "text_checksum": _text_checksum("".join(footer_texts)),
            },
            "footnotes": {
                "count": footnote_count,
                "text_checksum": _text_checksum(footnote_text),
            },
            "endnotes": {
                "count": endnote_count,
                "text_checksum": _text_checksum(endnote_text),
            },
            "comments": {
                "count": comment_count,
                "text_checksum": _text_checksum(comment_text),
            },
            "opaque": {
                "drawings": drawing_count,
                "equations": omath_count,
                "tables": body_tbl,
            },
        }
