from __future__ import annotations

import os
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

from .models import ProfileConfig

_ENV_KEYS = (
    "MCP_JUMPSERVER_GUI_SUCKS_BASE_URL",
    "MCP_JUMPSERVER_GUI_SUCKS_STATE_FILE",
    "MCP_JUMPSERVER_GUI_SUCKS_LOG_LEVEL",
    "MCP_JUMPSERVER_GUI_SUCKS_VERIFY_TLS",
)


@contextmanager
def profile_jms_env(
    profile: ProfileConfig,
    *,
    data_dir: Path,
    log_level: str = "WARNING",
) -> Iterator[Path]:
    state_file = data_dir / "state" / profile.id / "auth-state.json"
    state_file.parent.mkdir(parents=True, exist_ok=True)
    verify_tls = "true" if profile.jumpserver.base_url.startswith("https://") else "false"
    values = {
        "MCP_JUMPSERVER_GUI_SUCKS_BASE_URL": profile.jumpserver.base_url.rstrip("/"),
        "MCP_JUMPSERVER_GUI_SUCKS_STATE_FILE": str(state_file),
        "MCP_JUMPSERVER_GUI_SUCKS_LOG_LEVEL": log_level,
        "MCP_JUMPSERVER_GUI_SUCKS_VERIFY_TLS": verify_tls,
    }
    previous: dict[str, str | None] = {}
    for key in _ENV_KEYS:
        previous[key] = os.environ.get(key)
    for key, value in values.items():
        os.environ[key] = value
    try:
        yield state_file
    finally:
        for key in _ENV_KEYS:
            old = previous.get(key)
            if old is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old
