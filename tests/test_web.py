from pathlib import Path

from fastapi.testclient import TestClient

from decoupit.database import connect_database
from decoupit.media import SourceInspection
from decoupit.paths import resolve_app_paths
from decoupit.web import create_app


def test_status_page_and_health_endpoint(tmp_path: Path) -> None:
    paths = resolve_app_paths(environment={}, home=tmp_path)

    with TestClient(create_app(paths=paths)) as client:
        page = client.get("/")
        health = client.get("/api/health")

    assert page.status_code == 200
    assert "DecoupIt" in page.text
    assert "0.4.0.dev0" in page.text
    assert health.status_code == 200
    assert health.json() == {"status": "ready", "version": "0.4.0.dev0"}
    assert paths.data.is_dir()
    assert paths.cache.is_dir()
    assert paths.database.is_file()


def test_unknown_host_is_rejected(tmp_path: Path) -> None:
    app = create_app(paths=resolve_app_paths(environment={}, home=tmp_path))

    with TestClient(app, base_url="http://example.invalid") as client:
        response = client.get("/")

    assert response.status_code == 400


def test_create_project_and_list_it_after_restart(tmp_path: Path) -> None:
    paths = resolve_app_paths(environment={}, home=tmp_path)

    with TestClient(create_app(paths=paths)) as client:
        created = client.post(
            "/api/projects",
            json={"name": "  Projeto vazio  "},
            headers={"Origin": "http://testserver"},
        )

    with TestClient(create_app(paths=paths)) as client:
        listed = client.get("/api/projects")

    assert created.status_code == 201
    assert created.json()["name"] == "Projeto vazio"
    assert created.json()["status"] == "active"
    assert listed.status_code == 200
    assert listed.json() == [created.json()]


def test_cross_origin_project_creation_is_rejected(tmp_path: Path) -> None:
    paths = resolve_app_paths(environment={}, home=tmp_path)

    with TestClient(create_app(paths=paths)) as client:
        rejected = client.post(
            "/api/projects",
            json={"name": "Não deve existir"},
            headers={"Origin": "https://example.invalid"},
        )
        listed = client.get("/api/projects")

    assert rejected.status_code == 403
    assert listed.json() == []


def test_blank_project_name_is_rejected(tmp_path: Path) -> None:
    paths = resolve_app_paths(environment={}, home=tmp_path)

    with TestClient(create_app(paths=paths)) as client:
        response = client.post(
            "/api/projects",
            json={"name": "   "},
            headers={"Origin": "http://testserver"},
        )

    assert response.status_code == 422


def test_register_and_list_source_media(tmp_path: Path) -> None:
    paths = resolve_app_paths(environment={}, home=tmp_path)
    source_path = tmp_path / "phone.mp4"
    source_path.write_bytes(b"source")

    def fake_probe(path: Path) -> SourceInspection:
        stat = path.resolve().stat()
        return SourceInspection(
            path=path.resolve(),
            device=stat.st_dev,
            inode=stat.st_ino,
            size_bytes=stat.st_size,
            modified_at_ns=stat.st_mtime_ns,
            format_name="mov,mp4",
            duration_us=1_000_000,
            video_codec="h264",
            width=1920,
            height=1080,
            nominal_frame_rate=(30, 1),
            average_frame_rate=(30000, 1001),
            frame_rate_mode="variable",
            audio_codec="aac",
            sample_rate=48000,
            channels=2,
            probe_json="{}",
        )

    with TestClient(create_app(paths=paths, media_probe=fake_probe)) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Projeto"},
            headers={"Origin": "http://testserver"},
        ).json()
        created = client.post(
            f"/api/projects/{project['id']}/sources",
            json={"path": str(source_path)},
            headers={"Origin": "http://testserver"},
        )
        listed = client.get(f"/api/projects/{project['id']}/sources")

    assert created.status_code == 201
    assert created.json()["path"] == str(source_path.resolve())
    assert created.json()["frame_rate_mode"] == "variable"
    assert listed.json() == [created.json()]
    assert source_path.read_bytes() == b"source"


def test_register_source_rejects_unknown_project(tmp_path: Path) -> None:
    paths = resolve_app_paths(environment={}, home=tmp_path)

    with TestClient(create_app(paths=paths)) as client:
        response = client.post(
            "/api/projects/missing/sources",
            json={"path": str(tmp_path / "missing.mp4")},
            headers={"Origin": "http://testserver"},
        )

    assert response.status_code == 404


def test_enqueue_normalization_and_query_job(tmp_path: Path) -> None:
    paths = resolve_app_paths(environment={}, home=tmp_path)
    source_path = tmp_path / "phone.mp4"
    source_path.write_bytes(b"source")

    def fake_probe(path: Path) -> SourceInspection:
        stat = path.resolve().stat()
        return SourceInspection(
            path=path.resolve(),
            device=stat.st_dev,
            inode=stat.st_ino,
            size_bytes=stat.st_size,
            modified_at_ns=stat.st_mtime_ns,
            format_name="mov,mp4",
            duration_us=1_000_000,
            video_codec="h264",
            width=1920,
            height=1080,
            nominal_frame_rate=(30, 1),
            average_frame_rate=(30000, 1001),
            frame_rate_mode="variable",
            audio_codec="aac",
            sample_rate=48000,
            channels=2,
            probe_json="{}",
        )

    with TestClient(create_app(paths=paths, media_probe=fake_probe)) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Projeto"},
            headers={"Origin": "http://testserver"},
        ).json()
        source = client.post(
            f"/api/projects/{project['id']}/sources",
            json={"path": str(source_path)},
            headers={"Origin": "http://testserver"},
        ).json()
        endpoint = f"/api/projects/{project['id']}/sources/{source['id']}/normalization"
        created = client.post(endpoint, headers={"Origin": "http://testserver"})
        duplicate = client.post(endpoint, headers={"Origin": "http://testserver"})
        queried = client.get(f"/api/jobs/{created.json()['id']}")
        missing_output = client.get(endpoint)

    assert created.status_code == 202
    assert created.json()["kind"] == "media.normalize_cfr30"
    assert created.json()["state"] == "queued"
    assert duplicate.json()["id"] == created.json()["id"]
    assert queried.json() == created.json()
    assert missing_output.status_code == 404


def test_enqueue_waveform_only_after_normalization(tmp_path: Path) -> None:
    paths = resolve_app_paths(environment={}, home=tmp_path)
    source_path = tmp_path / "phone.mp4"
    normalized_path = tmp_path / "normalized.mp4"
    source_path.write_bytes(b"source")
    normalized_path.write_bytes(b"normalized")

    def fake_probe(path: Path) -> SourceInspection:
        stat = path.resolve().stat()
        return SourceInspection(
            path=path.resolve(),
            device=stat.st_dev,
            inode=stat.st_ino,
            size_bytes=stat.st_size,
            modified_at_ns=stat.st_mtime_ns,
            format_name="mov,mp4",
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

    with TestClient(create_app(paths=paths, media_probe=fake_probe)) as client:
        project = client.post(
            "/api/projects",
            json={"name": "Projeto"},
            headers={"Origin": "http://testserver"},
        ).json()
        source = client.post(
            f"/api/projects/{project['id']}/sources",
            json={"path": str(source_path)},
            headers={"Origin": "http://testserver"},
        ).json()
        endpoint = f"/api/projects/{project['id']}/sources/{source['id']}/waveform"
        too_early = client.post(endpoint, headers={"Origin": "http://testserver"})
        with connect_database(paths.database) as connection:
            connection.execute(
                """
                INSERT INTO normalized_media (
                    id, source_id, absolute_path, size_bytes, duration_us,
                    video_codec, frame_rate_num, frame_rate_den, profile_json
                ) VALUES ('normalized-1', ?, ?, ?, 1000000, 'h264', 30, 1, '{}')
                """,
                (
                    source["id"],
                    str(normalized_path),
                    normalized_path.stat().st_size,
                ),
            )
            connection.commit()
        review = client.get(f"/projects/{project['id']}/sources/{source['id']}/review")
        media = client.get(
            "/api/normalized-media/normalized-1/content",
            headers={"Range": "bytes=2-5"},
        )
        review_script = client.get("/static/review.js")
        created = client.post(endpoint, headers={"Origin": "http://testserver"})
        duplicate = client.post(endpoint, headers={"Origin": "http://testserver"})

    assert too_early.status_code == 409
    assert review.status_code == 200
    assert 'src="/api/normalized-media/normalized-1/content"' in review.text
    assert 'data-fps="30"' in review.text
    assert 'data-frame-count="30"' in review.text
    assert 'data-transcript-url=""' in review.text
    assert (
        f'data-review-intervals-url="/api/projects/{project["id"]}/sources/'
        f'{source["id"]}/review-intervals"' in review.text
    )
    assert 'id="transcript-query"' in review.text
    assert 'id="previous-match"' in review.text
    assert 'id="next-match"' in review.text
    assert media.status_code == 206
    assert media.content == b"rmal"
    assert media.headers["content-range"] == "bytes 2-5/10"
    assert media.headers["accept-ranges"] == "bytes"
    assert media.headers["content-type"] == "video/mp4"
    assert review_script.status_code == 200
    assert "requestVideoFrameCallback" in review_script.text
    assert "updateTranscript" in review_script.text
    assert "findSearchMatches" in review_script.text
    assert "selectSearchMatch" in review_script.text
    assert "renderReviewIntervals" in review_script.text
    assert "createReviewInterval" in review_script.text
    assert "intervalClassificationField" in review_script.text
    assert '"primary", "Principal"' in review_script.text
    assert "playReviewIntervalContext" in review_script.text
    assert "contextFrameMargin = 90" in review_script.text
    assert "frameRoundingTolerance" in review_script.text
    assert "shortcutUsesEditableTarget" in review_script.text
    assert "togglePlayback" in review_script.text
    assert "Atalhos:" in review.text
    assert "requestReviewIntervalSave" in review_script.text
    assert "autoSaveDelayMs = 600" in review_script.text
    assert "Alterações em intervalos são salvas automaticamente." in review.text
    assert created.status_code == 202
    assert created.json()["kind"] == "media.generate_waveform"
    assert duplicate.json()["id"] == created.json()["id"]
