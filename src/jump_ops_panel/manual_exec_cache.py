from __future__ import annotations

import asyncio
from dataclasses import dataclass

from .jms_runner import close_terminal


@dataclass
class _CachedSession:
    handle: str
    run_as_done: bool = False


class ManualExecCache:
    """One reusable JumpServer terminal per profile for manual Exec (avoids reconnect each click)."""

    def __init__(self) -> None:
        self._entries: dict[str, _CachedSession] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    def _lock(self, profile_id: str) -> asyncio.Lock:
        if profile_id not in self._locks:
            self._locks[profile_id] = asyncio.Lock()
        return self._locks[profile_id]

    async def evict(self, profile_id: str) -> None:
        entry = self._entries.pop(profile_id, None)
        if entry and entry.handle:
            await close_terminal(entry.handle)

    async def close_all(self) -> None:
        for profile_id in list(self._entries.keys()):
            await self.evict(profile_id)

    async def get_or_open(
        self,
        profile_id: str,
        opener,
    ) -> _CachedSession:
        entry = self._entries.get(profile_id)
        if entry is not None:
            return entry
        handle = await opener()
        entry = _CachedSession(handle=handle)
        self._entries[profile_id] = entry
        return entry

    async def with_session(self, profile_id: str, opener, runner):
        async with self._lock(profile_id):
            try:
                entry = await self.get_or_open(profile_id, opener)
                return await runner(entry)
            except Exception:
                await self.evict(profile_id)
                raise
