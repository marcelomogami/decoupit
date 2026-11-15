import subprocess
from pathlib import Path

import pytest

from decoupit.database import connect_database, initialize_database
from decoupit.media import SourceInspection
from decoupit.normalization import (
    NormalizationError,
    get_normalized_media,
    normalize_source,
)
from decoupit.projects import create_project
from decoupit.sources import create_source


def _inspection(path: Path, *, frame_rate_mode: str = "constant") -> SourceInspection:
    stat = path.stat()
    rate = (30, 1) if frame_rate_mode == "constant" else (30000, 1001)
    return SourceInspection(
        path=path,
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
        average_frame_rate=rate,
        frame_rate_mode=frame_rate_mode,
        audio_codec="aac",
        sample_rate=48000,
        channels=2,
        probe_json="{}",
        frame_count=30,
    )


def _registered_source(database_path: Path, source_path: Path) -> str:
    with connect_database(database_path) as connection:
        project = create_project(connection, name="Projeto")
        source = create_source(connection, project.id, _inspection(source_path))
    return source.id


def test_normalization_is_validated_and_published_atomically(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source bytes")
    initialize_database(database_path)
    source_id = _registered_source(database_path, source_path)

    def fake_run(
        command: tuple[str, ...], **_: object
    ) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"normalized bytes")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    normalized = normalize_source(
        database_path,
        source_id,
        runner=fake_run,
        probe=lambda path: _inspection(path),
    )

    assert normalized.path.name == "edit-master-cfr30.mp4"
    assert normalized.path.read_bytes() == b"normalized bytes"
    assert not normalized.path.with_name("edit-master-cfr30.part.mp4").exists()
    assert source_path.read_bytes() == b"source bytes"
    with connect_database(database_path) as connection:
        assert get_normalized_media(connection, source_id) == normalized


def test_invalid_output_is_never_published(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    source_path = tmp_path / "source.mp4"
    source_path.write_bytes(b"source bytes")
    initialize_database(database_path)
    source_id = _registered_source(database_path, source_path)

    def fake_run(
        command: tuple[str, ...], **_: object
    ) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"invalid normalized bytes")
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    with pytest.raises(NormalizationError, match="taxa de quadros constante"):
        normalize_source(
            database_path,
            source_id,
            runner=fake_run,
            probe=lambda path: _inspection(path, frame_rate_mode="variable"),
        )

    final_outputs = list(tmp_path.glob("projects/**/edit-master-cfr30.mp4"))
    assert final_outputs == []
