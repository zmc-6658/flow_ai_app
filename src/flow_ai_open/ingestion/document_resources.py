"""Extract styles.xml and numbering.xml summaries for document_resources."""
from __future__ import annotations

import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


def read_document_resources(docx_path: Path) -> dict:
    resources: dict = {"styles": [], "numbering": []}
    with zipfile.ZipFile(docx_path, "r") as zf:
        resources["styles"] = _read_styles(zf)
        resources["numbering"] = _read_numbering(zf)
    return resources


def _read_styles(zf: zipfile.ZipFile) -> list[dict]:
    try:
        root = ET.fromstring(zf.read("word/styles.xml"))
    except KeyError:
        return []
    styles: list[dict] = []
    for style in root.findall(".//w:style", NS):
        style_id = style.get(f"{{{W_NS}}}styleId") or style.get("styleId")
        style_type = style.get(f"{{{W_NS}}}type") or style.get("type")
        name_el = style.find("w:name", NS)
        name = name_el.get(f"{{{W_NS}}}val") if name_el is not None else None
        if style_id:
            styles.append({"style_id": style_id, "type": style_type, "name": name})
    return styles


def _read_numbering(zf: zipfile.ZipFile) -> list[dict]:
    try:
        root = ET.fromstring(zf.read("word/numbering.xml"))
    except KeyError:
        return []
    nums: list[dict] = []
    for num in root.findall(".//w:num", NS):
        num_id_el = num.find("w:numId", NS)
        if num_id_el is None:
            continue
        num_id = num_id_el.get(f"{{{W_NS}}}val")
        if num_id:
            nums.append({"num_id": num_id})
    return nums
