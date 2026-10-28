from __future__ import annotations

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
from .terminal_output import clean_command_stdout, command_kind_for_target, settle_timeout_for


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


async def _apply_run_as(
    profile: ProfileConfig,
    handle: str,
    *,
    timeout_seconds: float,
) -> None:
    run_as = profile.target.run_as
    if run_as.method.lower() == "sudo" and run_as.user:
        await switch_terminal_user_payload(
            session_handle=handle,
            target_user=run_as.user,
            method="sudo",
            total_timeout_seconds=min(timeout_seconds, 30.0),
        )


async def open_dedicated_terminal(
    profile: ProfileConfig,
    defaults: AppConfig,
    *,
    data_dir,
    reuse_existing: bool = False,
) -> str:
    set_package_log_level("WARNING")
    with profile_jms_env(profile, data_dir=data_dir):
        await ensure_authenticated(profile, data_dir=data_dir)
        opened = await acquire_terminal_session_payload(
            asset_ref=profile.target.asset_ref,
            account_ref=profile.target.account_ref,
            protocol=defaults.defaults.protocol,
            connect_method=defaults.defaults.connect_method,
            reuse_existing=reuse_existing,
        )
        return str(opened["session_handle"])


async def close_terminal(handle: str) -> None:
    try:
        await close_terminal_session_payload(session_handle=handle)
    except Exception:
        pass


async def run_on_handle(
    handle: str,
    remote_command: str,
    *,
    timeout_seconds: float,
    command_kind: str = "script",
) -> tuple[int | None, str, str]:
    payload = await run_terminal_command_payload(
        session_handle=handle,
        command=remote_command,
        settle_timeout_seconds=settle_timeout_for(
            timeout_seconds,
            command_kind=command_kind,
        ),
        total_timeout_seconds=timeout_seconds,
    )
    exit_status = payload.get("exit_status")
    stdout, hint = clean_command_stdout(payload)
    if hint and stdout:
        hint = ""
    return (
        int(exit_status) if exit_status is not None else None,
        stdout,
        hint,
    )


async def run_manual_remote(
    profile: ProfileConfig,
    defaults: AppConfig,
    remote_command: str,
    *,
    data_dir,
    timeout_seconds: float,
    label: str,
    target: str,
    cache,
) -> RunResult:
    started = datetime.now(tz=UTC)
    kind = command_kind_for_target(target)

    async def opener() -> str:
        return await open_dedicated_terminal(
            profile,
            defaults,
            data_dir=data_dir,
            reuse_existing=True,
        )

    async def runner(entry) -> RunResult:
        if not entry.run_as_done:
            await _apply_run_as(
                profile,
                entry.handle,
                timeout_seconds=timeout_seconds,
            )
            entry.run_as_done = True
        exit_status, stdout, hint = await run_on_handle(
            entry.handle,
            remote_command,
            timeout_seconds=timeout_seconds,
            command_kind=kind,
        )
        finished = datetime.now(tz=UTC)
        return RunResult(
            profile_id=profile.id,
            label=label,
            command=remote_command,
            exit_status=exit_status,
            stdout=stdout,
            started_at=started,
            finished_at=finished,
            error=hint,
        )

    try:
        return await cache.with_session(profile.id, opener, runner)
    except Exception as exc:
        finished = datetime.now(tz=UTC)
        return RunResult(
            profile_id=profile.id,
            label=label,
            command=remote_command,
            exit_status=None,
            stdout="",
            started_at=started,
            finished_at=finished,
            error=str(exc),
        )


async def run_ephemeral_remote(
    profile: ProfileConfig,
    defaults: AppConfig,
    remote_command: str,
    *,
    data_dir,
    timeout_seconds: float = 90.0,
    label: str = "exec",
    command_kind: str = "script",
) -> RunResult:
    started = datetime.now(tz=UTC)
    handle: str | None = None
    try:
        handle = await open_dedicated_terminal(profile, defaults, data_dir=data_dir)
        await _apply_run_as(profile, handle, timeout_seconds=timeout_seconds)
        exit_status, stdout, hint = await run_on_handle(
            handle,
            remote_command,
            timeout_seconds=timeout_seconds,
            command_kind=command_kind,
        )
        error = hint
    except Exception as exc:
        exit_status = None
        stdout = ""
        error = str(exc)
    finally:
        if handle:
            await close_terminal(handle)
    finished = datetime.now(tz=UTC)
    return RunResult(
        profile_id=profile.id,
        label=label,
        command=remote_command,
        exit_status=exit_status,
        stdout=stdout,
        started_at=started,
        finished_at=finished,
        error=error,
    )


async def run_script_remote(
    profile: ProfileConfig,
    defaults: AppConfig,
    remote_command: str,
    *,
    data_dir,
    timeout_seconds: float,
    label: str,
) -> RunResult:
    """Long .sh scripts use a dedicated terminal so manual bash cache stays free."""
    return await run_ephemeral_remote(
        profile,
        defaults,
        remote_command,
        data_dir=data_dir,
        timeout_seconds=timeout_seconds,
        label=label,
        command_kind="script",
    )


async def open_prepared_terminal(
    profile: ProfileConfig,
    defaults: AppConfig,
    *,
    data_dir,
    timeout_seconds: float = 30.0,
) -> str:
    handle = await open_dedicated_terminal(profile, defaults, data_dir=data_dir)
    try:
        await _apply_run_as(profile, handle, timeout_seconds=timeout_seconds)
        return handle
    except Exception:
        await close_terminal(handle)
        raise


async def run_operation(
    profile: ProfileConfig,
    defaults: AppConfig,
    operation: OperationConfig,
    *,
    data_dir,
    terminal_lock_held: bool = False,
    user_priority: bool = False,
) -> RunResult:
    del terminal_lock_held, user_priority
    remote_command = _build_command(
        profile,
        defaults,
        script_name=operation.script,
        command=operation.command,
    )
    return await run_ephemeral_remote(
        profile,
        defaults,
        remote_command,
        data_dir=data_dir,
        timeout_seconds=operation.timeout_seconds,
        label=operation.label,
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
    del terminal_lock_held
    op = OperationConfig(
        id=script_name,
        label=label,
        script=script_name,
        timeout_seconds=timeout_seconds,
    )
    return await run_operation(profile, defaults, op, data_dir=data_dir)
