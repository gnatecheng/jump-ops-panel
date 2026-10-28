from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .jms_runner import RunResult, run_operation, run_script_name
from .models import AppConfig, OperationConfig, ProfileConfig

LOGGER = logging.getLogger(__name__)


@dataclass
class PanelSnapshot:
    panel_id: str
    label: str
    result: RunResult | None = None
    last_error: str = ""


@dataclass
class DashboardState:
    profile_id: str
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))
    panels: dict[str, PanelSnapshot] = field(default_factory=dict)
    refresh_in_progress: bool = False


class DashboardStore:
    def __init__(self) -> None:
        self._states: dict[str, DashboardState] = {}
        self._refresh_tasks: dict[str, asyncio.Task] = {}

    def get(self, profile_id: str) -> DashboardState | None:
        return self._states.get(profile_id)

    def placeholder(self, profile_id: str) -> DashboardState:
        existing = self._states.get(profile_id)
        if existing is not None:
            return existing
        state = DashboardState(profile_id=profile_id, refresh_in_progress=True)
        self._states[profile_id] = state
        return state

    def schedule_refresh(
        self,
        profile: ProfileConfig,
        config: AppConfig,
        *,
        data_dir,
    ) -> None:
        task = self._refresh_tasks.get(profile.id)
        if task is not None and not task.done():
            return

        async def _run() -> None:
            try:
                await self.refresh_profile(profile, config, data_dir=data_dir)
            except asyncio.CancelledError:
                LOGGER.info("Dashboard refresh cancelled for profile %s", profile.id)
            except Exception:
                LOGGER.exception("Dashboard refresh failed for profile %s", profile.id)

        self._refresh_tasks[profile.id] = asyncio.create_task(_run())

    async def refresh_profile(
        self,
        profile: ProfileConfig,
        config: AppConfig,
        *,
        data_dir,
    ) -> DashboardState:
        prior = self._states.get(profile.id)
        state = DashboardState(
            profile_id=profile.id,
            panels=dict(prior.panels) if prior else {},
            refresh_in_progress=True,
        )
        self._states[profile.id] = state
        for panel in profile.dashboard.panels:
            snapshot = PanelSnapshot(panel_id=panel.id, label=panel.label)
            try:
                if panel.command:
                    op = OperationConfig(
                        id=panel.id,
                        label=panel.label,
                        command=panel.command,
                        timeout_seconds=30.0,
                    )
                    coro = run_operation(
                        profile,
                        config,
                        op,
                        data_dir=data_dir,
                    )
                elif panel.script:
                    coro = run_script_name(
                        profile,
                        config,
                        panel.script,
                        label=panel.label,
                        data_dir=data_dir,
                        timeout_seconds=90.0,
                    )
                else:
                    snapshot.last_error = "panel 需配置 script 或 command"
                    state.panels[panel.id] = snapshot
                    continue
                snapshot.result = await asyncio.wait_for(coro, timeout=95.0)
                if snapshot.result.error:
                    snapshot.last_error = snapshot.result.error
            except TimeoutError:
                snapshot.last_error = "看板脚本超时（95s）"
            except Exception as exc:
                snapshot.last_error = str(exc)
            state.panels[panel.id] = snapshot
        state.updated_at = datetime.now(tz=UTC)
        state.refresh_in_progress = False
        self._states[profile.id] = state
        return state
