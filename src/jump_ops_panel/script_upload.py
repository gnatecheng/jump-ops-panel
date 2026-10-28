from __future__ import annotations

from pathlib import Path

from mcp_jumpserver_gui_sucks.service import (
    acquire_sftp_session_payload,
    close_sftp_session_payload,
    sftp_mkdir_payload,
    sftp_upload_payload,
)

from .jms_auth import ensure_authenticated
from .jms_env import profile_jms_env
from .jms_runner import run_ephemeral_remote
from .models import AppConfig, ProfileConfig
from .script_catalog import MAX_UPLOAD_BYTES, ScriptCatalog, ScriptEntry
from .script_paths import build_upload_sync_command


async def upload_script_file(
    profile: ProfileConfig,
    config: AppConfig,
    *,
    data_dir: Path,
    filename: str,
    body: bytes,
    catalog: ScriptCatalog,
) -> ScriptEntry:
    name = catalog.validate_filename(filename)
    if len(body) > MAX_UPLOAD_BYTES:
        raise ValueError(f"文件超过 {MAX_UPLOAD_BYTES // 1024}KB 上限。")
    if b"\x00" in body:
        raise ValueError("脚本不能包含二进制 NUL。")

    local_path = catalog.local_staging_path(profile.id, name)
    local_path.write_bytes(body)

    remote_dir = config.defaults.script_remote_dir.rstrip("/")
    remote_path = f"{remote_dir}/{name}"

    with profile_jms_env(profile, data_dir=data_dir):
        await ensure_authenticated(profile, data_dir=data_dir)
        opened = await acquire_sftp_session_payload(
            asset_ref=profile.target.asset_ref,
            account_ref=profile.target.account_ref,
        )
        handle = str(opened["session_handle"])
        try:
            await sftp_mkdir_payload(
                session_handle=handle,
                path=remote_dir,
                parents=True,
            )
            await sftp_upload_payload(
                session_handle=handle,
                local_path=str(local_path),
                remote_path=remote_path,
                overwrite=True,
            )
        finally:
            await close_sftp_session_payload(session_handle=handle)

    sync_cmd = build_upload_sync_command(config, script_name=name)
    if sync_cmd:
        sync_result = await run_ephemeral_remote(
            profile,
            config,
            sync_cmd,
            data_dir=data_dir,
            timeout_seconds=60.0,
            label=f"sync {name}",
        )
        if sync_result.error:
            raise ValueError(f"脚本已上传 SFTP，但同步到执行目录失败：{sync_result.error}")
        if sync_result.exit_status not in (0, None):
            detail = sync_result.stdout or f"exit {sync_result.exit_status}"
            raise ValueError(f"脚本已上传 SFTP，但同步到执行目录失败：{detail}")

    return catalog.save_upload(
        profile.id,
        name=name,
        remote_path=remote_path,
        size=len(body),
    )
