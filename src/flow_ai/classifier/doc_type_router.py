"""Document type detection and YAML config loading."""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

from flow_ai.classifier.structural_track import DocTypeConfig, parse_config
from flow_ai.core.ast_models import DocumentAST, ParagraphNode


def _resolve_configs_dir() -> Path:
    """解析 configs 目录路径，兼容源码运行和 PyInstaller 打包环境。"""
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "flow_ai" / "classifier" / "configs"
    return Path(__file__).resolve().parent / "configs"


_CONFIGS_DIR = _resolve_configs_dir()


def load_doc_type_config(doc_type: str) -> DocTypeConfig:
    path = _CONFIGS_DIR / f"{doc_type}.yaml"
    if not path.exists():
        path = _CONFIGS_DIR / "thesis.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return parse_config(raw)


def detect_doc_type(ast: DocumentAST) -> str:
    sample = " ".join(
        node.text[:80]
        for node in ast.blocks[:30]
        if isinstance(node, ParagraphNode)
    ).lower()
    if "合同" in sample or "甲方" in sample or "乙方" in sample or "第一条" in sample:
        return "contract"
    if "executive summary" in sample or "季度" in sample or "报告" in sample:
        return "report"
    return "thesis"
