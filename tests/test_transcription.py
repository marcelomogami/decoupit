import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from decoupit.transcription import (
    MODEL_ID,
    MODEL_REVISION,
    TranscriptionError,
    transcribe_media,
    write_result,
)


class FakeModel:
    def __init__(self) -> None:
        self.transcribe_arguments: tuple[str, dict[str, Any]] | None = None

    def transcribe(self, media_path: str, **kwargs: Any) -> tuple[list[Any], Any]:
        self.transcribe_arguments = media_path, kwargs
        words = [
            SimpleNamespace(start=0.12, end=0.44, word=" Hello", probability=0.91),
            SimpleNamespace(start=0.44, end=0.80, word=" world", probability=0.87),
        ]
        segments = [
            SimpleNamespace(start=0.1, end=0.82, text=" Hello world", words=words)
        ]
        info = SimpleNamespace(
            language="en",
            language_probability=0.995,
            duration=1.0,
            duration_after_vad=0.72,
        )
        return segments, info


def test_transcription_uses_validated_profile_and_integer_timestamps(
    tmp_path: Path,
) -> None:
    media_path = tmp_path / "normalized.mp4"
    media_path.write_bytes(b"media")
    model = FakeModel()
    factory_arguments: dict[str, Any] = {}

    def factory(model_name: str, **kwargs: Any) -> FakeModel:
        factory_arguments.update(model_name=model_name, **kwargs)
        return model

    result = transcribe_media(media_path, model_factory=factory)

    assert factory_arguments == {
        "model_name": MODEL_ID,
        "device": "cuda",
        "compute_type": "float16",
        "cpu_threads": 4,
        "num_workers": 1,
        "local_files_only": True,
        "revision": MODEL_REVISION,
    }
    assert model.transcribe_arguments == (
        str(media_path),
        {"beam_size": 5, "vad_filter": True, "word_timestamps": True},
    )
    assert result.language == "en"
    assert result.duration_us == 1_000_000
    assert result.segments[0].words[0].start_us == 120_000
    assert result.segments[0].words[1].end_us == 800_000
    assert result.profile["model_revision"] == MODEL_REVISION
    assert result.profile["libraries"]["faster-whisper"] == "1.2.1"

    output_path = tmp_path / "transcript.raw.json"
    write_result(output_path, result)
    written = json.loads(output_path.read_text())
    assert written["segments"][0]["words"][0]["text"] == " Hello"
    assert not output_path.with_suffix(".json.part").exists()


def test_transcription_rejects_result_without_word_timestamps(tmp_path: Path) -> None:
    media_path = tmp_path / "normalized.mp4"
    media_path.write_bytes(b"media")

    class ModelWithoutWords:
        def transcribe(self, *_: Any, **__: Any) -> tuple[list[Any], Any]:
            segment = SimpleNamespace(start=0.0, end=1.0, text="text", words=[])
            info = SimpleNamespace(
                language="en",
                language_probability=1.0,
                duration=1.0,
                duration_after_vad=1.0,
            )
            return [segment], info

    with pytest.raises(TranscriptionError, match="timestamps por palavra"):
        transcribe_media(
            media_path,
            model_factory=lambda *_args, **_kwargs: ModelWithoutWords(),
        )


def test_transcription_accepts_media_without_detected_speech(tmp_path: Path) -> None:
    media_path = tmp_path / "silence.mp4"
    media_path.write_bytes(b"media")

    class SilentModel:
        def transcribe(self, *_: Any, **__: Any) -> tuple[list[Any], Any]:
            info = SimpleNamespace(
                language="en",
                language_probability=0.0,
                duration=1.0,
                duration_after_vad=0.0,
            )
            return [], info

    result = transcribe_media(
        media_path,
        model_factory=lambda *_args, **_kwargs: SilentModel(),
    )

    assert result.segments == ()
