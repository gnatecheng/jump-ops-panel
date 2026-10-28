from __future__ import annotations

"""Coordinate JumpServer terminal access between dashboard refresh and user ops."""

_yield_for_user: set[str] = set()


def signal_user_terminal(profile_id: str) -> None:
    _yield_for_user.add(profile_id)


def clear_user_terminal(profile_id: str) -> None:
    _yield_for_user.discard(profile_id)


def should_yield_terminal(profile_id: str) -> bool:
    return profile_id in _yield_for_user
