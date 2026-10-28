from __future__ import annotations

import shlex

from .models import AppConfig


def koko_sftp_staging_path(config: AppConfig, logical_path: str) -> str | None:
    """KoKo elFinder SFTP often writes logical paths under a mirror prefix (e.g. /tmp/home/...)."""
    prefix = (config.defaults.script_sftp_mirror_prefix or "").strip()
    if not prefix:
        return None
    logical = logical_path if logical_path.startswith("/") else f"/{logical_path}"
    return f"{prefix.rstrip('/')}{logical}"


def build_upload_sync_command(config: AppConfig, *, script_name: str) -> str | None:
    remote_dir = config.defaults.script_remote_dir.rstrip("/")
    dest = f"{remote_dir}/{script_name}"
    staging = koko_sftp_staging_path(config, dest)
    if not staging:
        return None
    return (
        f"if [ -f {shlex.quote(staging)} ]; then "
        f"mkdir -p {shlex.quote(remote_dir)} && "
        f"cp -f {shlex.quote(staging)} {shlex.quote(dest)} && "
        f"chmod +x {shlex.quote(dest)}; "
        f"elif [ -f {shlex.quote(dest)} ]; then "
        f"chmod +x {shlex.quote(dest)}; "
        f"else "
        f"echo 'JOP upload sync: missing {staging} and {dest}' >&2; "
        f"exit 1; "
        f"fi"
    )
