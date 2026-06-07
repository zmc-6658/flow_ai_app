"""Flow-AI Python 侧配置加载模块。

设计原则：
- Rust（Tauri 宿主进程）独占读取 config.yaml
- Rust 在 spawn Sidecar 子进程时，将配置注入为环境变量
- Python 侧只从环境变量读取，不自行查找配置文件

环境变量由 Rust 注入，也可手动设置（用于独立运行 sidecar_main.py 调试）。
"""
from __future__ import annotations

import os


def get_supabase_url() -> str:
    """Supabase 项目 URL（由 Rust 从 config.yaml 注入，或手动设置）"""
    return os.environ.get("FLOW_AI_SUPABASE_URL", "")


def get_supabase_anon_key() -> str:
    """Supabase 匿名密钥（由 Rust 从 config.yaml 注入，或手动设置）"""
    return os.environ.get("FLOW_AI_SUPABASE_ANON_KEY", "")


def is_debug_enabled() -> bool:
    """调试模式开关"""
    return os.environ.get("FLOW_AI_DEBUG") == "1"


def is_verbose_errors() -> bool:
    """详细异常 traceback（调试模式子开关）"""
    return os.environ.get("FLOW_AI_VERBOSE_ERRORS") == "1"
