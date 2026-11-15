import json
from array import array
from pathlib import Path

from fastapi.testclient import TestClient

from decoupit.database import connect_database, initialize_database
from decoupit.media import SourceInspection
from decoupit.paths import AppPaths
from decoupit.projects import create_project
from decoupit.sources import create_source
from decoupit.waveform import generate_waveform, get_waveform
from decoupit.web import create_app


def test_waveform_is_streamed_and_published_without_audio_file(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "data" / "decoupit.sqlite3"
    cache_root = tmp_path / "cache"
    source_path = tmp_path / "source.mp4"
    normalized_path = tmp_path / "normalized.mp4"
    source_path.write_bytes(b"source")
    normalized_path.write_bytes(b"normalized")
    initialize_database(database_path)
    stat = source_path.stat()
    inspection = SourceInspection(
        path=source_path,
        device=stat.st_dev,
        inode=stat.st_ino,
        size_bytes=stat.st_size,
        modified_at_ns=stat.st_mtime_ns,
        format_name="mp4",
        duration_us=1_000_000,
        video_codec="h264",
        width=1920,
        height=1080,
        nominal_frame_rate=(30, 1),
        average_frame_rate=(30, 1),
        frame_rate_mode="constant",
        audio_codec="aac",
        sample_rate=48000,
        channels=2,
        probe_json="{}",
    )
    with connect_database(database_path) as connection:
        project = create_project(connection, name="Waveform")
        source = create_source(connection, project.id, inspection)
        connection.execute(
            """
            INSERT INTO normalized_media (
                id, source_id, absolute_path, size_bytes, duration_us,
                video_codec, frame_rate_num, frame_rate_den, profile_json
            ) VALUES ('normalized-1', ?, ?, ?, 1000000, 'h264', 30, 1, '{}')
            """,
            (source.id, str(normalized_path), normalized_path.stat().st_size),
        )
        connection.commit()

    samples = array("h", [-100, 200] * 80 + [-300, 400] * 80 + [50, 60])
    raw_pcm = samples.tobytes()

    def decoder(_: Path) -> list[bytes]:
        return [raw_pcm[:317], raw_pcm[317:]]

    waveform = generate_waveform(database_path, cache_root, source.id, decoder=decoder)

    assert json.loads(waveform.path.read_text()) == {
        "version": 1,
        "sample_rate": 8000,
        "samples_per_point": 160,
        "peaks": [[-100, 200], [-300, 400], [50, 60]],
        "point_count": 3,
    }
    assert waveform.point_count == 3
    assert list(cache_root.rglob("*.wav")) == []
    assert list(cache_root.rglob("*.part.json")) == []
    with connect_database(database_path) as connection:
        assert get_waveform(connection, "normalized-1") == waveform
    app = create_app(paths=AppPaths(database_path.parent, cache_root))
    with TestClient(app) as client:
        response = client.get(f"/api/waveforms/{waveform.id}/data")
    assert response.status_code == 200
    assert response.json()["point_count"] == 3
