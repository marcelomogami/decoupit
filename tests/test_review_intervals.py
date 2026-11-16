import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from decoupit.database import connect_database, initialize_database
from decoupit.media import SourceInspection
from decoupit.paths import AppPaths
from decoupit.projects import create_project
from decoupit.review_intervals import (
    ReviewIntervalError,
    create_review_interval,
    delete_review_interval,
    list_review_intervals,
    update_review_interval,
)
from decoupit.sources import create_source
from decoupit.web import create_app


def _normalized_media(tmp_path: Path) -> tuple[Path, str, str, str]:
    database_path = tmp_path / "decoupit.sqlite3"
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
        project = create_project(connection, name="Intervalos")
        source = create_source(connection, project.id, inspection)
        connection.execute(
            """
            INSERT INTO normalized_media (
                id, source_id, absolute_path, size_bytes, duration_us, frame_count,
                video_codec, frame_rate_num, frame_rate_den, profile_json
            ) VALUES ('normalized-1', ?, ?, ?, 1000000, 30, 'h264', 30, 1, '{}')
            """,
            (source.id, str(normalized_path), normalized_path.stat().st_size),
        )
        connection.commit()
    return database_path, "normalized-1", project.id, source.id


def test_review_interval_crud_persists_frame_boundaries(tmp_path: Path) -> None:
    database_path, normalized_media_id, _, _ = _normalized_media(tmp_path)

    with connect_database(database_path) as connection:
        created = create_review_interval(
            connection,
            normalized_media_id,
            start_frame=3,
            end_frame=8,
            frame_count=30,
        )
        assert created.classification is None
        assert list_review_intervals(connection, normalized_media_id) == [created]
        updated = update_review_interval(
            connection,
            normalized_media_id,
            created.id,
            start_frame=4,
            end_frame=10,
            frame_count=30,
            classification="primary",
        )
        assert updated.classification == "primary"
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "UPDATE review_intervals SET classification = 'favorite' WHERE id = ?",
                (created.id,),
            )
        connection.rollback()

    with connect_database(database_path) as connection:
        assert list_review_intervals(connection, normalized_media_id) == [updated]
        assert (
            delete_review_interval(connection, normalized_media_id, created.id) is True
        )
        assert list_review_intervals(connection, normalized_media_id) == []
        assert (
            delete_review_interval(connection, normalized_media_id, created.id) is False
        )


@pytest.mark.parametrize(
    ("start_frame", "end_frame"),
    ((-1, 0), (4, 3), (0, 30)),
)
def test_review_interval_rejects_invalid_frame_boundaries(
    tmp_path: Path,
    start_frame: int,
    end_frame: int,
) -> None:
    database_path, normalized_media_id, _, _ = _normalized_media(tmp_path)

    with (
        connect_database(database_path) as connection,
        pytest.raises(ReviewIntervalError),
    ):
        create_review_interval(
            connection,
            normalized_media_id,
            start_frame=start_frame,
            end_frame=end_frame,
            frame_count=30,
        )


def test_review_interval_rejects_invalid_classification(tmp_path: Path) -> None:
    database_path, normalized_media_id, _, _ = _normalized_media(tmp_path)

    with (
        connect_database(database_path) as connection,
        pytest.raises(ReviewIntervalError, match="classificação"),
    ):
        create_review_interval(
            connection,
            normalized_media_id,
            start_frame=0,
            end_frame=1,
            frame_count=30,
            classification="favorite",  # type: ignore[arg-type]
        )


def test_review_interval_api_persists_updates_across_restart(tmp_path: Path) -> None:
    database_path, _, project_id, source_id = _normalized_media(tmp_path)
    paths = AppPaths(database_path.parent, tmp_path / "cache")
    endpoint = f"/api/projects/{project_id}/sources/{source_id}/review-intervals"
    export_endpoint = endpoint + "/export.csv"
    markers_endpoint = endpoint + "/markers.json"
    kdenlive_markers_endpoint = endpoint + "/kdenlive-markers.json"

    with TestClient(create_app(paths=paths)) as client:
        empty = client.get(endpoint)
        invalid = client.post(
            endpoint,
            json={"start_frame": 0, "end_frame": 30},
            headers={"Origin": "http://testserver"},
        )
        invalid_classification = client.post(
            endpoint,
            json={
                "start_frame": 0,
                "end_frame": 1,
                "classification": "favorite",
            },
            headers={"Origin": "http://testserver"},
        )
        created = client.post(
            endpoint,
            json={"start_frame": 3, "end_frame": 8},
            headers={"Origin": "http://testserver"},
        )
        interval_endpoint = f"{endpoint}/{created.json()['id']}"
        updated = client.patch(
            interval_endpoint,
            json={"start_frame": 4, "end_frame": 10},
            headers={"Origin": "http://testserver"},
        )
        classified = client.patch(
            interval_endpoint,
            json={
                "start_frame": 4,
                "end_frame": 10,
                "classification": "alternative",
            },
            headers={"Origin": "http://testserver"},
        )
        exported = client.get(export_endpoint)
        markers = client.get(markers_endpoint)
        kdenlive_markers = client.get(kdenlive_markers_endpoint)

    with TestClient(create_app(paths=paths)) as client:
        listed = client.get(endpoint)
        deleted = client.delete(
            interval_endpoint,
            headers={"Origin": "http://testserver"},
        )
        missing = client.patch(
            interval_endpoint,
            json={"start_frame": 4, "end_frame": 10},
            headers={"Origin": "http://testserver"},
        )

    assert empty.json() == []
    assert invalid.status_code == 422
    assert invalid_classification.status_code == 422
    assert created.status_code == 201
    assert created.json()["start_frame"] == 3
    assert created.json()["end_frame"] == 8
    assert created.json()["classification"] is None
    assert updated.status_code == 200
    assert updated.json()["start_frame"] == 4
    assert updated.json()["end_frame"] == 10
    assert updated.json()["classification"] is None
    assert classified.json()["classification"] == "alternative"
    assert exported.status_code == 200
    assert exported.headers["content-type"] == "text/csv; charset=utf-8"
    assert exported.headers["content-disposition"] == (
        'attachment; filename="decupagem.csv"'
    )
    assert exported.text == (
        "id_intervalo,quadro_entrada,quadro_saida,inicio_us,fim_exclusivo_us,"
        "duracao_quadros,classificacao\n"
        f"{created.json()['id']},4,10,133334,366667,7,alternativa\n"
    )
    assert markers.status_code == 200
    assert markers.headers["content-type"] == "application/json"
    assert markers.headers["content-disposition"] == (
        'attachment; filename="decupagem-markers.json"'
    )
    assert markers.json() == {
        "format": "decoupit.review-markers/v1",
        "normalized_media_id": "normalized-1",
        "frame_rate": {"numerator": 30, "denominator": 1},
        "markers": [
            {
                "id": created.json()["id"],
                "kind": "interval",
                "start_frame": 4,
                "end_frame": 10,
                "classification": "alternative",
                "category": {
                    "key": "alternative",
                    "label": "Alternativa",
                    "color": "#68a9df",
                },
            }
        ],
    }
    assert kdenlive_markers.status_code == 200
    assert kdenlive_markers.headers["content-disposition"] == (
        'attachment; filename="decupagem-kdenlive-markers.json"'
    )
    assert kdenlive_markers.json() == [
        {
            "pos": 4,
            "comment": "DecoupIt: Alternativa",
            "type": 0,
            "duration": 7,
        }
    ]
    assert listed.json() == [classified.json()]
    assert deleted.status_code == 204
    assert missing.status_code == 404
