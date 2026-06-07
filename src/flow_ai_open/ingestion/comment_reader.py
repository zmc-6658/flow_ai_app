"""Read comments.xml into ParseMetadata (D9-A: store only, do not export)."""
from __future__ import annotations

import zipfile
from pathlib import Path
from uuid import uuid4
from xml.etree import ElementTree as ET

from flow_ai.core.ast_models import CommentSummary, OpaqueType
from flow_ai.core.preservation_models import AssetBlob, AssetStore

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}


def read_comments(docx_path: Path, asset_store: AssetStore) -> list[CommentSummary]:
    part = "word/comments.xml"
    summaries: list[CommentSummary] = []
    with zipfile.ZipFile(docx_path, "r") as zf:
        try:
            raw = zf.read(part)
        except KeyError:
            return summaries

        asset_store.add(
            AssetBlob(
                id=f"asset_comments_{uuid4().hex[:8]}",
                opaque_type=OpaqueType.GENERIC,
                xml=raw.decode("utf-8"),
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.comments+xml",
            )
        )

        root = ET.fromstring(raw)
        for comment in root.findall(".//w:comment", NS):
            comment_id = comment.get(f"{{{W_NS}}}id") or comment.get("w:id") or ""
            author = comment.get(f"{{{W_NS}}}author") or comment.get("w:author")
            date = comment.get(f"{{{W_NS}}}date") or comment.get("w:date")
            text_parts: list[str] = []
            for t_el in comment.findall(".//w:t", NS):
                if t_el.text:
                    text_parts.append(t_el.text)
            summaries.append(
                CommentSummary(
                    comment_id=str(comment_id),
                    author=author,
                    text="".join(text_parts),
                    date=date,
                )
            )
    return summaries
