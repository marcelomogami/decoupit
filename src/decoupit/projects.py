"""Persistence operations for DecoupIt projects."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Project:
    id: str
    name: str
    status: str
    created_at: str
    updated_at: str


def _project_from_row(row: sqlite3.Row) -> Project:
    return Project(
        id=row["id"],
        name=row["name"],
        status=row["status"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def create_project(
    connection: sqlite3.Connection,
    *,
    name: str,
    project_id: str | None = None,
) -> Project:
    normalized_name = name.strip()
    if not normalized_name:
        raise ValueError("o nome do projeto não pode ficar vazio")
    if len(normalized_name) > 200:
        raise ValueError("o nome do projeto deve ter no máximo 200 caracteres")
    identifier = str(uuid.uuid4()) if project_id is None else project_id
    connection.execute(
        "INSERT INTO projects (id, name) VALUES (?, ?)",
        (identifier, normalized_name),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM projects WHERE id = ?", (identifier,)
    ).fetchone()
    if row is None:
        raise RuntimeError("o projeto criado não foi encontrado")
    return _project_from_row(row)


def list_projects(connection: sqlite3.Connection) -> list[Project]:
    rows = connection.execute(
        "SELECT * FROM projects ORDER BY created_at, id"
    ).fetchall()
    return [_project_from_row(row) for row in rows]


def get_project(connection: sqlite3.Connection, project_id: str) -> Project:
    row = connection.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if row is None:
        raise KeyError(project_id)
    return _project_from_row(row)
