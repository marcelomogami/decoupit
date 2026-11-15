"""Persistence for immutable source media registrations."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from decoupit.media import SourceInspection


@dataclass(frozen=True, slots=True)
class SourceMedia:
    id: str
    project_id: str
    path: Path
    device: int
    inode: int
    size_bytes: int
    modified_at_ns: int
    format_name: str
    duration_us: int | None
    video_codec: str
    width: int
    height: int
    frame_rate_mode: str
    audio_codec: str | None
    sample_rate: int | None
    channels: int | None
    created_at: str


def _source_from_row(row: sqlite3.Row) -> SourceMedia:
    return SourceMedia(
        id=row["id"],
        project_id=row["project_id"],
        path=Path(row["absolute_path"]),
        device=row["device"],
        inode=row["inode"],
        size_bytes=row["size_bytes"],
        modified_at_ns=row["modified_at_ns"],
        format_name=row["format_name"],
        duration_us=row["duration_us"],
        video_codec=row["video_codec"],
        width=row["width"],
        height=row["height"],
        frame_rate_mode=row["frame_rate_mode"],
        audio_codec=row["audio_codec"],
        sample_rate=row["sample_rate"],
        channels=row["channels"],
        created_at=row["created_at"],
    )


def create_source(
    connection: sqlite3.Connection,
    project_id: str,
    inspection: SourceInspection,
) -> SourceMedia:
    identifier = str(uuid.uuid4())
    nominal_num, nominal_den = inspection.nominal_frame_rate or (None, None)
    average_num, average_den = inspection.average_frame_rate or (None, None)
    connection.execute(
        """
        INSERT INTO source_media (
            id, project_id, absolute_path, device, inode, size_bytes,
            modified_at_ns, format_name, duration_us, video_codec, width, height,
            nominal_frame_rate_num, nominal_frame_rate_den,
            average_frame_rate_num, average_frame_rate_den, frame_rate_mode,
            audio_codec, sample_rate, channels, probe_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            identifier,
            project_id,
            str(inspection.path),
            inspection.device,
            inspection.inode,
            inspection.size_bytes,
            inspection.modified_at_ns,
            inspection.format_name,
            inspection.duration_us,
            inspection.video_codec,
            inspection.width,
            inspection.height,
            nominal_num,
            nominal_den,
            average_num,
            average_den,
            inspection.frame_rate_mode,
            inspection.audio_codec,
            inspection.sample_rate,
            inspection.channels,
            inspection.probe_json,
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM source_media WHERE id = ?", (identifier,)
    ).fetchone()
    if row is None:
        raise RuntimeError("a mídia cadastrada não foi encontrada")
    return _source_from_row(row)


def list_sources(connection: sqlite3.Connection, project_id: str) -> list[SourceMedia]:
    rows = connection.execute(
        "SELECT * FROM source_media WHERE project_id = ? ORDER BY created_at, id",
        (project_id,),
    ).fetchall()
    return [_source_from_row(row) for row in rows]


def get_source(connection: sqlite3.Connection, source_id: str) -> SourceMedia:
    row = connection.execute(
        "SELECT * FROM source_media WHERE id = ?", (source_id,)
    ).fetchone()
    if row is None:
        raise KeyError(source_id)
    return _source_from_row(row)
