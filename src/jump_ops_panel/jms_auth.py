from __future__ import annotations

import asyncio
import logging
import os

from mcp_jumpserver_gui_sucks.cli_login import JumpServerCLILogin, LoginFlowError
from mcp_jumpserver_gui_sucks.config import Settings
from mcp_jumpserver_gui_sucks.logging_utils import set_package_log_level
from mcp_jumpserver_gui_sucks.service import build_status_payload, refresh_terminal_auth_payload
from mcp_jumpserver_gui_sucks.session_store import SessionStore

from .config_loader import resolve_password
from .jms_env import profile_jms_env
from .models import ProfileConfig

LOGGER = logging.getLogger(__name__)


async def auth_status_ok() -> bool:
    payload = await build_status_payload()
    return bool(payload.get("authenticated")) and bool(
        payload.get("cookie_session_authenticated")
    )


def login_with_password(profile: ProfileConfig, password: str) -> None:
    set_package_log_level("WARNING")
    settings = Settings.from_env()
    flow = JumpServerCLILogin(
        settings,
        base_url=profile.jumpserver.base_url.rstrip("/"),
    )
    try:
        flow.bootstrap()
        encrypted = flow.encrypt_password(password)
        flow.establish_web_session(
            username=profile.jumpserver.username,
            encrypted_password=encrypted,
        )
        try:
            flow.get_confirm_descriptor(confirm_type="password")
            flow.complete_confirmation(
                confirm_type="password",
                secret_key=encrypted,
            )
            key_payload = flow.create_access_key()
            auth_state = flow.build_access_key_auth_state(
                username=profile.jumpserver.username,
                key_id=str(key_payload.get("id", "")),
                secret=str(key_payload.get("secret", "")),
                login_source="jump-ops-panel",
            )
        except LoginFlowError as exc:
            LOGGER.warning("Access key setup skipped, using cookie session: %s", exc)
            auth_state = flow.build_web_session_auth_state(
                username=profile.jumpserver.username,
                login_source="jump-ops-panel-cookie",
            )
        SessionStore(settings.state_file).save(auth_state)
    finally:
        flow.close()


def _allow_password_login() -> bool:
    return os.getenv("JOP_ALLOW_PASSWORD_LOGIN", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


async def ensure_authenticated(profile: ProfileConfig, *, data_dir) -> None:
    with profile_jms_env(profile, data_dir=data_dir):
        if await auth_status_ok():
            return
        await refresh_terminal_auth_payload(force=False)
        if await auth_status_ok():
            return
        if not _allow_password_login():
            raise LoginFlowError(
                "JumpServer 会话无效。Pod 内无法用密码登录（JumpServer 验证码需要人工输入）。"
                "请在本机 mcp-jumpserver-gui-sucks login 后执行 deploy/k8s/upload-auth-state.sh 同步 auth-state。"
            )
        password = resolve_password(profile.jumpserver)
        await asyncio.to_thread(login_with_password, profile, password)
        if not await auth_status_ok():
            raise LoginFlowError(
                "JumpServer 密码登录后仍无法建立会话（常见原因：验证码）。"
                "请改用 upload-auth-state.sh 上传本机 CLI 登录后的 auth-state。"
            )
