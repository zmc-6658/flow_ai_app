"""打包构建脚本：将 Flow-AI + Flow-AI_open 合并打包为 Sidecar EXE（供 Tauri externalBin 使用）"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
FLOW_AI_SRC = ROOT / ".." / "Flow-AI" / "src"
FLOW_AI_OPEN_SRC = ROOT / ".." / "Flow-AI_open" / "src"
MERGED_SRC = ROOT / "src"
CONFIG_YAML = ROOT / ".." / "config.yaml"

# Tauri externalBin 目标三元组后缀（Windows x86_64）
PLATFORM_SUFFIX = "x86_64-pc-windows-msvc"
# Sidecar EXE 名称
SIDECAR_EXE_NAME = "Flow-AI-sidecar"
# Tauri binaries 目录
TAURI_BINARIES_DIR = ROOT / ".." / "Flow-AI_ui-ux" / "src-tauri" / "binaries"


def read_version_from_config() -> str:
    """从 config.yaml 读取统一版本号"""
    content = yaml.safe_load(CONFIG_YAML.read_text(encoding="utf-8"))
    version = content.get("app", {}).get("version", "0.1.0")
    return version


def sync_version(version: str) -> None:
    """将版本号同步到所有相关文件"""
    print(f"[版本同步] 统一版本号: {version}")

    # 1. Flow-AI/src/flow_ai/__init__.py
    init_py = ROOT / ".." / "Flow-AI" / "src" / "flow_ai" / "__init__.py"
    if init_py.exists():
        text = init_py.read_text(encoding="utf-8")
        text = re.sub(r'__version__\s*=\s*"[^"]*"', f'__version__ = "{version}"', text)
        init_py.write_text(text, encoding="utf-8")

    # 2. Flow-AI/pyproject.toml
    for pyproject in [
        ROOT / ".." / "Flow-AI" / "pyproject.toml",
        ROOT / ".." / "Flow-AI_open" / "pyproject.toml",
        ROOT / "pyproject.toml",
    ]:
        if pyproject.exists():
            text = pyproject.read_text(encoding="utf-8")
            text = re.sub(r'version\s*=\s*"[^"]*"', f'version = "{version}"', text, count=1)
            pyproject.write_text(text, encoding="utf-8")

    # 3. tauri.conf.json
    tauri_conf = ROOT / ".." / "Flow-AI_ui-ux" / "src-tauri" / "tauri.conf.json"
    if tauri_conf.exists():
        text = tauri_conf.read_text(encoding="utf-8")
        text = re.sub(r'"version"\s*:\s*"[^"]*"', f'"version": "{version}"', text, count=1)
        tauri_conf.write_text(text, encoding="utf-8")

    # 4. package.json
    package_json = ROOT / ".." / "Flow-AI_ui-ux" / "package.json"
    if package_json.exists():
        text = package_json.read_text(encoding="utf-8")
        text = re.sub(r'"version"\s*:\s*"[^"]*"', f'"version": "{version}"', text, count=1)
        package_json.write_text(text, encoding="utf-8")

    print("[版本同步] 已同步到所有文件")


def merge_sources() -> None:
    """合并 Flow-AI 和 Flow-AI_open 的源码到 src/ 目录"""
    if MERGED_SRC.exists():
        shutil.rmtree(MERGED_SRC)
    MERGED_SRC.mkdir(parents=True)

    flow_ai_dst = MERGED_SRC / "flow_ai"
    if flow_ai_dst.exists():
        shutil.rmtree(flow_ai_dst)
    shutil.copytree(FLOW_AI_SRC / "flow_ai", flow_ai_dst)

    flow_ai_open_dst = MERGED_SRC / "flow_ai_open"
    if flow_ai_open_dst.exists():
        shutil.rmtree(flow_ai_open_dst)
    shutil.copytree(FLOW_AI_OPEN_SRC / "flow_ai_open", flow_ai_open_dst)

    print(f"[1/4] 源码合并完成: {MERGED_SRC}")


def install_deps() -> None:
    """安装依赖和 PyInstaller"""
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"), "--quiet"]
    )
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "pyinstaller", "--quiet"]
    )
    print("[2/4] 依赖安装完成")


def build_exe() -> Path:
    """执行 PyInstaller 构建，返回生成的 EXE 路径"""
    # 清理旧构建产物
    for old_dir in [ROOT / "build", ROOT / "dist"]:
        if old_dir.exists():
            shutil.rmtree(old_dir, ignore_errors=True)
            print(f"  [清理] 已删除旧构建目录: {old_dir.name}")

    subprocess.check_call(
        [sys.executable, "-m", "PyInstaller", str(ROOT / "flow_ai.spec"), "--clean", "--noconfirm"],
        cwd=str(ROOT),
    )
    exe_path = ROOT / "dist" / f"{SIDECAR_EXE_NAME}.exe"
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / 1024 / 1024
        print(f"[3/4] EXE 构建完成: {exe_path} ({size_mb:.1f} MB)")
        return exe_path
    else:
        print("\n构建失败，请检查日志")
        sys.exit(1)


def copy_to_tauri_binaries(exe_path: Path) -> None:
    """将构建好的 EXE 复制到 Tauri binaries 目录，并添加平台三元组后缀"""
    TAURI_BINARIES_DIR.mkdir(parents=True, exist_ok=True)

    # Tauri externalBin 要求文件名格式：<name>-<target-triple>.exe
    target_name = f"{SIDECAR_EXE_NAME}-{PLATFORM_SUFFIX}.exe"
    target_path = TAURI_BINARIES_DIR / target_name

    shutil.copy2(exe_path, target_path)
    size_mb = target_path.stat().st_size / 1024 / 1024
    print(f"[4/4] 已复制到 Tauri binaries: {target_path} ({size_mb:.1f} MB)")


def verify_sidecar(exe_path: Path) -> None:
    """验证构建的 EXE 能否启动并响应 JSON-RPC ping 请求"""
    print("\n正在验证 Sidecar EXE ...")
    try:
        # 构造一个简单的 ping 请求（使用 get_status 命令，不需要前置状态）
        ping_request = json.dumps({"cmd": "get_status", "id": 1, "params": {}})
        # 启动 EXE 进程，通过 stdin 发送请求，读取 stdout 响应
        proc = subprocess.run(
            [str(exe_path)],
            input=ping_request + "\n",
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode != 0:
            print(f"  [警告] Sidecar 退出码非零: {proc.returncode}")
            if proc.stderr:
                print(f"  stderr: {proc.stderr[:500]}")
            return

        # 解析 stdout 中的 JSON 响应
        output_lines = [line.strip() for line in proc.stdout.strip().splitlines() if line.strip()]
        if not output_lines:
            print("  [警告] Sidecar 未返回任何输出")
            return

        response = json.loads(output_lines[-1])
        if response.get("status") == "success" and response.get("id") == 1:
            print("  ✓ Sidecar 验证通过：成功响应 get_status 请求")
        else:
            print(f"  [警告] Sidecar 返回了非预期响应: {response}")
    except subprocess.TimeoutExpired:
        print("  [警告] Sidecar 验证超时（15秒），可能启动较慢")
    except json.JSONDecodeError as exc:
        print(f"  [警告] Sidecar 返回了非 JSON 输出: {exc}")
    except Exception as exc:
        print(f"  [警告] Sidecar 验证失败: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Flow-AI Sidecar 打包构建")
    parser.add_argument(
        "--sidecar-only",
        action="store_true",
        help="仅执行 Sidecar 打包（跳过源码合并和依赖安装，直接构建 EXE）",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Flow-AI Sidecar 打包（Tauri externalBin）")
    print("=" * 60)

    # 从 config.yaml 读取版本号并同步到所有文件
    version = read_version_from_config()
    sync_version(version)

    if args.sidecar_only:
        # 跳过源码合并和依赖安装，直接构建
        print("[跳过] 源码合并（--sidecar-only 模式）")
        print("[跳过] 依赖安装（--sidecar-only 模式）")
        exe_path = build_exe()
    else:
        merge_sources()
        install_deps()
        exe_path = build_exe()

    copy_to_tauri_binaries(exe_path)
    verify_sidecar(exe_path)


if __name__ == "__main__":
    main()
