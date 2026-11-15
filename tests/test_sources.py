import json
from pathlib import Path

from decoupit.database import connect_database, initialize_database
from decoupit.media import SourceInspection
from decoupit.projects import create_project
from decoupit.sources import create_source, list_sources


def test_source_identity_and_metadata_are_persisted(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    initialize_database(database_path)
    inspection = SourceInspection(
        path=tmp_path / "source.mp4",
        device=1,
        inode=2,
        size_bytes=3,
        modified_at_ns=4,
        format_name="mov,mp4",
        duration_us=5_000_000,
        video_codec="h264",
        width=1920,
        height=1080,
        nominal_frame_rate=(30, 1),
        average_frame_rate=(30000, 1001),
        frame_rate_mode="variable",
        audio_codec="aac",
        sample_rate=48000,
        channels=2,
        probe_json=json.dumps({"streams": []}),
    )

    with connect_database(database_path) as connection:
        project = create_project(connection, name="Projeto")
        created = create_source(connection, project.id, inspection)
        listed = list_sources(connection, project.id)

    assert listed == [created]
    assert created.path == inspection.path
    assert created.frame_rate_mode == "variable"
    assert created.size_bytes == 3
