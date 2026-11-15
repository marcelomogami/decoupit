"""Persistence and worker entry point for word-level transcriptions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from decoupit.database import connect_database
from decoupit.normalization import get_normalized_media
from decoupit.resource_lock import exclusive_heavy_job
from decoupit.sources import get_source
from decoupit.transcription import (
    TranscriptionError,
    TranscriptionResult,
    runtime_profile,
    transcribe_media,
    write_result,
)

Transcriber = Callable[[Path], TranscriptionResult]


@dataclass(frozen=True, slots=True)
class TranscriptionRun:
    id: str
    normalized_media_id: str
    profile_hash: str
    raw_output_path: Path
    language: str
    language_probability: float
    duration_us: int
    duration_after_vad_us: int
    segment_count: int
    word_count: int
    created_at: str


@dataclass(frozen=True, slots=True)
class TranscriptWordRecord:
    start_us: int
    end_us: int
    text: str
    probability: float


@dataclass(frozen=True, slots=True)
class TranscriptSegmentRecord:
    segment_index: int
    start_us: int
    end_us: int
    text: str
    words: tuple[TranscriptWordRecord, ...]


@dataclass(frozen=True, slots=True)
class TranscriptDocument:
    transcription_run_id: str
    language: str
    segments: tuple[TranscriptSegmentRecord, ...]


def canonical_profile(profile: dict[str, object]) -> tuple[str, str]:
    profile_json = json.dumps(
        profile, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return profile_json, hashlib.sha256(profile_json.encode()).hexdigest()


def current_profile_hash() -> str:
    return canonical_profile(runtime_profile())[1]


def _run_from_row(row: sqlite3.Row) -> TranscriptionRun:
    return TranscriptionRun(
        id=row["id"],
        normalized_media_id=row["normalized_media_id"],
        profile_hash=row["profile_hash"],
        raw_output_path=Path(row["raw_output_path"]),
        language=row["language"],
        language_probability=row["language_probability"],
        duration_us=row["duration_us"],
        duration_after_vad_us=row["duration_after_vad_us"],
        segment_count=row["segment_count"],
        word_count=row["word_count"],
        created_at=row["created_at"],
    )


def get_transcription_run(
    connection: sqlite3.Connection,
    normalized_media_id: str,
    profile_hash: str | None = None,
) -> TranscriptionRun | None:
    if profile_hash is None:
        row = connection.execute(
            """
            SELECT * FROM transcription_runs
            WHERE normalized_media_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (normalized_media_id,),
        ).fetchone()
    else:
        row = connection.execute(
            """
            SELECT * FROM transcription_runs
            WHERE normalized_media_id = ? AND profile_hash = ?
            """,
            (normalized_media_id, profile_hash),
        ).fetchone()
    return None if row is None else _run_from_row(row)


def get_transcription_run_by_id(
    connection: sqlite3.Connection, transcription_run_id: str
) -> TranscriptionRun:
    row = connection.execute(
        "SELECT * FROM transcription_runs WHERE id = ?",
        (transcription_run_id,),
    ).fetchone()
    if row is None:
        raise KeyError(transcription_run_id)
    return _run_from_row(row)


def get_transcript_document(
    connection: sqlite3.Connection, transcription_run_id: str
) -> TranscriptDocument:
    run = get_transcription_run_by_id(connection, transcription_run_id)
    segment_rows = connection.execute(
        """
        SELECT * FROM transcript_segments
        WHERE transcription_run_id = ?
        ORDER BY segment_index
        """,
        (transcription_run_id,),
    ).fetchall()
    word_rows = connection.execute(
        """
        SELECT * FROM transcript_words
        WHERE transcription_run_id = ?
        ORDER BY segment_index, word_index
        """,
        (transcription_run_id,),
    ).fetchall()
    words_by_segment: dict[int, list[TranscriptWordRecord]] = {}
    for row in word_rows:
        words_by_segment.setdefault(row["segment_index"], []).append(
            TranscriptWordRecord(
                start_us=row["start_us"],
                end_us=row["end_us"],
                text=row["text"],
                probability=row["probability"],
            )
        )
    segments = tuple(
        TranscriptSegmentRecord(
            segment_index=row["segment_index"],
            start_us=row["start_us"],
            end_us=row["end_us"],
            text=row["text"],
            words=tuple(words_by_segment.get(row["segment_index"], ())),
        )
        for row in segment_rows
    )
    return TranscriptDocument(
        transcription_run_id=run.id,
        language=run.language,
        segments=segments,
    )


def _insert_result(
    connection: sqlite3.Connection,
    normalized_media_id: str,
    raw_output_path: Path,
    result: TranscriptionResult,
) -> TranscriptionRun:
    profile_json, profile_hash = canonical_profile(result.profile)
    identifier = str(uuid.uuid4())
    word_count = sum(len(segment.words) for segment in result.segments)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO transcription_runs (
                id, normalized_media_id, profile_hash, profile_json,
                raw_output_path, language, language_probability, duration_us,
                duration_after_vad_us, segment_count, word_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                identifier,
                normalized_media_id,
                profile_hash,
                profile_json,
                str(raw_output_path),
                result.language,
                result.language_probability,
                result.duration_us,
                result.duration_after_vad_us,
                len(result.segments),
                word_count,
            ),
        )
        for segment_index, segment in enumerate(result.segments):
            connection.execute(
                """
                INSERT INTO transcript_segments (
                    transcription_run_id, segment_index, start_us, end_us, text
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    segment_index,
                    segment.start_us,
                    segment.end_us,
                    segment.text,
                ),
            )
            connection.executemany(
                """
                INSERT INTO transcript_words (
                    transcription_run_id, segment_index, word_index,
                    start_us, end_us, text, probability
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        identifier,
                        segment_index,
                        word_index,
                        word.start_us,
                        word.end_us,
                        word.text,
                        word.probability,
                    )
                    for word_index, word in enumerate(segment.words)
                ],
            )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    row = connection.execute(
        "SELECT * FROM transcription_runs WHERE id = ?", (identifier,)
    ).fetchone()
    if row is None:
        raise RuntimeError("a transcrição persistida não foi encontrada")
    return _run_from_row(row)


def persist_transcription(
    database_path: Path,
    source_id: str,
    *,
    transcriber: Transcriber = transcribe_media,
) -> TranscriptionRun:
    with exclusive_heavy_job(database_path):
        profile_hash = current_profile_hash()
        with connect_database(database_path) as connection:
            source = get_source(connection, source_id)
            normalized = get_normalized_media(connection, source_id)
            if normalized is None:
                raise TranscriptionError(
                    "a mídia normalizada ainda não está disponível"
                )
            existing = get_transcription_run(connection, normalized.id, profile_hash)
            if existing is not None:
                raise TranscriptionError("a mídia já possui esta transcrição")
        if not normalized.path.is_file():
            raise TranscriptionError("a mídia normalizada não está acessível")
        if normalized.path.stat().st_size != normalized.size_bytes:
            raise TranscriptionError("a mídia normalizada mudou desde a publicação")

        output_directory = (
            database_path.parent / "projects" / source.project_id / "models"
        )
        output_directory.mkdir(parents=True, exist_ok=True)
        raw_output_path = output_directory / f"transcript-{profile_hash[:12]}.raw.json"
        result = transcriber(normalized.path)
        result_profile_hash = canonical_profile(result.profile)[1]
        if result_profile_hash != profile_hash:
            raise TranscriptionError("o perfil executado difere do perfil solicitado")
        write_result(raw_output_path, result)
        try:
            with connect_database(database_path) as connection:
                return _insert_result(
                    connection, normalized.id, raw_output_path, result
                )
        except Exception:
            raw_output_path.unlink(missing_ok=True)
            raise


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Persiste uma transcrição local.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--source-id", required=True)
    arguments = parser.parse_args(argv)
    persist_transcription(arguments.database, arguments.source_id)


if __name__ == "__main__":
    main()
