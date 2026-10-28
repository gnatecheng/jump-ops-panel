from __future__ import annotations

import os
from pathlib import Path

import yaml

from .models import AppConfig, JumpServerConfig, ProfileConfig


def resolve_password(jms: JumpServerConfig) -> str:
    if jms.password:
        return jms.password
    if jms.password_env:
        value = os.getenv(jms.password_env, "").strip()
        if value:
            return value
        raise ValueError(f"Environment variable {jms.password_env!r} is not set.")
    raise ValueError("JumpServer password is not configured (password or password_env).")


def load_config(path: Path) -> AppConfig:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("Config root must be a mapping.")
    return AppConfig.model_validate(raw)


def list_profile_summaries(config: AppConfig) -> list[dict[str, str]]:
    return [{"id": p.id, "label": p.label} for p in config.profiles]


def project_root() -> Path:
    raw = os.getenv("JOP_PROJECT_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    here = Path(__file__).resolve().parent
    # editable layout: jump-ops-panel/src/jump_ops_panel/...
    repo_candidate = here.parent.parent
    if (repo_candidate / "assets").is_dir():
        return repo_candidate
    # docker / pip: assets live beside WORKDIR in image
    docker_candidate = Path("/build/jump-ops-panel")
    if (docker_candidate / "assets").is_dir():
        return docker_candidate
    return repo_candidate


def resolve_local_script(local_rel: str, root: Path | None = None) -> Path:
    base = root or project_root()
    path = (base / local_rel).resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Local script not found: {path}")
    return path
