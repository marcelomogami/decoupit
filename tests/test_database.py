import sqlite3
from pathlib import Path

import pytest

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
        foreign_keys = connection.execute("PRAGMA foreign_keys").fetchone()[0]

    assert {"projects", "schema_migrations"} <= tables
    assert dict(migration) == {
        "version": 1,
        "name": "create_projects",
        "checksum_length": 64,
    }
    assert foreign_keys == 1


def test_initialize_database_is_idempotent(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"

    initialize_database(database_path)
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        count = connection.execute("SELECT count(*) FROM schema_migrations").fetchone()[
            0
        ]

    assert count == 1


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
