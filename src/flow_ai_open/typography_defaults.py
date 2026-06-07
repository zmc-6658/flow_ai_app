from __future__ import annotations

import sys
from collections import defaultdict
from typing import Any

from flow_ai.core.ast_models import (
    BlockFeatures,
    DocumentAST,
    HeadingNode,
    ParagraphNode,
)

_SEMANTIC_ROLE_TO_BASE_ROLE: dict[str, str] = {
    "title_cn": "DOC_TITLE",
    "title_en": "DOC_TITLE",
    "author_info": "AUTHOR",
    "abstract": "ABSTRACT",
    "abstract_body": "NORMAL",
    "abstract_body_en": "NORMAL",
    "keywords": "KEYWORDS",
    "keywords_en": "KEYWORDS",
    "toc": "NORMAL",
    "toc_entry": "NORMAL",
    "references": "REFERENCES",
    "references_item": "REFERENCES",
    "acknowledgment": "NORMAL",
    "acknowledgment_body": "NORMAL",
    "appendix": "NORMAL",
    "appendix_body": "NORMAL",
    "figure_caption": "FIGURE_CAPTION",
    "table_caption": "TABLE_CAPTION",
    "body": "NORMAL",
    "standard": "NORMAL",
}

_HEADING_LEVEL_TO_BASE_ROLE: dict[int, str] = {
    1: "HEADING_1",
    2: "HEADING_2",
    3: "HEADING_3",
    4: "HEADING_4",
}

_GROUP_BY_ROLE: dict[str, str] = {
    "DOC_TITLE": "元数据",
    "AUTHOR": "元数据",
    "ABSTRACT": "元数据",
    "KEYWORDS": "元数据",
    "HEADING_1": "标题组",
    "HEADING_2": "标题组",
    "HEADING_3": "标题组",
    "HEADING_4": "标题组",
    "NORMAL": "正文组",
    "BLOCK_QUOTE": "正文组",
    "LIST_BULLET": "正文组",
    "LIST_NUMBER": "正文组",
    "FIGURE_CAPTION": "正文组",
    "TABLE_CAPTION": "正文组",
    "TABLE_CELL": "正文组",
    "REFERENCES": "参考文献",
    "HEADER_TEXT": "页眉页脚",
    "FOOTER_TEXT": "页眉页脚",
    "FOOTNOTE": "脚注",
}


def _resolve_base_role_id(rule: dict[str, Any]) -> str:
    selector = rule.get("selector", {})
    semantic_role = selector.get("semantic_role", "")
    if semantic_role in _SEMANTIC_ROLE_TO_BASE_ROLE:
        return _SEMANTIC_ROLE_TO_BASE_ROLE[semantic_role]
    level = selector.get("level")
    if isinstance(level, int) and level in _HEADING_LEVEL_TO_BASE_ROLE:
        return _HEADING_LEVEL_TO_BASE_ROLE[level]
    if selector.get("node_kind") == "heading":
        return "HEADING_1"
    return "NORMAL"


def _intent_to_rules(intent: dict[str, Any]) -> list[dict[str, Any]]:
    rules: list[dict[str, Any]] = []
    rule_id_counter = 0

    if "font_name" in intent or "east_asia_font" in intent:
        font_name = intent.get("east_asia_font") or intent.get("font_name", "")
        rules.append({
            "id": f"rule-{rule_id_counter}",
            "kind": "fontFamily",
            "label": "字体",
            "value": font_name,
            "valueLabel": font_name,
        })
        rule_id_counter += 1

    if "font_size_pt" in intent:
        size_pt = intent["font_size_pt"]
        rules.append({
            "id": f"rule-{rule_id_counter}",
            "kind": "fontSize",
            "label": "字号",
            "value": f"{size_pt}pt",
            "valueLabel": f"{size_pt} 磅",
        })
        rule_id_counter += 1

    if "bold" in intent and intent["bold"]:
        rules.append({
            "id": f"rule-{rule_id_counter}",
            "kind": "fontStyle",
            "label": "字形",
            "value": "bold",
            "valueLabel": "加粗",
        })
        rule_id_counter += 1

    if "alignment" in intent:
        alignment = intent["alignment"]
        rules.append({
            "id": f"rule-{rule_id_counter}",
            "kind": "alignment",
            "label": "对齐方式",
            "value": alignment,
            "valueLabel": alignment,
        })
        rule_id_counter += 1

    if "first_line_indent_pt" in intent:
        indent_pt = intent["first_line_indent_pt"]
        rules.append({
            "id": f"rule-{rule_id_counter}",
            "kind": "specialIndent",
            "label": "首行缩进",
            "value": f"{indent_pt}pt",
            "valueLabel": f"{indent_pt} 磅",
        })
        rule_id_counter += 1

    if "line_spacing_pt" in intent:
        sp_pt = intent["line_spacing_pt"]
        rules.append({
            "id": f"rule-{rule_id_counter}",
            "kind": "lineSpacing",
            "label": "行距",
            "value": f"{sp_pt}pt",
            "valueLabel": f"固定值 {sp_pt} 磅",
        })
        rule_id_counter += 1
    elif "line_spacing_multiple" in intent:
        mult = intent["line_spacing_multiple"]
        rules.append({
            "id": f"rule-{rule_id_counter}",
            "kind": "lineSpacing",
            "label": "行距",
            "value": f"{mult}x",
            "valueLabel": f"{mult} 倍行距",
        })
        rule_id_counter += 1

    if "space_before_pt" in intent or "space_after_pt" in intent:
        before = intent.get("space_before_pt", 0)
        after = intent.get("space_after_pt", 0)
        label_parts = []
        if before:
            label_parts.append(f"段前 {before} 磅")
        if after:
            label_parts.append(f"段后 {after} 磅")
        rules.append({
            "id": f"rule-{rule_id_counter}",
            "kind": "spacingBeforeAfter",
            "label": "段间距",
            "value": f"{before}|{after}",
            "valueLabel": " · ".join(label_parts) if label_parts else "默认",
        })
        rule_id_counter += 1

    return rules


def _load_profile_rules(yaml_path: str) -> list[dict[str, Any]]:
    path = Path(yaml_path)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        return []
    profile = data.get("profile", {})
    return profile.get("rules", [])


def get_typography_defaults() -> dict[str, Any]:
    # 兼容 PyInstaller 打包环境
    if hasattr(sys, "_MEIPASS"):
        templates_dir = Path(sys._MEIPASS) / "flow_ai_open" / "templates"
    else:
        templates_dir = Path(__file__).resolve().parent / "templates"
    extracted_path = templates_dir / "extracted_thesis.yaml"

    profile_rules = _load_profile_rules(str(extracted_path))

    style_variants: list[dict[str, Any]] = []
    role_rules: dict[str, list[dict[str, Any]]] = {}

    for rule in profile_rules:
        rule_id = rule.get("id", "")
        label = rule.get("label", rule_id)
        description = rule.get("description", "")
        base_role_id = _resolve_base_role_id(rule)
        group_name = _GROUP_BY_ROLE.get(base_role_id, "正文组")
        overrides = _intent_to_rules(rule.get("intent", {}))
        selector = rule.get("selector", {})
        region = selector.get("region", "body")

        variant: dict[str, Any] = {
            "id": rule_id,
            "name": label,
            "groupName": group_name,
            "description": description,
            "baseRoleId": base_role_id,
            "inheritedFromRoleName": label,
            "isCustom": False,
            "isConfirmed": False,
            "overrides": overrides,
            "region": region,
            "isSystemDefault": True,
        }
        style_variants.append(variant)

        role_rules.setdefault(base_role_id, []).append({
            "id": rule_id,
            "kind": rule_id,
            "label": label,
            "value": base_role_id,
            "valueLabel": label,
        })

    base_roles: list[dict[str, Any]] = []
    for role_id, rules in role_rules.items():
        base_roles.append({
            "id": role_id,
            "name": role_id,
            "groupName": _GROUP_BY_ROLE.get(role_id, "正文组"),
            "description": "",
            "defaultRules": rules,
        })

    return {
        "base_roles": base_roles,
        "style_variants": style_variants,
        "rule_definitions": [],
    }


# ---------------------------------------------------------------------------
# 动态生成：从已解析的文档 AST 提取排版样式（替代静态模板）
# ---------------------------------------------------------------------------

def _normalize_font_name(name: str | None) -> str:
    """标准化字体名（大小写、空格、常见别名统一）。"""
    if not name:
        return ""
    name = name.strip().lower()
    # 常见别名映射
    _alias_map = {
        "simhei": "黑体", "heiti": "黑体",
        "simsun": "宋体", "songti": "宋体", "宋体": "宋体",
        "simfang": "仿宋", "fangsong": "仿宋",
        "kaiti": "楷体", "simkai": "楷体",
        "times new roman": "Times New Roman",
        "calibri": "Calibri",
        "微软雅黑": "微软雅黑", "microsoft yahei": "微软雅黑",
    }
    return _alias_map.get(name, name.title())


def _style_group_key(feat: BlockFeatures, node_kind: str, level: int | None) -> str:
    """生成宽松的分组 key：相同 Word 样式 + 近似视觉特征 → 同一组。

    字号四舍五入到 0.5pt，字体名标准化，对齐方式只分4类。
    """
    # 主键：Word 内部样式名（最可靠的样式标识）
    style = (feat.style_name or "unknown").strip()

    # 辅助：近似视觉特征（宽松匹配）
    size = feat.dominant_font_size or 0
    size_bucket = f"{round(size * 2) / 2:.1f}pt"  # 四舍五入到 0.5pt

    font = _normalize_font_name(feat.dominant_font_family)

    align_raw = (
        feat.alignment.value if hasattr(feat.alignment, "value") else str(feat.alignment)
    ).lower()
    align_bucket = align_raw if align_raw in ("left", "center", "right", "justify") else ""

    bold = "B" if (feat.bold_ratio or 0) > 0.5 else ""
    is_heading = "H" if node_kind == "heading" else ""
    lvl = f"L{level}" if node_kind == "heading" and level is not None else ""

    return f"{style}|{size_bucket}|{font}|{align_bucket}{bold}{is_heading}{lvl}"


def _generate_style_label(
    feat: BlockFeatures,
    node_kind: str,
    level: int | None,
    member_count: int,
) -> str:
    """生成有意义的样式名称（基于特征描述，不用段落文本）。"""
    parts: list[str] = []

    # 节点类型
    if node_kind == "heading" and level is not None:
        level_cn = {1: "一级标题", 2: "二级标题", 3: "三级标题", 4: "四级标题"}.get(level, f"标题{level}")
        parts.append(level_cn)

    # Word 样式名（如果有意义）
    style = (feat.style_name or "").strip()
    if style and style.lower() not in ("normal", "", "unknown"):
        parts.append(style)

    # 视觉特征摘要
    if feat.dominant_font_size:
        parts.append(f"{feat.dominant_font_size:.0f}pt")
    if feat.dominant_font_family:
        parts.append(_normalize_font_name(feat.dominant_font_family))
    if (feat.bold_ratio or 0) > 0.5:
        parts.append("加粗")

    if parts:
        return " ".join(parts)

    # 兜底
    if node_kind == "heading":
        return "标题"
    return "正文"


def _infer_base_role_from_features(
    kind: str,
    level: int | None,
    feat: BlockFeatures,
) -> str:
    """根据节点类型 + 样式特征推断 base_role。"""
    if kind == "heading":
        level = level or 1
        return _HEADING_LEVEL_TO_BASE_ROLE.get(level, "HEADING_1")

    # 通过 style_name 推断语义角色
    name = (feat.style_name or "").lower()
    size = feat.dominant_font_size or 0

    if any(kw in name for kw in ("title", "标题", "大标题")):
        return "DOC_TITLE"
    if any(kw in name for kw in ("author", "作者", "姓名")):
        return "AUTHOR"
    if any(kw in name for kw in ("abstract", "摘要")):
        return "ABSTRACT"
    if any(kw in name for kw in ("keyword", "关键词")):
        return "KEYWORDS"
    if any(kw in name for kw in ("reference", "参考文献", "bibliography")):
        return "REFERENCES"
    if any(kw in name for kw in ("toc", "目录")):
        return "NORMAL"
    if any(kw in name for kw in ("acknowledgment", "致谢")):
        return "NORMAL"

    # 大字号 → 可能是标题类
    if size >= 18:
        return "HEADING_1"
    if size >= 14:
        return "HEADING_2"

    return "NORMAL"


def build_typography_defaults_from_ast(ast: DocumentAST) -> dict[str, Any]:
    """从已解析的文档 AST 动态生成排版默认数据。

    策略：
      1. 按 Word 内部样式名 + 宽松视觉特征分组（字号四舍五入、字体标准化）
      2. 每组生成一个 style_variant，用特征描述命名（非段落文本）
      3. 合并成员数 <= 1 的微小组到相邻的大组，避免碎片化
    """
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    role_counter: dict[str, int] = defaultdict(int)

    for node in ast.blocks:
        feat = getattr(node, "features", None)
        if not isinstance(feat, BlockFeatures):
            continue

        kind = getattr(node, "kind", "paragraph")
        level = getattr(node, "level", None)
        key = _style_group_key(feat, kind, level)

        base_role_id = _infer_base_role_from_features(kind, level, feat)
        role_counter[base_role_id] += 1

        groups[key].append({
            "node_id": node.id,
            "baseRoleId": base_role_id,
            "kind": kind,
            "level": level,
            "feat": feat,
        })

    # 过滤掉成员过少的碎片组（<=1 个段落的单独组合并到 NORMAL）
    MIN_GROUP_SIZE = 2
    merged_singles: list[dict[str, Any]] = []
    filtered_groups: dict[str, list[dict[str, Any]]] = {}

    for key, members in groups.items():
        if len(members) >= MIN_GROUP_SIZE:
            filtered_groups[key] = members
        else:
            merged_singles.extend(members)

    # 将碎片归入最大的 NORMAL 组
    if merged_singles:
        # 找一个已有的 NORMAL 组或创建一个
        normal_key = next((k for k, v in filtered_groups.items() if any(m["baseRoleId"] == "NORMAL" for m in v)), None)
        if normal_key:
            filtered_groups[normal_key].extend(merged_singles)
        else:
            filtered_groups["__merged_singles__"] = merged_singles

    style_variants: list[dict[str, Any]] = []
    role_rules: dict[str, list[dict[str, Any]]] = {}

    for key, members in filtered_groups.items():
        rep = members[0]
        feat = rep["feat"]
        base_role_id = rep["baseRoleId"]

        variant_id = f"dyn-{len(style_variants)}"
        label = _generate_style_label(feat, rep["kind"], rep["level"], len(members))
        group_name = _GROUP_BY_ROLE.get(base_role_id, "正文组")
        overrides = _intent_to_features_to_rules(feat)

        variant: dict[str, Any] = {
            "id": variant_id,
            "name": label,
            "groupName": group_name,
            "description": f"{len(members)} 个段落 · 源样式: {feat.style_name or '自定义'}",
            "baseRoleId": base_role_id,
            "inheritedFromRoleName": label,
            "isCustom": False,
            "isConfirmed": False,
            "overrides": overrides,
            "region": "body",
            "isSystemDefault": True,
        }
        style_variants.append(variant)

        role_rules.setdefault(base_role_id, []).append({
            "id": variant_id,
            "kind": variant_id,
            "label": label,
            "value": base_role_id,
            "valueLabel": label,
        })

    base_roles: list[dict[str, Any]] = []
    for role_id in sorted(role_counter.keys()):
        base_roles.append({
            "id": role_id,
            "name": role_id,
            "groupName": _GROUP_BY_ROLE.get(role_id, "正文组"),
            "description": f"共 {role_counter[role_id]} 个段落",
            "defaultRules": role_rules.get(role_id, []),
        })

    return {
        "base_roles": base_roles,
        "style_variants": style_variants,
        "rule_definitions": [],
    }


def _intent_to_features_to_rules(feat: BlockFeatures) -> list[dict[str, Any]]:
    """将 BlockFeatures 转换为前端 TypographyRule 格式的 overrides。"""
    rules: list[dict[str, Any]] = []
    rid = 0

    if feat.dominant_font_family:
        rules.append({
            "id": f"fr-{rid}", "kind": "fontFamily",
            "label": "字体", "value": feat.dominant_font_family,
            "valueLabel": feat.dominant_font_family,
        })
        rid += 1

    if feat.dominant_font_size:
        sz = feat.dominant_font_size
        rules.append({
            "id": f"fr-{rid}", "kind": "fontSize",
            "label": "字号", "value": f"{sz}pt",
            "valueLabel": f"{sz:.1f} 磅",
        })
        rid += 1

    if (feat.bold_ratio or 0) > 0.5:
        rules.append({
            "id": f"fr-{rid}", "kind": "fontStyle",
            "label": "字形", "value": "bold",
            "valueLabel": "加粗",
        })
        rid += 1

    alignment_val = (
        feat.alignment.value if hasattr(feat.alignment, "value") else str(feat.alignment)
    )
    if alignment_val and alignment_val != "unknown":
        align_map = {"left": "左对齐", "center": "居中", "right": "右对齐", "justify": "两端对齐"}
        rules.append({
            "id": f"fr-{rid}", "kind": "alignment",
            "label": "对齐方式", "value": alignment_val,
            "valueLabel": align_map.get(alignment_val, alignment_val),
        })
        rid += 1

    if feat.indent_first_line_twips is not None and feat.indent_first_line_twips > 0:
        indent_pt = round(feat.indent_first_line_twips / 20, 1)
        rules.append({
            "id": f"fr-{rid}", "kind": "specialIndent",
            "label": "首行缩进", "value": f"{indent_pt}pt",
            "valueLabel": f"{indent_pt} 磅",
        })
        rid += 1

    return rules