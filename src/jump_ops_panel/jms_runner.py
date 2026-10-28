from __future__ import annotations

import asyncio
import shlex
from dataclasses import dataclass
from datetime import UTC, datetime

from mcp_jumpserver_gui_sucks.logging_utils import set_package_log_level
from mcp_jumpserver_gui_sucks.service import (
    acquire_terminal_session_payload,
    close_terminal_session_payload,
    run_terminal_command_payload,
    switch_terminal_user_payload,
)

from .jms_auth import ensure_authenticated
from .jms_env import profile_jms_env
from .models import AppConfig, OperationConfig, ProfileConfig
from .terminal_coord import clear_user_terminal, signal_user_terminal

_profile_terminal_locks: dict[str, asyncio.Lock] = {}


def profile_terminal_lock(profile_id: str) -> asyncio.Lock:
    if profile_id not in _profile_terminal_locks:
        _profile_terminal_locks[profile_id] = asyncio.Lock()
    return _profile_terminal_locks[profile_id]


class ProfileTerminalBusyError(RuntimeError):
    """Raised when the profile terminal lock is held (e.g. dashboard refresh)."""


async def acquire_profile_terminal(
    profile_id: str,
    *,
    wait_seconds: float,
    user_priority: bool = False,
) -> None:
    if user_priority:
        signal_user_terminal(profile_id)
    lock = profile_terminal_lock(profile_id)
    try:
        await asyncio.wait_for(lock.acquire(), timeout=wait_seconds)
    except TimeoutError as exc:
        if user_priority:
            clear_user_terminal(profile_id)
        raise ProfileTerminalBusyError(
            "JumpServer 终端仍被占用（看板刷新或其它任务）。请等 1–2 分钟再试；"
            "也可点看板「立即刷新」完成后再操作。"
        ) from exc


@dataclass
class RunResult:
    profile_id: str
    label: str
    command: str
    exit_status: int | None
    stdout: str
    started_at: datetime
    finished_at: datetime
    error: str = ""


def _remote_script_command(remote_dir: str, script_name: str) -> str:
    path = f"{remote_dir.rstrip('/')}/{script_name}"
    return f"bash {shlex.quote(path)}"


def _build_command(
    profile: ProfileConfig,
    defaults: AppConfig,
    *,
    script_name: str | None = None,
    command: str | None = None,
) -> str:
    remote_dir = defaults.defaults.script_remote_dir
    if command:
        return command
    if script_name:
        return _remote_script_command(remote_dir, script_name)
    raise ValueError("Either script_name or command is required.")


async def _run_on_session(
    profile: ProfileConfig,
    defaults: AppConfig,
    remote_command: str,
    *,
    timeout_seconds: float,
) -> tuple[int | None, str]:
    set_package_log_level("WARNING")
    opened = await acquire_terminal_session_payload(
        asset_ref=profile.target.asset_ref,
        account_ref=profile.target.account_ref,
        protocol=defaults.defaults.protocol,
        connect_method=defaults.defaults.connect_method,
    )
    handle = str(opened["session_handle"])
    try:
        run_as = profile.target.run_as
        if run_as.method.lower() == "sudo" and run_as.user:
            await switch_terminal_user_payload(
                session_handle=handle,
                target_user=run_as.user,
                method="sudo",
                total_timeout_seconds=min(timeout_seconds, 30.0),
            )
        payload = await run_terminal_command_payload(
            session_handle=handle,
            command=remote_command,
            settle_timeout_seconds=2.0,
            total_timeout_seconds=timeout_seconds,
        )
        exit_status = payload.get("exit_status")
        stdout = str(payload.get("command_stdout_text") or "").strip()
        return (
            int(exit_status) if exit_status is not None else None,
            stdout,
        )
    finally:
        await close_terminal_session_payload(session_handle=handle)


async def _run_operation_locked(
    profile: ProfileConfig,
    defaults: AppConfig,
    operation: OperationConfig,
    *,
    data_dir,
    started: datetime,
    remote_command: str,
) -> tuple[int | None, str, str]:
    with profile_jms_env(profile, data_dir=data_dir):
        await ensure_authenticated(profile, data_dir=data_dir)
        try:
            exit_status, stdout = await _run_on_session(
                profile,
                defaults,
                remote_command,
                timeout_seconds=operation.timeout_seconds,
            )
            return exit_status, stdout, ""
        except Exception as exc:
            return None, "", str(exc)


async def run_operation(
    profile: ProfileConfig,
    defaults: AppConfig,
    operation: OperationConfig,
    *,
    data_dir,
    terminal_lock_held: bool = False,
    user_priority: bool = False,
) -> RunResult:
    started = datetime.now(tz=UTC)
    remote_command = _build_command(
        profile,
        defaults,
        script_name=operation.script,
        command=operation.command,
    )
    exit_status: int | None
    stdout: str
    error: str
    if terminal_lock_held:
        exit_status, stdout, error = await _run_operation_locked(
            profile,
            defaults,
            operation,
            data_dir=data_dir,
            started=started,
            remote_command=remote_command,
        )
    else:
        wait_seconds = 180.0 if user_priority else 15.0
        try:
            await acquire_profile_terminal(
                profile.id,
                wait_seconds=wait_seconds,
                user_priority=user_priority,
            )
        except ProfileTerminalBusyError as exc:
            finished = datetime.now(tz=UTC)
            return RunResult(
                profile_id=profile.id,
                label=operation.label,
                command=remote_command,
                exit_status=None,
                stdout="",
                started_at=started,
                finished_at=finished,
                error=str(exc),
            )
        try:
            exit_status, stdout, error = await _run_operation_locked(
                profile,
                defaults,
                operation,
                data_dir=data_dir,
                started=started,
                remote_command=remote_command,
            )
        finally:
            profile_terminal_lock(profile.id).release()
            if user_priority:
                clear_user_terminal(profile.id)
    finished = datetime.now(tz=UTC)
    return RunResult(
        profile_id=profile.id,
        label=operation.label,
        command=remote_command,
        exit_status=exit_status,
        stdout=stdout,
        started_at=started,
        finished_at=finished,
        error=error,
    )


async def run_script_name(
    profile: ProfileConfig,
    defaults: AppConfig,
    script_name: str,
    *,
    label: str,
    data_dir,
    timeout_seconds: float = 90.0,
    terminal_lock_held: bool = False,
) -> RunResult:
    op = OperationConfig(
        id=script_name,
        label=label,
        script=script_name,
        timeout_seconds=timeout_seconds,
    )
    return await run_operation(
        profile,
        defaults,
        op,
        data_dir=data_dir,
        terminal_lock_held=terminal_lock_held,
    )


async def deploy_init_scripts(
    profile: ProfileConfig,
    defaults: AppConfig,
    *,
    data_dir,
    project_root,
    user_priority: bool = False,
) -> RunResult:
    from .config_loader import resolve_local_script

    started = datetime.now(tz=UTC)
    remote_dir = defaults.defaults.script_remote_dir
    chunks: list[str] = []
    for item in profile.init.scripts:
        try:
            local_path = resolve_local_script(item.local, root=project_root)
            body = local_path.read_text(encoding="utf-8")
        except OSError as exc:
            finished = datetime.now(tz=UTC)
            return RunResult(
                profile_id=profile.id,
                label="初始化脚本",
                command=f"deploy -> {remote_dir}",
                exit_status=None,
                stdout="",
                started_at=started,
                finished_at=finished,
                error=str(exc),
            )
        remote_path = f"{remote_dir.rstrip('/')}/{item.remote_name}"
        quoted = shlex.quote(remote_path)
        chunks.append(
            f"mkdir -p {shlex.quote(remote_dir)} && "
            f"cat > {quoted} <<'JOP_EOF'\n{body}\nJOP_EOF\n"
            f"chmod 755 {quoted}"
        )
    remote_command = " && ".join(chunks) if chunks else "echo 'no init scripts'"
    wait_seconds = 180.0 if user_priority else 15.0
    try:
        await acquire_profile_terminal(
            profile.id,
            wait_seconds=wait_seconds,
            user_priority=user_priority,
        )
    except ProfileTerminalBusyError as exc:
        finished = datetime.now(tz=UTC)
        return RunResult(
            profile_id=profile.id,
            label="初始化脚本",
            command=f"deploy {len(profile.init.scripts)} file(s) -> {remote_dir}",
            exit_status=None,
            stdout="",
            started_at=started,
            finished_at=finished,
            error=str(exc),
        )
    try:
        with profile_jms_env(profile, data_dir=data_dir):
            await ensure_authenticated(profile, data_dir=data_dir)
            try:
                exit_status, stdout = await _run_on_session(
                    profile,
                    defaults,
                    remote_command,
                    timeout_seconds=120.0,
                )
                error = ""
            except Exception as exc:
                exit_status = None
                stdout = ""
                error = str(exc)
    finally:
        profile_terminal_lock(profile.id).release()
        if user_priority:
            clear_user_terminal(profile.id)
    finished = datetime.now(tz=UTC)
    return RunResult(
        profile_id=profile.id,
        label="初始化脚本",
        command=f"deploy {len(profile.init.scripts)} file(s) -> {remote_dir}",
        exit_status=exit_status,
        stdout=stdout or ("OK" if not error else ""),
        started_at=started,
        finished_at=finished,
        error=error,
    )
