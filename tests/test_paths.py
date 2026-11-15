from pathlib import Path

from decoupit.paths import resolve_app_paths


def test_resolve_app_paths_uses_xdg_directories(tmp_path: Path) -> None:
    data_home = tmp_path / "data"
    cache_home = tmp_path / "cache"

    paths = resolve_app_paths(
        environment={
            "XDG_DATA_HOME": str(data_home),
            "XDG_CACHE_HOME": str(cache_home),
        },
        home=tmp_path / "home",
    )

    assert paths.data == data_home / "decoupit"
    assert paths.cache == cache_home / "decoupit"
    assert paths.database == data_home / "decoupit" / "decoupit.sqlite3"


def test_relative_xdg_directories_fall_back_to_home(tmp_path: Path) -> None:
    paths = resolve_app_paths(
        environment={"XDG_DATA_HOME": "relative", "XDG_CACHE_HOME": "relative"},
        home=tmp_path,
    )

    assert paths.data == tmp_path / ".local" / "share" / "decoupit"
    assert paths.cache == tmp_path / ".cache" / "decoupit"


def test_create_directories_creates_only_application_roots(tmp_path: Path) -> None:
    paths = resolve_app_paths(environment={}, home=tmp_path)

    paths.create_directories()

    assert paths.data.is_dir()
    assert paths.cache.is_dir()
    assert not paths.database.exists()
