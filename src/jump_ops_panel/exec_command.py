from __future__ import annotations

import shlex

from .models import AppConfig


def build_remote_command(
    config: AppConfig,
    *,
    target: str,
    args_line: str,
) -> str:
    target = target.strip()
    args_line = args_line.strip()
    remote_dir = config.defaults.script_remote_dir.rstrip("/")
    if target == "bash":
        if not args_line:
            raise ValueError("bash 模式需要输入命令。")
        return args_line
    if not target.endswith(".sh"):
        raise ValueError("脚本名必须以 .sh 结尾。")
    script_path = f"{remote_dir}/{target}"
    parts = [f"bash {shlex.quote(script_path)}"]
    if args_line:
        parts.extend(shlex.quote(part) for part in shlex.split(args_line))
    return " ".join(parts)


def exec_timeout_for_target(config: AppConfig, target: str) -> float:
    defaults = config.defaults
    if target.strip() == "bash":
        return float(defaults.exec_bash_timeout_seconds)
    return float(defaults.exec_script_timeout_seconds)


def format_exec_label(*, target: str, args_line: str) -> str:
    args_line = args_line.strip()
    if target == "bash":
        preview = args_line[:60] + ("…" if len(args_line) > 60 else "")
        return f"bash: {preview or '(空)'}"
    if args_line:
        return f"{target} {args_line}"[:80]
    return target
