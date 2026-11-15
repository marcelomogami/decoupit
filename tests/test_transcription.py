import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from decoupit.transcription import (
    ALIGN_MODEL_FILENAME,
    MODEL_REVISION,
    TranscriptionError,
    resolve_model_path,
    resolve_runtime_python,
    transcribe_media,
    write_result,
)


def _runtime_payload(*, words: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    aligned_segments: list[dict[str, Any]] = []
    transcription_segments: list[dict[str, Any]] = []
    if words is not None:
        transcription_segments.append(
            {
                "start": 0.1,
                "end": 0.82,
                "text": " Hello world",
                "avg_logprob": -0.1,
            }
        )
        aligned_segments.append(
            {
                "start": 0.12,
                "end": 0.8,
                "text": " Hello world",
                "words": words,
                "avg_logprob": -0.1,
            }
        )
    return {
        "profile": {
            "libraries": {
                "faster-whisper": "1.2.1",
                "pyannote.audio": "4.0.7",
                "torch": "2.8.0",
                "torchaudio": "2.8.0",
                "whisperx": "3.8.6",
            }
        },
        "metrics": {"total_seconds": 1.25},
        "transcription": {
            "language": "en",
            "language_probability": 0.995,
            "duration": 1.0,
            "duration_after_vad": 0.72 if words is not None else 0.0,
            "segments": transcription_segments,
        },
        "aligned": {"segments": aligned_segments, "word_segments": words or []},
    }


def _fake_runtime(
    tmp_path: Path,
    payload: dict[str, Any],
) -> tuple[Path, Path, Path, str, Any]:
    runtime_python = tmp_path / "runtime" / "bin" / "python"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text("")
    runtime_python.chmod(0o755)
    model_path = tmp_path / "model"
    model_path.mkdir()
    (model_path / "model.bin").write_bytes(b"model")
    (model_path / "config.json").write_text("{}")
    align_model_directory = tmp_path / "align"
    align_model_directory.mkdir()
    align_model_bytes = b"align-model"
    (align_model_directory / ALIGN_MODEL_FILENAME).write_bytes(align_model_bytes)
    align_model_hash = hashlib.sha256(align_model_bytes).hexdigest()

    def run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        output_path = Path(command[command.index("--output") + 1])
        output_path.write_text(json.dumps(payload))
        return subprocess.CompletedProcess(command, 0, "", "")

    return (
        runtime_python,
        model_path,
        align_model_directory,
        align_model_hash,
        run,
    )


def test_transcription_uses_isolated_whisperx_and_aligned_integer_timestamps(
    tmp_path: Path,
) -> None:
    media_path = tmp_path / "normalized.mp4"
    media_path.write_bytes(b"media")
    words = [
        {"start": 0.12, "end": 0.44, "word": "Hello", "score": 0.91},
        {"start": 0.44, "end": 0.8, "word": "world", "score": 0.87},
    ]
    payload = _runtime_payload(words=words)
    runtime_python, model_path, align_dir, align_hash, run = _fake_runtime(
        tmp_path, payload
    )

    result = transcribe_media(
        media_path,
        runtime_python=runtime_python,
        model_path=model_path,
        align_model_directory=align_dir,
        alignment_model_sha256=align_hash,
        command_runner=run,
    )

    assert result.language == "en"
    assert result.language_probability == 0.995
    assert result.duration_us == 1_000_000
    assert result.segments[0].words[0].start_us == 120_000
    assert result.segments[0].words[1].end_us == 800_000
    assert [word.text for word in result.segments[0].words] == [" Hello", " world"]
    assert result.profile["pipeline"] == "whisperx"
    assert result.profile["model_revision"] == MODEL_REVISION
    assert result.profile["chunk_size"] == 10

    output_path = tmp_path / "transcript.raw.json"
    write_result(output_path, result)
    written = json.loads(output_path.read_text())
    assert written["transcription"]["segments"][0]["start"] == 0.1
    assert written["aligned"]["segments"][0]["words"][0]["start"] == 0.12
    assert written["result"]["segments"][0]["words"][0]["text"] == " Hello"
    assert not output_path.with_suffix(".json.part").exists()


def test_transcription_rejects_aligned_word_without_timestamps(tmp_path: Path) -> None:
    media_path = tmp_path / "normalized.mp4"
    media_path.write_bytes(b"media")
    payload = _runtime_payload(words=[{"word": "text", "score": 0.5}])
    runtime_python, model_path, align_dir, align_hash, run = _fake_runtime(
        tmp_path, payload
    )

    with pytest.raises(TranscriptionError, match="timestamps alinhados"):
        transcribe_media(
            media_path,
            runtime_python=runtime_python,
            model_path=model_path,
            align_model_directory=align_dir,
            alignment_model_sha256=align_hash,
            command_runner=run,
        )


def test_transcription_accepts_media_without_detected_speech(tmp_path: Path) -> None:
    media_path = tmp_path / "silence.mp4"
    media_path.write_bytes(b"media")
    payload = _runtime_payload(words=None)
    runtime_python, model_path, align_dir, align_hash, run = _fake_runtime(
        tmp_path, payload
    )

    result = transcribe_media(
        media_path,
        runtime_python=runtime_python,
        model_path=model_path,
        align_model_directory=align_dir,
        alignment_model_sha256=align_hash,
        command_runner=run,
    )

    assert result.segments == ()


def test_transcription_rejects_unexpected_runtime_versions(tmp_path: Path) -> None:
    media_path = tmp_path / "normalized.mp4"
    media_path.write_bytes(b"media")
    payload = _runtime_payload(words=[])
    payload["profile"]["libraries"]["whisperx"] = "unexpected"
    runtime_python, model_path, align_dir, align_hash, run = _fake_runtime(
        tmp_path, payload
    )

    with pytest.raises(TranscriptionError, match="versões diferentes"):
        transcribe_media(
            media_path,
            runtime_python=runtime_python,
            model_path=model_path,
            align_model_directory=align_dir,
            alignment_model_sha256=align_hash,
            command_runner=run,
        )


def test_model_resolution_falls_back_to_home_cache(tmp_path: Path) -> None:
    model_path = (
        tmp_path
        / ".cache"
        / "huggingface"
        / "hub"
        / "models--Systran--faster-whisper-medium"
        / "snapshots"
        / MODEL_REVISION
    )
    model_path.mkdir(parents=True)
    (model_path / "model.bin").write_bytes(b"model")
    (model_path / "config.json").write_text("{}")

    assert (
        resolve_model_path(
            environment={"XDG_CACHE_HOME": str(tmp_path / "isolated")},
            home=tmp_path,
        )
        == model_path
    )


def test_runtime_resolution_accepts_explicit_isolated_python(tmp_path: Path) -> None:
    runtime_python = tmp_path / "whisperx" / "bin" / "python"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.write_text("")
    runtime_python.chmod(0o755)

    assert (
        resolve_runtime_python(
            environment={"DECOUPIT_WHISPERX_PYTHON": str(runtime_python)},
            home=tmp_path,
        )
        == runtime_python.resolve()
    )


def test_runtime_resolution_preserves_virtualenv_python_symlink(
    tmp_path: Path,
) -> None:
    base_python = tmp_path / "base-python"
    base_python.write_text("")
    base_python.chmod(0o755)
    runtime_python = tmp_path / "venv" / "bin" / "python"
    runtime_python.parent.mkdir(parents=True)
    runtime_python.symlink_to(base_python)

    assert (
        resolve_runtime_python(
            environment={"DECOUPIT_WHISPERX_PYTHON": str(runtime_python)},
            home=tmp_path,
        )
        == runtime_python.absolute()
    )
