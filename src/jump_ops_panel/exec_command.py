from __future__ import annotations

import shlex

from .models import AppConfig, ProfileConfig


def _wrap_script_login_shell(profile: ProfileConfig, command: str, *, target: str) -> str:
    """Non-login KoKo shells miss root kubeconfig; match interactive `sudo -i` env."""
    if target.strip() == "bash":
        return command
    if profile.target.run_as.method.lower() != "sudo":
        return command
    return f"bash -lc {shlex.quote(command)}"


def _wrap_script_timeout(command: str, *, target: str, timeout_seconds: float | None) -> str:
    if target.strip() == "bash" or timeout_seconds is None or timeout_seconds <= 0:
        return command
    limit = max(30, int(timeout_seconds) - 15)
    return f"timeout -s TERM {limit} {command}"


def build_remote_command(
    config: AppConfig,
    profile: ProfileConfig,
    *,
    target: str,
    args_line: str,
    timeout_seconds: float | None = None,
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
    command = " ".join(parts)
    command = _wrap_script_login_shell(profile, command, target=target)
    command = _wrap_script_timeout(
        command,
        target=target,
        timeout_seconds=timeout_seconds,
    )
    return command


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
