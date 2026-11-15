import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from decoupit.database import connect_database, initialize_database
from decoupit.media import SourceInspection
from decoupit.paths import AppPaths
from decoupit.projects import create_project
from decoupit.sources import create_source
from decoupit.transcription import (
    TranscriptionError,
    TranscriptionResult,
    TranscriptSegment,
    TranscriptWord,
    runtime_profile,
)
from decoupit.transcripts import (
    get_transcript_document,
    get_transcription_run,
    persist_transcription,
)
from decoupit.web import create_app


def test_transcription_raw_segments_and_words_are_persisted(tmp_path: Path) -> None:
    database_path = tmp_path / "data" / "decoupit.sqlite3"
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
        project = create_project(connection, name="Transcript")
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

    paths = AppPaths(database_path.parent, tmp_path / "cache")
    endpoint = f"/api/projects/{project.id}/sources/{source.id}/transcription"
    with TestClient(create_app(paths=paths)) as client:
        missing = client.get(endpoint)
        created = client.post(endpoint, headers={"Origin": "http://testserver"})
        duplicate = client.post(endpoint, headers={"Origin": "http://testserver"})
    assert missing.status_code == 404
    assert created.status_code == 202
    assert created.json()["kind"] == "media.transcribe_words"
    assert duplicate.json()["id"] == created.json()["id"]

    result = TranscriptionResult(
        language="en",
        language_probability=0.99,
        duration_us=1_000_000,
        duration_after_vad_us=800_000,
        segments=(
            TranscriptSegment(
                start_us=100_000,
                end_us=800_000,
                text=" Hello world",
                words=(
                    TranscriptWord(100_000, 400_000, " Hello", 0.91),
                    TranscriptWord(400_000, 800_000, " world", 0.88),
                ),
            ),
        ),
        profile=runtime_profile(),
    )

    run = persist_transcription(database_path, source.id, transcriber=lambda _: result)

    assert run.segment_count == 1
    assert run.word_count == 2
    assert json.loads(run.raw_output_path.read_text())["result"]["language"] == "en"
    assert source_path.read_bytes() == b"source"
    assert normalized_path.read_bytes() == b"normalized"
    assert list(run.raw_output_path.parent.glob("*.part")) == []
    with connect_database(database_path) as connection:
        assert get_transcription_run(connection, "normalized-1") == run
        document = get_transcript_document(connection, run.id)
        segments = connection.execute("SELECT * FROM transcript_segments").fetchall()
        words = connection.execute(
            "SELECT * FROM transcript_words ORDER BY word_index"
        ).fetchall()
    assert len(segments) == 1
    assert [word["text"] for word in words] == [" Hello", " world"]
    assert document.segments[0].words[1].text == " world"

    with pytest.raises(TranscriptionError, match="já possui"):
        persist_transcription(database_path, source.id, transcriber=lambda _: result)

    with TestClient(create_app(paths=paths)) as client:
        response = client.get(endpoint)
        content = client.get(f"/api/transcriptions/{run.id}/content")
        subtitles = client.get(f"/api/transcriptions/{run.id}/subtitles.srt")
        review = client.get(f"/projects/{project.id}/sources/{source.id}/review")
        rejected = client.post(endpoint, headers={"Origin": "http://testserver"})
    assert response.status_code == 200
    assert response.json()["segment_count"] == 1
    assert response.json()["word_count"] == 2
    assert content.status_code == 200
    assert content.json()["segments"][0]["words"][0]["text"] == " Hello"
    assert subtitles.status_code == 200
    assert subtitles.headers["content-type"] == "application/x-subrip; charset=utf-8"
    assert subtitles.headers["content-disposition"] == (
        'attachment; filename="transcript.srt"'
    )
    assert subtitles.text == ("1\n00:00:00,100 --> 00:00:00,800\nHello world\n")
    assert f"/api/transcriptions/{run.id}/subtitles.srt" in review.text
    assert "Baixar SRT" in review.text
    assert rejected.status_code == 409
