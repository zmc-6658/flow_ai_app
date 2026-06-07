"""Flow-AI 桌面应用入口（PyInstaller 打包用）"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from flow_ai_open.pipeline import FlowPipeline


def get_bundled_rules_path() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)
        return base / "flow_ai_open" / "templates" / "extracted_thesis.yaml"
    return Path(__file__).resolve().parent / "src" / "flow_ai_open" / "templates" / "extracted_thesis.yaml"


def run(input_path: str, rules_path: str | None = None, output_dir: str | None = None) -> Path:
    input_path = Path(input_path).resolve()
    if not input_path.exists():
        print(f"[错误] 文件不存在: {input_path}")
        sys.exit(1)

    rules_path = Path(rules_path).resolve() if rules_path else get_bundled_rules_path()
    output_dir = Path(output_dir).resolve() if output_dir else Path.cwd() / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{input_path.stem}_格式化.docx"

    pipe = FlowPipeline()

    parse_shell = pipe.parse(input_path)
    if parse_shell.error_code:
        print(f"[错误] 解析失败: {parse_shell.message}")
        sys.exit(1)

    classify_shell = pipe.classify()
    if classify_shell.error_code:
        print(f"[错误] 分类失败: {classify_shell.message}")
        sys.exit(1)

    plan_shell = pipe.compile_plan(rules_path)
    if plan_shell.error_code:
        print(f"[错误] 规则编译失败: {plan_shell.message}")
        sys.exit(1)

    render_shell = pipe.render(output_path)
    if render_shell.error_code:
        print(f"[错误] 渲染失败: {render_shell.message}")
        sys.exit(1)

    print(f"完成！输出文件: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="Flow-AI 文档格式化工具")
    parser.add_argument("--sidecar", action="store_true", help="以 Sidecar 模式启动（JSON-RPC stdin/stdout）")
    parser.add_argument("input", nargs="?", help="输入 .docx 文件路径")
    parser.add_argument("-r", "--rules", default=None, help="YAML 规则文件路径")
    parser.add_argument("-o", "--output-dir", default=None, help="输出目录")
    args = parser.parse_args()

    if args.sidecar:
        from sidecar_main import run_sidecar
        run_sidecar()
        return

    if not args.input:
        parser.error("未指定输入文件，请提供 .docx 文件路径")

    run(args.input, args.rules, args.output_dir)


if __name__ == "__main__":
    main()
