"""Persistence for manually reviewed frame intervals."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass


class ReviewIntervalError(ValueError):
    """Raised when manual interval boundaries are invalid."""


@dataclass(frozen=True, slots=True)
class ReviewInterval:
    id: str
    normalized_media_id: str
    start_frame: int
    end_frame: int
    created_at: str
    updated_at: str


def _interval_from_row(row: sqlite3.Row) -> ReviewInterval:
    return ReviewInterval(
        id=row["id"],
        normalized_media_id=row["normalized_media_id"],
        start_frame=row["start_frame"],
        end_frame=row["end_frame"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _validate_frames(start_frame: int, end_frame: int, frame_count: int) -> None:
    if (
        isinstance(start_frame, bool)
        or isinstance(end_frame, bool)
        or not isinstance(start_frame, int)
        or not isinstance(end_frame, int)
    ):
        raise ReviewIntervalError("os limites devem ser quadros inteiros")
    if start_frame < 0:
        raise ReviewIntervalError("o quadro inicial não pode ser negativo")
    if end_frame < start_frame:
        raise ReviewIntervalError("o quadro final não pode vir antes do inicial")
    if frame_count <= 0 or end_frame >= frame_count:
        raise ReviewIntervalError("o quadro final está fora da mídia")


def list_review_intervals(
    connection: sqlite3.Connection, normalized_media_id: str
) -> list[ReviewInterval]:
    rows = connection.execute(
        """
        SELECT * FROM review_intervals
        WHERE normalized_media_id = ?
        ORDER BY start_frame, end_frame, created_at, id
        """,
        (normalized_media_id,),
    ).fetchall()
    return [_interval_from_row(row) for row in rows]


def create_review_interval(
    connection: sqlite3.Connection,
    normalized_media_id: str,
    *,
    start_frame: int,
    end_frame: int,
    frame_count: int,
) -> ReviewInterval:
    _validate_frames(start_frame, end_frame, frame_count)
    identifier = str(uuid.uuid4())
    connection.execute(
        """
        INSERT INTO review_intervals (
            id, normalized_media_id, start_frame, end_frame
        ) VALUES (?, ?, ?, ?)
        """,
        (identifier, normalized_media_id, start_frame, end_frame),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM review_intervals WHERE id = ?", (identifier,)
    ).fetchone()
    if row is None:
        raise RuntimeError("o intervalo recém-criado não foi encontrado")
    return _interval_from_row(row)


def update_review_interval(
    connection: sqlite3.Connection,
    normalized_media_id: str,
    interval_id: str,
    *,
    start_frame: int,
    end_frame: int,
    frame_count: int,
) -> ReviewInterval:
    _validate_frames(start_frame, end_frame, frame_count)
    cursor = connection.execute(
        """
        UPDATE review_intervals
        SET start_frame = ?, end_frame = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
        WHERE id = ? AND normalized_media_id = ?
        """,
        (start_frame, end_frame, interval_id, normalized_media_id),
    )
    if cursor.rowcount == 0:
        connection.rollback()
        raise KeyError(interval_id)
    connection.commit()
    row = connection.execute(
        "SELECT * FROM review_intervals WHERE id = ?", (interval_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError("o intervalo atualizado não foi encontrado")
    return _interval_from_row(row)


def delete_review_interval(
    connection: sqlite3.Connection,
    normalized_media_id: str,
    interval_id: str,
) -> bool:
    cursor = connection.execute(
        """
        DELETE FROM review_intervals
        WHERE id = ? AND normalized_media_id = ?
        """,
        (interval_id, normalized_media_id),
    )
    connection.commit()
    return cursor.rowcount > 0
