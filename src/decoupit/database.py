"""SQLite connection and migration management."""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

_MIGRATION_NAME = re.compile(r"^(?P<version>\d{4})_(?P<name>[a-z0-9_]+)\.sql$")


class MigrationError(RuntimeError):
    """Raised when the migration history is inconsistent."""


@dataclass(frozen=True, slots=True)
class Migration:
    version: int
    name: str
    checksum: str
    sql: str


def connect_database(path: Path) -> sqlite3.Connection:
    """Open a configured connection to an existing or new database."""

    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA journal_mode = WAL")
    return connection


def _load_migrations() -> tuple[Migration, ...]:
    migration_files = resources.files("decoupit.migrations").iterdir()
    migrations: list[Migration] = []
    for migration_file in sorted(migration_files, key=lambda item: item.name):
        match = _MIGRATION_NAME.fullmatch(migration_file.name)
        if match is None:
            continue
        sql = migration_file.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=int(match.group("version")),
                name=match.group("name"),
                checksum=hashlib.sha256(sql.encode()).hexdigest(),
                sql=sql,
            )
        )
    versions = [migration.version for migration in migrations]
    if versions != list(range(1, len(migrations) + 1)):
        raise MigrationError("as migrações devem formar uma sequência desde a versão 1")
    return tuple(migrations)


def _ensure_migration_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            checksum TEXT NOT NULL CHECK (length(checksum) = 64),
            applied_at TEXT NOT NULL
                DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        ) STRICT
        """
    )
    connection.commit()


def _validate_history(
    connection: sqlite3.Connection, migrations: tuple[Migration, ...]
) -> set[int]:
    known = {migration.version: migration for migration in migrations}
    applied: set[int] = set()
    for row in connection.execute(
        "SELECT version, name, checksum FROM schema_migrations ORDER BY version"
    ):
        migration = known.get(row["version"])
        if migration is None:
            raise MigrationError(f"migração aplicada desconhecida: {row['version']}")
        if row["name"] != migration.name or row["checksum"] != migration.checksum:
            raise MigrationError(f"migração aplicada foi alterada: {row['version']}")
        applied.add(row["version"])
    return applied


def _apply_migration(connection: sqlite3.Connection, migration: Migration) -> None:
    script = f"""
    BEGIN IMMEDIATE;
    {migration.sql}
    INSERT INTO schema_migrations (version, name, checksum)
    VALUES ({migration.version}, '{migration.name}', '{migration.checksum}');
    PRAGMA user_version = {migration.version};
    COMMIT;
    """
    try:
        connection.executescript(script)
    except sqlite3.Error:
        connection.rollback()
        raise


def initialize_database(path: Path) -> None:
    """Create the database and apply every pending migration."""

    path.parent.mkdir(parents=True, exist_ok=True)
    migrations = _load_migrations()
    with connect_database(path) as connection:
        _ensure_migration_table(connection)
        applied = _validate_history(connection, migrations)
        for migration in migrations:
            if migration.version not in applied:
                _apply_migration(connection, migration)
