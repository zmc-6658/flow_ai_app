from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import TypeAdapter

from flow_ai.core.profile_models import RenderProfiles
from flow_ai.core.style_models import RuleNode


def _resolve_templates_dir() -> Path:
    """解析 templates 目录路径，兼容源码运行和 PyInstaller 打包环境。"""
    # PyInstaller 打包后，_MEIPASS 指向解压临时目录
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "flow_ai_open" / "templates"
    # 源码运行时，相对于本文件向上查找
    return Path(__file__).resolve().parent.parent / "templates"


_DEFAULT_RULES_PATH = _resolve_templates_dir() / "default_thesis.yaml"


def load_default_rules() -> list[RuleNode]:
    """加载内置默认排版规则。"""
    return load_rules_from_yaml(str(_DEFAULT_RULES_PATH))


def load_rules_from_yaml(yaml_path: str) -> list[RuleNode]:

    path = Path(yaml_path)
    with path.open("r", encoding="utf-8") as file:
        raw_data = yaml.safe_load(file)

    rules_data = _extract_rules(raw_data)
    return TypeAdapter(list[RuleNode]).validate_python(rules_data)


def load_profiles_from_yaml(yaml_path: str) -> RenderProfiles:

    path = Path(yaml_path)
    with path.open("r", encoding="utf-8") as file:
        raw_data = yaml.safe_load(file)

    if not isinstance(raw_data, dict):
        return RenderProfiles.fallback()

    profiles_data = raw_data.get("profiles")
    if profiles_data is None:
        return RenderProfiles.fallback()

    merged = RenderProfiles.fallback().model_dump()
    for key, value in profiles_data.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return RenderProfiles.model_validate(merged)


def _extract_rules(raw_data: Any) -> Any:
    if isinstance(raw_data, dict) and "rules" in raw_data:
        return raw_data["rules"]
    if isinstance(raw_data, list):
        return raw_data
    raise ValueError("YAML 规则文件必须包含顶层 'rules' 列表")
