"""Filesystem locations owned by DecoupIt."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppPaths:
    """Durable and recreatable application locations."""

    data: Path
    cache: Path

    @property
    def database(self) -> Path:
        return self.data / "decoupit.sqlite3"

    def create_directories(self) -> None:
        self.data.mkdir(parents=True, exist_ok=True)
        self.cache.mkdir(parents=True, exist_ok=True)


def _absolute_xdg_path(value: str | None, fallback: Path) -> Path:
    if value:
        candidate = Path(value)
        if candidate.is_absolute():
            return candidate
    return fallback


def resolve_app_paths(
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> AppPaths:
    """Resolve XDG paths without creating or modifying them."""

    current_environment = os.environ if environment is None else environment
    user_home = Path.home() if home is None else home
    data_home = _absolute_xdg_path(
        current_environment.get("XDG_DATA_HOME"), user_home / ".local" / "share"
    )
    cache_home = _absolute_xdg_path(
        current_environment.get("XDG_CACHE_HOME"), user_home / ".cache"
    )
    return AppPaths(data=data_home / "decoupit", cache=cache_home / "decoupit")
