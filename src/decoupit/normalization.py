"""CFR 30 edit-master generation and atomic publication."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from decoupit.database import connect_database
from decoupit.media import SourceInspection, probe_source
from decoupit.resource_lock import exclusive_heavy_job
from decoupit.sources import SourceMedia, get_source

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]
MediaProbe = Callable[[Path], SourceInspection]

PROFILE = {
    "name": "cfr30_nvenc_v1",
    "container": "mp4",
    "video_codec": "h264_nvenc",
    "frame_rate": "30/1",
    "pixel_format": "yuv420p",
    "gop": 2,
    "b_frames": 0,
    "audio_codec": "aac",
    "audio_bitrate": "256k",
    "audio_sample_rate": 48000,
}


class NormalizationError(RuntimeError):
    """Raised when a normalized edit master cannot be safely published."""


@dataclass(frozen=True, slots=True)
class NormalizedMedia:
    id: str
    source_id: str
    path: Path
    size_bytes: int
    duration_us: int
    frame_count: int | None
    video_codec: str
    created_at: str


def build_ffmpeg_command(source: Path, partial_output: Path) -> tuple[str, ...]:
    return (
        "ffmpeg",
        "-hide_banner",
        "-v",
        "error",
        "-nostdin",
        "-y",
        "-i",
        str(source),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0?",
        "-vf",
        "fps=30",
        "-c:v",
        "h264_nvenc",
        "-b:v",
        "0",
        "-rc",
        "cbr",
        "-g",
        "2",
        "-bf",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "256k",
        "-ar",
        "48000",
        "-fps_mode",
        "cfr",
        "-movflags",
        "+faststart",
        str(partial_output),
    )


def _normalized_from_row(row: sqlite3.Row) -> NormalizedMedia:
    return NormalizedMedia(
        id=row["id"],
        source_id=row["source_id"],
        path=Path(row["absolute_path"]),
        size_bytes=row["size_bytes"],
        duration_us=row["duration_us"],
        frame_count=row["frame_count"],
        video_codec=row["video_codec"],
        created_at=row["created_at"],
    )


def get_normalized_media(
    connection: sqlite3.Connection, source_id: str
) -> NormalizedMedia | None:
    row = connection.execute(
        "SELECT * FROM normalized_media WHERE source_id = ?", (source_id,)
    ).fetchone()
    return None if row is None else _normalized_from_row(row)


def _verify_source_identity(source: SourceMedia) -> None:
    try:
        stat = source.path.stat()
    except OSError as error:
        raise NormalizationError("o vídeo bruto não está acessível") from error
    identity = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)
    expected = (
        source.device,
        source.inode,
        source.size_bytes,
        source.modified_at_ns,
    )
    if identity != expected:
        raise NormalizationError("o vídeo bruto mudou desde o cadastro")


def _validate_output(source: SourceMedia, output: SourceInspection) -> None:
    if output.frame_rate_mode != "constant":
        raise NormalizationError("a saída não possui taxa de quadros constante")
    if output.nominal_frame_rate != (30, 1) or output.average_frame_rate != (30, 1):
        raise NormalizationError("a saída não possui 30 fps exatos")
    if output.video_codec != "h264":
        raise NormalizationError("a saída não usa vídeo H.264")
    if (output.width, output.height) != (source.width, source.height):
        raise NormalizationError("a resolução da saída difere do bruto")
    if source.audio_codec is not None and output.audio_codec is None:
        raise NormalizationError("a saída perdeu o stream de áudio")
    if (
        source.duration_us is not None
        and output.duration_us is not None
        and abs(output.duration_us - source.duration_us) > 34_000
    ):
        raise NormalizationError("a duração da saída difere mais de um quadro")


def _insert_normalized_media(
    connection: sqlite3.Connection,
    source_id: str,
    path: Path,
    inspection: SourceInspection,
) -> NormalizedMedia:
    if inspection.duration_us is None:
        raise NormalizationError("a saída não informa duração")
    identifier = str(uuid.uuid4())
    connection.execute(
        """
        INSERT INTO normalized_media (
            id, source_id, absolute_path, size_bytes, duration_us, frame_count,
            video_codec, frame_rate_num, frame_rate_den, profile_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 30, 1, ?)
        """,
        (
            identifier,
            source_id,
            str(path),
            path.stat().st_size,
            inspection.duration_us,
            inspection.frame_count,
            inspection.video_codec,
            json.dumps(PROFILE, sort_keys=True, separators=(",", ":")),
        ),
    )
    connection.commit()
    row = connection.execute(
        "SELECT * FROM normalized_media WHERE id = ?", (identifier,)
    ).fetchone()
    if row is None:
        raise RuntimeError("a mídia normalizada não foi encontrada")
    return _normalized_from_row(row)


def normalize_source(
    database_path: Path,
    source_id: str,
    *,
    runner: CommandRunner = subprocess.run,
    probe: MediaProbe = probe_source,
) -> NormalizedMedia:
    with exclusive_heavy_job(database_path):
        return _normalize_source_locked(
            database_path, source_id, runner=runner, probe=probe
        )


def _normalize_source_locked(
    database_path: Path,
    source_id: str,
    *,
    runner: CommandRunner,
    probe: MediaProbe,
) -> NormalizedMedia:
    with connect_database(database_path) as connection:
        source = get_source(connection, source_id)
        if get_normalized_media(connection, source_id) is not None:
            raise NormalizationError("a mídia já possui uma versão normalizada")
    _verify_source_identity(source)

    output_directory = (
        database_path.parent / "projects" / source.project_id / "media" / source.id
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    final_path = output_directory / "edit-master-cfr30.mp4"
    partial_path = output_directory / "edit-master-cfr30.part.mp4"
    partial_path.unlink(missing_ok=True)
    command = build_ffmpeg_command(source.path, partial_path)
    try:
        result = runner(
            command,
            capture_output=True,
            text=True,
            timeout=7200,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise NormalizationError("FFmpeg excedeu o limite de duas horas") from error
    except OSError as error:
        message = f"não foi possível executar FFmpeg: {error}"
        raise NormalizationError(message) from error
    if result.returncode != 0:
        detail = result.stderr.strip() or "erro sem detalhes"
        raise NormalizationError(f"FFmpeg falhou: {detail}")
    if not partial_path.is_file() or partial_path.stat().st_size == 0:
        raise NormalizationError("FFmpeg não produziu uma saída válida")

    inspection = probe(partial_path)
    _validate_output(source, inspection)
    os.replace(partial_path, final_path)
    try:
        with connect_database(database_path) as connection:
            return _insert_normalized_media(
                connection, source.id, final_path, inspection
            )
    except Exception:
        final_path.unlink(missing_ok=True)
        raise


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Normaliza uma mídia para CFR 30.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    arguments = parser.parse_args(argv)
    normalize_source(arguments.database, arguments.source_id)


if __name__ == "__main__":
    main()
