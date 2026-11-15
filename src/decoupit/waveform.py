"""Compact waveform generation without an intermediate audio file."""

from __future__ import annotations

import argparse
import os
import sqlite3
import subprocess
import sys
import tempfile
import uuid
from array import array
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from decoupit.database import connect_database
from decoupit.normalization import get_normalized_media
from decoupit.resource_lock import exclusive_heavy_job
from decoupit.sources import get_source

SAMPLE_RATE = 8000
SAMPLES_PER_POINT = 160
FORMAT_VERSION = 1

PcmDecoder = Callable[[Path], Iterable[bytes]]


class WaveformError(RuntimeError):
    """Raised when waveform data cannot be generated or published."""


@dataclass(frozen=True, slots=True)
class Waveform:
    id: str
    normalized_media_id: str
    path: Path
    size_bytes: int
    point_count: int
    sample_rate: int
    samples_per_point: int
    format_version: int
    created_at: str


def build_ffmpeg_command(media_path: Path) -> tuple[str, ...]:
    return (
        "ffmpeg",
        "-hide_banner",
        "-v",
        "error",
        "-xerror",
        "-nostdin",
        "-i",
        str(media_path),
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        str(SAMPLE_RATE),
        "-f",
        "s16le",
        "pipe:1",
    )


def decode_pcm(media_path: Path) -> Iterator[bytes]:
    with tempfile.TemporaryFile() as error_file:
        try:
            process = subprocess.Popen(
                build_ffmpeg_command(media_path),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=error_file,
                close_fds=True,
            )
        except OSError as error:
            raise WaveformError(f"não foi possível executar FFmpeg: {error}") from error
        if process.stdout is None:
            process.kill()
            process.wait()
            raise WaveformError("FFmpeg não disponibilizou o áudio decodificado")
        try:
            while chunk := process.stdout.read(64 * 1024):
                yield chunk
            return_code = process.wait()
        except BaseException:
            process.terminate()
            process.wait()
            raise
        if return_code != 0:
            error_file.seek(0)
            detail = error_file.read(64 * 1024).decode(errors="replace").strip()
            raise WaveformError(f"FFmpeg falhou: {detail or 'erro sem detalhes'}")


def _waveform_from_row(row: sqlite3.Row) -> Waveform:
    return Waveform(
        id=row["id"],
        normalized_media_id=row["normalized_media_id"],
        path=Path(row["absolute_path"]),
        size_bytes=row["size_bytes"],
        point_count=row["point_count"],
        sample_rate=row["sample_rate"],
        samples_per_point=row["samples_per_point"],
        format_version=row["format_version"],
        created_at=row["created_at"],
    )


def get_waveform(
    connection: sqlite3.Connection, normalized_media_id: str
) -> Waveform | None:
    row = connection.execute(
        "SELECT * FROM waveforms WHERE normalized_media_id = ?",
        (normalized_media_id,),
    ).fetchone()
    return None if row is None else _waveform_from_row(row)


def get_waveform_by_id(connection: sqlite3.Connection, waveform_id: str) -> Waveform:
    row = connection.execute(
        "SELECT * FROM waveforms WHERE id = ?", (waveform_id,)
    ).fetchone()
    if row is None:
        raise KeyError(waveform_id)
    return _waveform_from_row(row)


def _write_waveform(path: Path, chunks: Iterable[bytes]) -> int:
    point_count = 0
    first_point = True
    pending = array("h")
    trailing_byte = b""
    with path.open("x", encoding="utf-8") as output:
        output.write(
            '{"version":1,"sample_rate":8000,"samples_per_point":160,"peaks":['
        )
        for chunk in chunks:
            payload = trailing_byte + chunk
            if len(payload) % 2:
                trailing_byte = payload[-1:]
                payload = payload[:-1]
            else:
                trailing_byte = b""
            samples = array("h")
            samples.frombytes(payload)
            if sys.byteorder != "little":
                samples.byteswap()
            pending.extend(samples)
            complete_samples = (len(pending) // SAMPLES_PER_POINT) * SAMPLES_PER_POINT
            for offset in range(0, complete_samples, SAMPLES_PER_POINT):
                bucket = pending[offset : offset + SAMPLES_PER_POINT]
                if not first_point:
                    output.write(",")
                output.write(f"[{min(bucket)},{max(bucket)}]")
                first_point = False
                point_count += 1
            pending = pending[complete_samples:]
        if trailing_byte:
            raise WaveformError("FFmpeg retornou uma amostra de áudio incompleta")
        if pending:
            if not first_point:
                output.write(",")
            output.write(f"[{min(pending)},{max(pending)}]")
            point_count += 1
        if point_count == 0:
            raise WaveformError("a mídia normalizada não produziu amostras de áudio")
        output.write(f'],"point_count":{point_count}}}')
        output.flush()
        os.fsync(output.fileno())
    return point_count


def _insert_waveform(
    connection: sqlite3.Connection,
    normalized_media_id: str,
    path: Path,
    point_count: int,
) -> Waveform:
    identifier = str(uuid.uuid4())
    connection.execute(
        """
        INSERT INTO waveforms (
            id, normalized_media_id, absolute_path, size_bytes, point_count,
            sample_rate, samples_per_point, format_version
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            identifier,
            normalized_media_id,
            str(path),
            path.stat().st_size,
            point_count,
            SAMPLE_RATE,
            SAMPLES_PER_POINT,
            FORMAT_VERSION,
        ),
    )
    connection.commit()
    return get_waveform_by_id(connection, identifier)


def generate_waveform(
    database_path: Path,
    cache_root: Path,
    source_id: str,
    *,
    decoder: PcmDecoder = decode_pcm,
) -> Waveform:
    with exclusive_heavy_job(database_path):
        with connect_database(database_path) as connection:
            source = get_source(connection, source_id)
            normalized = get_normalized_media(connection, source_id)
            if normalized is None:
                raise WaveformError("a mídia normalizada ainda não está disponível")
            existing = get_waveform(connection, normalized.id)
            if existing is not None and existing.path.is_file():
                raise WaveformError("a mídia já possui waveform")
            if existing is not None:
                connection.execute("DELETE FROM waveforms WHERE id = ?", (existing.id,))
                connection.commit()
        if not normalized.path.is_file():
            raise WaveformError("a mídia normalizada não está acessível")
        if normalized.path.stat().st_size != normalized.size_bytes:
            raise WaveformError("a mídia normalizada mudou desde a publicação")

        output_directory = (
            cache_root / "projects" / source.project_id / "media" / source.id
        )
        output_directory.mkdir(parents=True, exist_ok=True)
        final_path = output_directory / "waveform-v1.json"
        partial_path = output_directory / "waveform-v1.part.json"
        partial_path.unlink(missing_ok=True)
        try:
            point_count = _write_waveform(partial_path, decoder(normalized.path))
            os.replace(partial_path, final_path)
            with connect_database(database_path) as connection:
                return _insert_waveform(
                    connection, normalized.id, final_path, point_count
                )
        except Exception:
            partial_path.unlink(missing_ok=True)
            if final_path.is_file():
                final_path.unlink()
            raise


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Gera o waveform de uma mídia.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--cache-root", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    arguments = parser.parse_args(argv)
    generate_waveform(arguments.database, arguments.cache_root, arguments.source_id)


if __name__ == "__main__":
    main()
