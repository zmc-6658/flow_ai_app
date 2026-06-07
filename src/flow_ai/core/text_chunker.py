# TODO: 保留代码——后续大文档分段分类时需要用到 chunk_chinese_text()
# 当前没有任何运行时路径引用此模块，暂不启用。
# 启用时从 flow_ai_app/flow_ai.spec 的 hiddenimports 中恢复此模块。
#
# from __future__ import annotations
#
# import re
#
#
# def _split_paragraphs_keep_separators(text: str) -> list[str]:
#     if not text:
#         return []
#     parts = re.split(r"(\n\n)", text)
#     return [p for p in parts if p != ""]
#
#
# def _split_sentences_in_paragraph(para: str) -> list[str]:
#     if not para:
#         return []
#     parts = para.split("。")
#     if len(parts) == 1:
#         return [parts[0]]
#     sentences: list[str] = []
#     for head in parts[:-1]:
#         sentences.append(head + "。")
#     tail = parts[-1]
#     if tail:
#         sentences.append(tail)
#     return sentences
#
#
# def _build_units(text: str) -> list[str]:
#     units: list[str] = []
#     for piece in _split_paragraphs_keep_separators(text):
#         if piece == "\n\n":
#             units.append(piece)
#         else:
#             units.extend(_split_sentences_in_paragraph(piece))
#     return units
#
#
# def chunk_chinese_text(text: str, max_chars: int = 400) -> list[str]:
#     if not text:
#         return []
#     units = _build_units(text)
#     if not units:
#         return []
#     chunks: list[str] = []
#     current_parts: list[str] = []
#     current_len = 0
#     for u in units:
#         n = len(u)
#         if n > max_chars:
#             if current_parts:
#                 chunks.append("".join(current_parts))
#                 current_parts = []
#                 current_len = 0
#             chunks.append(u)
#             continue
#         if current_len + n <= max_chars:
#             current_parts.append(u)
#             current_len += n
#         else:
#             if current_parts:
#                 chunks.append("".join(current_parts))
#             current_parts = [u]
#             current_len = n
#     if current_parts:
#         chunks.append("".join(current_parts))
#     return chunks