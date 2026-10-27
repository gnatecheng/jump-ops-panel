from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime

from .jms_runner import RunResult, run_script_name
from .models import AppConfig, ProfileConfig


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


class DashboardStore:
    def __init__(self) -> None:
        self._states: dict[str, DashboardState] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, profile_id: str) -> asyncio.Lock:
        if profile_id not in self._locks:
            self._locks[profile_id] = asyncio.Lock()
        return self._locks[profile_id]

    def get(self, profile_id: str) -> DashboardState | None:
        return self._states.get(profile_id)

    async def refresh_profile(
        self,
        profile: ProfileConfig,
        config: AppConfig,
        *,
        data_dir,
    ) -> DashboardState:
        lock = self._lock(profile.id)
        async with lock:
            state = DashboardState(profile_id=profile.id)
            for panel in profile.dashboard.panels:
                snapshot = PanelSnapshot(panel_id=panel.id, label=panel.label)
                try:
                    snapshot.result = await run_script_name(
                        profile,
                        config,
                        panel.script,
                        label=panel.label,
                        data_dir=data_dir,
                        timeout_seconds=90.0,
                    )
                    if snapshot.result.error:
                        snapshot.last_error = snapshot.result.error
                except Exception as exc:
                    snapshot.last_error = str(exc)
                state.panels[panel.id] = snapshot
            state.updated_at = datetime.now(tz=UTC)
            self._states[profile.id] = state
            return state
