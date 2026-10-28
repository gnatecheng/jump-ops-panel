from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

SAFE_SCRIPT_NAME = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]*\.sh$")
MAX_UPLOAD_BYTES = 256 * 1024


@dataclass
class ScriptEntry:
    name: str
    remote_path: str
    uploaded_at: str
    size: int


class ScriptCatalog:
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir

    def _manifest_path(self, profile_id: str) -> Path:
        return self._data_dir / "manifests" / f"{profile_id}.json"

    def _local_dir(self, profile_id: str) -> Path:
        return self._data_dir / "uploads" / profile_id

    def list_scripts(self, profile_id: str) -> list[ScriptEntry]:
        path = self._manifest_path(profile_id)
        if not path.is_file():
            return []
        raw = json.loads(path.read_text(encoding="utf-8"))
        entries = [ScriptEntry(**item) for item in raw.get("scripts", [])]
        return sorted(entries, key=lambda e: e.name.lower())

    def validate_filename(self, filename: str) -> str:
        name = Path(filename).name
        if name != filename or ".." in filename:
            raise ValueError("非法文件名。")
        if not SAFE_SCRIPT_NAME.match(name):
            raise ValueError("仅允许 .sh 文件名（字母数字._-）。")
        return name

    def save_upload(
        self,
        profile_id: str,
        *,
        name: str,
        remote_path: str,
        size: int,
    ) -> ScriptEntry:
        entries = self.list_scripts(profile_id)
        entries = [e for e in entries if e.name != name]
        entry = ScriptEntry(
            name=name,
            remote_path=remote_path,
            uploaded_at=datetime.now(tz=UTC).isoformat(),
            size=size,
        )
        entries.append(entry)
        path = self._manifest_path(profile_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"scripts": [asdict(e) for e in entries]}, indent=2),
            encoding="utf-8",
        )
        return entry

    def local_staging_path(self, profile_id: str, name: str) -> Path:
        directory = self._local_dir(profile_id)
        directory.mkdir(parents=True, exist_ok=True)
        return directory / name
