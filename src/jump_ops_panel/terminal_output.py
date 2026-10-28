from __future__ import annotations


def settle_timeout_for(
    total_timeout_seconds: float,
    *,
    command_kind: str = "script",
) -> float:
    """KoKo idle gap after last output before treating the command as finished."""
    if command_kind == "bash":
        # Short commands (id, kubectl get …) should not wait 30–60s of silence.
        return min(5.0, max(2.0, total_timeout_seconds * 0.05))
    return max(30.0, min(total_timeout_seconds * 0.5, 120.0))


def command_kind_for_target(target: str) -> str:
    return "bash" if target.strip() == "bash" else "script"


def exec_timeout_seconds(
    *,
    target: str,
    default_script: float,
    default_bash: float,
) -> float:
    if target.strip() == "bash":
        return default_bash
    return default_script


def _strip_mcp_wrapper(text: str) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    filtered: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped in {"stty -echo", "stty echo"}:
            continue
        if stripped.startswith("trap 'stty echo'"):
            continue
        if stripped.startswith("__MCP_JMS_COMMAND_START_"):
            continue
        if stripped.startswith("__MCP_JMS_EXIT_STATUS_"):
            continue
        filtered.append(line)
    return "\n".join(filtered).strip()


def clean_command_stdout(payload: dict) -> tuple[str, str]:
    """Return (stdout, error_hint) from run_terminal_command_payload."""
    completed = bool(payload.get("command_completed"))
    timed_out = bool(payload.get("timed_out"))
    stdout = str(payload.get("command_stdout_text") or "").strip()
    if not completed:
        stdout = _strip_mcp_wrapper(stdout)
    if completed:
        return stdout, ""
    hint = ""
    if timed_out or not completed:
        hint = (
            "命令在超时时间内未结束（输出可能不完整）。"
            "长脚本可在 profiles 调大 exec_script_timeout_seconds。"
        )
    if not stdout:
        return "", hint
    return stdout, ""
