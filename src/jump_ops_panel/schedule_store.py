from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .exec_command import build_remote_command, exec_timeout_for_target, format_exec_label
from .terminal_output import command_kind_for_target
from .jms_runner import RunResult, close_terminal, open_prepared_terminal, run_on_handle
from .models import AppConfig, ProfileConfig

if TYPE_CHECKING:
    from .main import AppState

LOGGER = logging.getLogger(__name__)

MAX_SCHEDULES_PER_PROFILE = 4


@dataclass
class ScheduleEntry:
    id: str
    profile_id: str
    target: str
    args_line: str
    interval_seconds: int
    paused: bool = False
    session_handle: str = ""
    label: str = ""
    last_run_at: str | None = None
    last_stdout: str = ""
    last_error: str = ""
    last_exit_status: int | None = None
    last_duration_seconds: float | None = None
    created_at: str = field(default_factory=lambda: datetime.now(tz=UTC).isoformat())


class ScheduleStore:
    def __init__(
        self,
        scheduler: AsyncIOScheduler,
        *,
        data_dir: Path,
        state_getter: Callable[[], AppState],
    ) -> None:
        self._scheduler = scheduler
        self._data_dir = data_dir
        self._state_getter = state_getter
        self._entries: dict[str, ScheduleEntry] = {}

    def _persist_path(self, profile_id: str) -> Path:
        return self._data_dir / "schedules" / f"{profile_id}.json"

    def load_from_disk(self) -> None:
        directory = self._data_dir / "schedules"
        if not directory.is_dir():
            return
        for path in directory.glob("*.json"):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
                for item in raw.get("schedules", []):
                    entry = ScheduleEntry(**item)
                    entry.session_handle = ""
                    self._entries[entry.id] = entry
            except Exception:
                LOGGER.exception("Failed to load schedules from %s", path)

    async def bootstrap_jobs(self) -> None:
        for entry in list(self._entries.values()):
            if not entry.paused:
                try:
                    await self._ensure_session(entry)
                except Exception:
                    LOGGER.exception("Schedule %s session bootstrap failed", entry.id)
            self._register_job(entry)

    def _save_profile(self, profile_id: str) -> None:
        items = [asdict(e) for e in self._entries.values() if e.profile_id == profile_id]
        for item in items:
            item["session_handle"] = ""
        path = self._persist_path(profile_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"schedules": items}, indent=2), encoding="utf-8")

    def list_for_profile(self, profile_id: str) -> list[ScheduleEntry]:
        return sorted(
            (e for e in self._entries.values() if e.profile_id == profile_id),
            key=lambda e: e.created_at,
        )

    def get(self, schedule_id: str) -> ScheduleEntry | None:
        return self._entries.get(schedule_id)

    def _job_id(self, schedule_id: str) -> str:
        return f"user-schedule-{schedule_id}"

    async def _ensure_session(self, entry: ScheduleEntry) -> None:
        if entry.session_handle:
            return
        state = self._state_getter()
        profile = state.config.get_profile(entry.profile_id)
        handle = await open_prepared_terminal(
            profile,
            state.config,
            data_dir=state.data_dir,
        )
        entry.session_handle = handle

    async def _tick(self, schedule_id: str) -> None:
        entry = self._entries.get(schedule_id)
        if entry is None or entry.paused:
            return
        from .config_loader import load_config

        state = self._state_getter()
        config = load_config(state.config_path)
        tick_started = time.perf_counter()
        try:
            profile = config.get_profile(entry.profile_id)
            await self._ensure_session(entry)
            tick_timeout = exec_timeout_for_target(config, entry.target)
            remote_command = build_remote_command(
                config,
                profile,
                target=entry.target,
                args_line=entry.args_line,
                timeout_seconds=tick_timeout,
            )
            exit_status, stdout, hint = await run_on_handle(
                entry.session_handle,
                remote_command,
                timeout_seconds=tick_timeout,
                command_kind=command_kind_for_target(entry.target),
            )
            entry.last_run_at = datetime.now(tz=UTC).isoformat()
            entry.last_stdout = stdout
            entry.last_exit_status = exit_status
            entry.last_error = hint
        except Exception as exc:
            entry.last_run_at = datetime.now(tz=UTC).isoformat()
            entry.last_error = str(exc)
            entry.last_stdout = ""
            LOGGER.warning("Schedule %s tick failed: %s", schedule_id, exc)
        finally:
            entry.last_duration_seconds = float(
                round(time.perf_counter() - tick_started)
            )
            self._save_profile(entry.profile_id)

    def _register_job(self, entry: ScheduleEntry) -> None:
        job_id = self._job_id(entry.id)
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass
        interval = max(entry.interval_seconds, 5)
        self._scheduler.add_job(
            self._tick,
            "interval",
            seconds=interval,
            args=[entry.id],
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        if entry.paused:
            self._scheduler.pause_job(job_id)
    async def add(
        self,
        profile: ProfileConfig,
        config: AppConfig,
        *,
        target: str,
        args_line: str,
        interval_seconds: int,
    ) -> ScheduleEntry:
        existing = self.list_for_profile(profile.id)
        if len(existing) >= MAX_SCHEDULES_PER_PROFILE:
            raise ValueError(f"每个环境最多 {MAX_SCHEDULES_PER_PROFILE} 个定时 Panel。")
        build_remote_command(
            config,
            profile,
            target=target,
            args_line=args_line,
            timeout_seconds=exec_timeout_for_target(config, target),
        )
        interval_seconds = max(int(interval_seconds), 5)
        entry = ScheduleEntry(
            id=uuid.uuid4().hex[:10],
            profile_id=profile.id,
            target=target.strip(),
            args_line=args_line.strip(),
            interval_seconds=interval_seconds,
            label=format_exec_label(target=target, args_line=args_line),
        )
        self._entries[entry.id] = entry
        await self._ensure_session(entry)
        self._register_job(entry)
        self._save_profile(profile.id)
        return entry

    async def toggle_pause(self, schedule_id: str) -> ScheduleEntry:
        entry = self._entries.get(schedule_id)
        if entry is None:
            raise KeyError(schedule_id)
        job_id = self._job_id(schedule_id)
        if entry.paused:
            entry.paused = False
            if not entry.session_handle:
                await self._ensure_session(entry)
            self._scheduler.resume_job(job_id)
        else:
            entry.paused = True
            self._scheduler.pause_job(job_id)
        self._save_profile(entry.profile_id)
        return entry

    async def close_all_sessions(self) -> None:
        for entry in list(self._entries.values()):
            if entry.session_handle:
                await close_terminal(entry.session_handle)
                entry.session_handle = ""

    async def delete(self, schedule_id: str) -> None:
        entry = self._entries.pop(schedule_id, None)
        if entry is None:
            return
        job_id = self._job_id(schedule_id)
        try:
            self._scheduler.remove_job(job_id)
        except Exception:
            pass
        if entry.session_handle:
            await close_terminal(entry.session_handle)
        self._save_profile(entry.profile_id)
