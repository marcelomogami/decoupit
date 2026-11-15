import sqlite3
from pathlib import Path

import pytest

import decoupit.database as database_module
from decoupit.database import MigrationError, connect_database, initialize_database


def test_initialize_database_applies_initial_migration(tmp_path: Path) -> None:
    database_path = tmp_path / "data" / "decoupit.sqlite3"

    initialize_database(database_path)

    with connect_database(database_path) as connection:
        tables = {
            row["name"]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        migration = connection.execute(
            "SELECT version, name, length(checksum) AS checksum_length "
            "FROM schema_migrations"
        ).fetchone()
        schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]

    assert {
        "jobs",
        "normalized_media",
        "projects",
        "schema_migrations",
        "source_media",
    } <= tables
    assert dict(migration) == {
        "version": 1,
        "name": "create_projects",
        "checksum_length": 64,
    }
    assert schema_version == 4
    assert foreign_keys == 1


def test_initialize_database_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"

    initialize_database(database_path)
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        count = connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[
            0
        ]

    assert count == 4


def test_project_constraints_reject_invalid_state(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    initialize_database(database_path)

    with (
        connect_database(database_path) as connection,
        pytest.raises(sqlite3.IntegrityError),
    ):
        connection.execute(
            "INSERT INTO projects (id, name, status) VALUES (?, ?, ?)",
            ("project-id", "Projeto", "invalid"),
        )


def test_changed_applied_migration_is_rejected(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    initialize_database(database_path)
    with connect_database(database_path) as connection:
        connection.execute(
            "UPDATE schema_migrations SET checksum = ? WHERE version = 1",
            ("0" * 64,),
        )

    with pytest.raises(MigrationError, match="migração aplicada foi alterada: 1"):
        initialize_database(database_path)


def test_job_constraints_reject_invalid_state(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    initialize_database(database_path)

    with (
        connect_database(database_path) as connection,
        pytest.raises(sqlite3.IntegrityError),
    ):
        connection.execute(
            "INSERT INTO jobs (id, kind, state) VALUES (?, ?, ?)",
            ("job-id", "normalize_media", "invalid"),
        )


def test_existing_database_is_backed_up_before_pending_migration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    migrations = database_module._load_migrations()
    monkeypatch.setattr(database_module, "_load_migrations", lambda: migrations[:3])
    initialize_database(database_path)
    with connect_database(database_path) as connection:
        connection.execute(
            "INSERT INTO projects (id, name) VALUES ('kept', 'Preservado')"
        )
        connection.commit()

    monkeypatch.setattr(database_module, "_load_migrations", lambda: migrations)
    initialize_database(database_path)

    backups = list((tmp_path / "backups").glob("*-before-v0004.sqlite3"))
    assert len(backups) == 1
    with connect_database(backups[0]) as connection:
        project = connection.execute(
            "SELECT name FROM projects WHERE id = 'kept'"
        ).fetchone()
        version = connection.execute("PRAGMA user_version").fetchone()[0]
    assert project["name"] == "Preservado"
    assert version == 3
