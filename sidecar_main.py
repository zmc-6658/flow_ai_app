from __future__ import annotations

import json
import logging
import os
import sys
import traceback
import uuid
from pathlib import Path
from typing import Any

from flow_ai.contracts.status_shell import StatusShell
from flow_ai_open.adapters.patch_merger import DecisionPatch
from flow_ai_open.config_loader import is_debug_enabled, is_verbose_errors
from flow_ai_open.pipeline import FlowPipeline
from flow_ai_open.pipeline.ast_projection import (
    build_ast_tree,
    decisions_to_dicts,
)

_pipeline: FlowPipeline | None = None
log = logging.getLogger(__name__)


def get_pipeline() -> FlowPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = FlowPipeline()
    return _pipeline


# ---------------------------------------------------------------------------
# 用户设置持久化（%APPDATA%/Flow-AI/settings.json 或 ~/.flow_ai/settings.json）
# ---------------------------------------------------------------------------

def _settings_dir() -> Path:
    """返回用户级配置目录"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Flow-AI"
    return Path.home() / ".flow_ai"


def _settings_path() -> Path:
    path = _settings_dir() / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _load_settings() -> dict[str, Any]:
    """加载用户设置；首次运行则生成 install_id"""
    path = _settings_path()
    if path.is_file():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as exc:
            log.warning("加载设置失败: %s", exc)
    return {
        "install_id": str(uuid.uuid4()),
        "telemetry_opt_in": None,
        "first_run": True,
    }


def _save_settings(settings: dict[str, Any]) -> None:
    """保存用户设置到磁盘"""
    path = _settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 响应辅助函数
# ---------------------------------------------------------------------------

def _shell_to_dict(
    shell: StatusShell,
    request_id: int | None = None,
) -> dict[str, Any]:
    status = "error" if shell.error_code is not None else "success"
    error_code_str = shell.error_code.value if shell.error_code is not None else None
    data = None
    if shell.data is not None:
        if hasattr(shell.data, "model_dump"):
            data = shell.data.model_dump(mode="json")
        elif isinstance(shell.data, Path):
            data = str(shell.data)
        else:
            data = shell.data
    result: dict[str, Any] = {
        "id": request_id,
        "status": status,
        "schema_version": "v3",
        "data": data,
        "error_code": error_code_str,
        "message": shell.message,
        "recoverable": shell.recoverable,
    }
    if request_id is None:
        result.pop("id")
    return result


def _success_response(
    data: Any,
    request_id: int | None = None,
    message: str = "",
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": request_id,
        "status": "success",
        "schema_version": "v3",
        "data": data,
        "error_code": None,
        "message": message,
        "recoverable": True,
    }
    if request_id is None:
        result.pop("id")
    return result


def _error_response(
    error_code: str,
    message: str,
    request_id: int | None = None,
    recoverable: bool = True,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": request_id,
        "status": "error",
        "schema_version": "v3",
        "data": None,
        "error_code": error_code,
        "message": message,
        "recoverable": recoverable,
    }
    if request_id is None:
        result.pop("id")
    return result


def _project_current_state() -> dict[str, Any]:
    pipeline = get_pipeline()
    decisions = pipeline.context.decisions
    ast = pipeline.context.classified_ast or pipeline.context.ast
    return {
        "ast": build_ast_tree(ast, decisions) if ast is not None else [],
        "decisions": decisions_to_dicts(decisions) if decisions else [],
    }


# ---------------------------------------------------------------------------
# 核心 Pipeline Handlers
# ---------------------------------------------------------------------------

def _handle_parse(params: dict[str, Any], req_id: int) -> dict[str, Any]:
    docx_path = params.get("docx_path", "")
    if not docx_path:
        return _error_response(
            "INVALID_PARAMS", "缺少 docx_path 参数", request_id=req_id
        )
    pipeline = get_pipeline()
    shell = pipeline.parse(docx_path)
    if shell.error_code is not None:
        return _shell_to_dict(shell, request_id=req_id)
    decisions = pipeline.context.decisions
    projected = build_ast_tree(shell.data, decisions) if shell.data else []
    return _success_response({"ast": projected}, request_id=req_id)


def _handle_classify(params: dict[str, Any], req_id: int) -> dict[str, Any]:
    pipeline = get_pipeline()
    shell = pipeline.classify()
    if shell.error_code is not None:
        return _shell_to_dict(shell, request_id=req_id)
    decisions = pipeline.context.decisions
    ast = pipeline.context.classified_ast
    projected_ast = build_ast_tree(ast, decisions) if ast else []
    projected_decisions = decisions_to_dicts(decisions) if decisions else []
    return _success_response(
        {"ast": projected_ast, "decisions": projected_decisions},
        request_id=req_id,
    )


def _handle_patch(params: dict[str, Any], req_id: int) -> dict[str, Any]:
    raw_patches = params.get("patches", [])
    if not raw_patches:
        return _error_response(
            "INVALID_PARAMS", "缺少 patches 参数", request_id=req_id
        )
    patches = [DecisionPatch(**p) for p in raw_patches]
    pipeline = get_pipeline()
    shell = pipeline.patch_decisions(patches)
    if shell.error_code is not None:
        return _shell_to_dict(shell, request_id=req_id)
    decisions = pipeline.context.decisions
    ast = pipeline.context.classified_ast or pipeline.context.ast
    projected_ast = build_ast_tree(ast, decisions) if ast else []
    projected_decisions = decisions_to_dicts(decisions) if decisions else []
    return _success_response(
        {"ast": projected_ast, "decisions": projected_decisions},
        request_id=req_id,
    )


def _handle_compile(params: dict[str, Any], req_id: int) -> dict[str, Any]:
    rules_path = params.get("rules_path")
    pipeline = get_pipeline()
    shell = pipeline.compile_plan(rules_path)
    if shell.error_code is not None:
        return _shell_to_dict(shell, request_id=req_id)
    # 返回编译结果摘要，而非完整 RenderPlan
    render_plan = shell.data
    compiled = render_plan is not None
    node_count = len(render_plan.node_styles) if render_plan and hasattr(render_plan, "node_styles") else 0
    return _success_response(
        {
            "source": rules_path or "inline",
            "compiled": compiled,
            "rules_path": rules_path,
            "node_count": node_count,
        },
        request_id=req_id,
    )


def _handle_render(params: dict[str, Any], req_id: int) -> dict[str, Any]:
    output_path = params.get("output_path", "")
    if not output_path:
        return _error_response(
            "INVALID_PARAMS", "缺少 output_path 参数", request_id=req_id
        )
    pipeline = get_pipeline()
    shell = pipeline.render(output_path)
    if shell.error_code is not None:
        return _shell_to_dict(shell, request_id=req_id)
    rendered_path = str(shell.data) if shell.data else ""

    # 渲染成功后，若用户已同意遥测，则尝试上传 pending 队列
    _try_upload_telemetry()

    return _success_response({"output_path": rendered_path}, request_id=req_id)


def _try_upload_telemetry() -> None:
    """若用户同意遥测，尝试上传 KnowledgeBase 中的 pending 数据"""
    settings = _load_settings()
    if settings.get("telemetry_opt_in") is not True:
        return
    try:
        from flow_ai.format.knowledge_base import open_thread_local
        from flow_ai_open.telemetry import upload_pending, upload_content_role_pending

        kb = open_thread_local()
        upload_pending(kb)
        upload_content_role_pending(kb)
        kb.close()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 状态与设置 Handlers
# ---------------------------------------------------------------------------

def _handle_get_status(params: dict[str, Any], req_id: int) -> dict[str, Any]:
    pipeline = get_pipeline()
    ctx = pipeline.context
    has_ast = ctx.ast is not None
    has_classified = ctx.classified_ast is not None
    has_decisions = len(ctx.decisions) > 0
    has_plan = has_ast and ctx.render_plan is not None
    return _success_response(
        {
            "has_document": has_ast,
            "has_classified": has_classified,
            "has_decisions": has_decisions,
            "has_plan": has_plan,
            "decision_count": len(ctx.decisions),
        },
        request_id=req_id,
    )


def _handle_reset(params: dict[str, Any], req_id: int) -> dict[str, Any]:
    pipeline = get_pipeline()
    pipeline.reset()
    return _success_response({"status": "ok"}, request_id=req_id)


def _handle_get_typography_defaults(params: dict[str, Any], req_id: int) -> dict[str, Any]:
    """返回排版默认数据：优先从当前解析的文档动态生成，无文档时回退静态模板。"""
    from flow_ai_open.typography_defaults import (
        build_typography_defaults_from_ast,
        get_typography_defaults,
    )
    try:
        # 优先使用已解析文档的 AST 动态生成排版样式
        pipeline = get_pipeline()
        ast = pipeline.context.ast
        if ast is not None and ast.blocks:
            data = build_typography_defaults_from_ast(ast)
            # 补充 rule_definitions（UI 选择器用）
            from flow_ai_open.engine.yaml_loader import load_default_rules
            rules = load_default_rules()
            data["rule_definitions"] = [rule.model_dump(mode="json") for rule in rules]
            return _success_response(data, request_id=req_id)

        # 无已解析文档时回退到静态模板
        data = get_typography_defaults()
        from flow_ai_open.engine.yaml_loader import load_default_rules
        rules = load_default_rules()
        data["rule_definitions"] = [rule.model_dump(mode="json") for rule in rules]
        return _success_response(data, request_id=req_id)
    except Exception as exc:
        return _error_response(
            "HANDLER_ERROR",
            f"获取排版默认数据失败: {exc}",
            request_id=req_id,
            recoverable=True,
        )


def _handle_get_settings(params: dict[str, Any], req_id: int) -> dict[str, Any]:
    """返回用户设置（首次调用时自动生成 install_id）"""
    settings = _load_settings()
    return _success_response(settings, request_id=req_id)


def _handle_update_settings(params: dict[str, Any], req_id: int) -> dict[str, Any]:
    """更新用户设置并持久化"""
    settings = _load_settings()
    if "telemetry_opt_in" in params:
        settings["telemetry_opt_in"] = params["telemetry_opt_in"]
    if "first_run" in params:
        settings["first_run"] = params["first_run"]
    _save_settings(settings)
    return _success_response(settings, request_id=req_id)


# ---------------------------------------------------------------------------
# 格式契约与遥测 Handlers
# ---------------------------------------------------------------------------

def _handle_extract_format_catalog(params: dict[str, Any], req_id: int) -> dict[str, Any]:
    """从模板 DOCX 提取格式目录（占位，待实现完整链路）"""
    return _success_response({"catalog": []}, request_id=req_id)


def _handle_confirm_format_slot(params: dict[str, Any], req_id: int) -> dict[str, Any]:
    """用户确权格式签名，记录到本地 KnowledgeBase；若开启遥测则加入上传队列"""
    fingerprint_key = params.get("fingerprint_key", "")
    section = params.get("section", "body")
    slot_id = params.get("slot_id", "")
    doc_type = params.get("doc_type", "thesis")

    if not fingerprint_key or not slot_id:
        return _error_response(
            "INVALID_PARAMS",
            "缺少 fingerprint_key 或 slot_id 参数",
            request_id=req_id,
        )

    settings = _load_settings()
    install_id = settings.get("install_id") or str(uuid.uuid4())

    try:
        from flow_ai.format.knowledge_base import open_thread_local

        kb = open_thread_local()
        kb.record_confirmation(
            fingerprint_key=fingerprint_key,
            section=section,
            slot_id=slot_id,
            doc_type=doc_type,
            install_id=install_id,
        )
        kb.close()
    except Exception as exc:
        return _error_response(
            "HANDLER_ERROR",
            f"记录格式签名失败: {exc}",
            request_id=req_id,
            recoverable=True,
        )

    # 若用户已同意遥测，尝试立即上传
    if settings.get("telemetry_opt_in") is True:
        _try_upload_telemetry()

    return _success_response({"confirmed": True}, request_id=req_id)


HANDLERS: dict[str, Any] = {
    "parse": _handle_parse,
    "classify": _handle_classify,
    "patch": _handle_patch,
    "compile": _handle_compile,
    "render": _handle_render,
    "get_status": _handle_get_status,
    "reset": _handle_reset,
    "get_typography_defaults": _handle_get_typography_defaults,
    "get_settings": _handle_get_settings,
    "update_settings": _handle_update_settings,
    "extract_format_catalog": _handle_extract_format_catalog,
    "confirm_format_slot": _handle_confirm_format_slot,
}


def _dispatch(request: dict[str, Any]) -> dict[str, Any]:
    cmd = request.get("cmd", "")
    params = request.get("params", {})
    req_id = request.get("id")

    handler = HANDLERS.get(cmd)
    if handler is None:
        return _error_response(
            "UNKNOWN_COMMAND",
            f"未知命令: {cmd}",
            request_id=req_id,
            recoverable=True,
        )

    try:
        return handler(params, req_id)
    except Exception as exc:
        tb = traceback.format_exc()
        log_message = f"{exc}\n{tb}" if is_verbose_errors() else str(exc)
        return _error_response(
            "HANDLER_ERROR",
            log_message,
            request_id=req_id,
            recoverable=False,
        )


def run_sidecar() -> None:
    import signal

    # 优雅处理终止信号
    def _handle_signal(signum: int, _frame: Any) -> None:
        sig_name = signal.Signals(signum).name
        sys.stderr.write(f"[Sidecar] 收到信号 {sig_name}，正在退出...\n")
        sys.exit(0)

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _error_response(
                error_code="INVALID_JSON",
                message=f"JSON 解析失败: {exc}",
                request_id=None,
                recoverable=True,
            )
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()
            continue

        cmd = request.get("cmd", "")
        if cmd == "exit":
            break

        response = _dispatch(request)
        sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
        sys.stdout.flush()


if __name__ == "__main__":
    run_sidecar()
