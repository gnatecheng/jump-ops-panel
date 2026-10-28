from __future__ import annotations

import logging
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from .config_loader import load_config
from .dashboard_store import DashboardStore
from .models import AppConfig

LOGGER = logging.getLogger(__name__)


def start_dashboard_scheduler(
    *,
    config_path: Path,
    data_dir: Path,
    store: DashboardStore,
) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler()

    def reload_config() -> AppConfig:
        return load_config(config_path)

    async def tick(profile_id: str) -> None:
        config = reload_config()
        try:
            profile = config.get_profile(profile_id)
        except KeyError:
            return
        if not profile.dashboard.panels:
            return
        store.schedule_refresh(profile, config, data_dir=data_dir)

    config = load_config(config_path)
    for profile in config.profiles:
        interval = max(profile.dashboard.refresh_interval_seconds, 5)
        scheduler.add_job(
            tick,
            "interval",
            seconds=interval,
            args=[profile.id],
            id=f"dashboard-{profile.id}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    scheduler.start()
    return scheduler
