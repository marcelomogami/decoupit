"""Isolated WhisperX transcription with aligned word timestamps."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

MODEL_ID = "Systran/faster-whisper-medium"
MODEL_REVISION = "08e178d48790749d25932bbc082711ddcfdfbc4f"
ALIGN_MODEL_ID = "WAV2VEC2_ASR_BASE_960H"
ALIGN_MODEL_FILENAME = "wav2vec2_fairseq_base_ls960_asr_ls960.pth"
ALIGN_MODEL_SHA256 = "488fd4f16de84438ffc945334278c1b9fb9b7159a806c1080b16111a958c945d"
EXPECTED_LIBRARIES = {
    "faster-whisper": "1.2.1",
    "pyannote.audio": "4.0.7",
    "torch": "2.8.0",
    "torchaudio": "2.8.0",
    "whisperx": "3.8.6",
}
PROFILE = {
    "pipeline": "whisperx",
    "model": MODEL_ID,
    "model_revision": MODEL_REVISION,
    "align_model": ALIGN_MODEL_ID,
    "align_model_sha256": ALIGN_MODEL_SHA256,
    "vad": "pyannote",
    "device": "cuda",
    "compute_type": "float16",
    "cpu_threads": 4,
    "batch_size": 4,
    "chunk_size": 10,
    "local_files_only": True,
    "libraries": EXPECTED_LIBRARIES,
}

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class TranscriptionError(RuntimeError):
    """Raised when local transcription cannot produce a valid result."""


@dataclass(frozen=True, slots=True)
class TranscriptWord:
    start_us: int
    end_us: int
    text: str
    probability: float


@dataclass(frozen=True, slots=True)
class TranscriptSegment:
    start_us: int
    end_us: int
    text: str
    words: tuple[TranscriptWord, ...]


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    language: str
    language_probability: float
    duration_us: int
    duration_after_vad_us: int
    segments: tuple[TranscriptSegment, ...]
    profile: dict[str, Any]
    raw_output: dict[str, Any] | None = None

    def to_json(self) -> str:
        payload = {} if self.raw_output is None else dict(self.raw_output)
        payload["profile"] = self.profile
        payload["result"] = {
            "language": self.language,
            "language_probability": self.language_probability,
            "duration_us": self.duration_us,
            "duration_after_vad_us": self.duration_after_vad_us,
            "segments": [asdict(segment) for segment in self.segments],
        }
        return json.dumps(
            payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )


def _seconds_to_us(value: float, label: str) -> int:
    if not math.isfinite(value) or value < 0:
        raise TranscriptionError(f"tempo inválido em {label}")
    return round(value * 1_000_000)


def _data_root(environment: Mapping[str, str], home: Path) -> Path:
    if xdg_data_home := environment.get("XDG_DATA_HOME"):
        return Path(xdg_data_home)
    return home / ".local" / "share"


def _source_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _resolve_executable(path: Path, label: str) -> Path:
    canonical_path = path.expanduser().absolute()
    if not canonical_path.exists():
        raise TranscriptionError(f"{label} não está disponível: {path}")
    if not canonical_path.is_file() or not os.access(canonical_path, os.X_OK):
        raise TranscriptionError(f"{label} não é executável: {canonical_path}")
    return canonical_path


def resolve_runtime_python(
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    current_environment = os.environ if environment is None else environment
    user_home = Path.home() if home is None else home
    if configured := current_environment.get("DECOUPIT_WHISPERX_PYTHON"):
        return _resolve_executable(Path(configured), "o runtime WhisperX")
    candidates = (
        _data_root(current_environment, user_home)
        / "decoupit"
        / "runtime"
        / "whisperx"
        / "bin"
        / "python",
        _source_root() / "runtime" / "whisperx" / ".venv" / "bin" / "python",
    )
    for candidate in candidates:
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate.absolute()
    raise TranscriptionError(
        "o runtime WhisperX isolado não está instalado; configure "
        "DECOUPIT_WHISPERX_PYTHON"
    )


def resolve_model_path(
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    current_environment = os.environ if environment is None else environment
    user_home = Path.home() if home is None else home
    cache_roots: list[Path] = []
    if hub_cache := current_environment.get("HUGGINGFACE_HUB_CACHE"):
        cache_roots.append(Path(hub_cache))
    if hf_home := current_environment.get("HF_HOME"):
        cache_roots.append(Path(hf_home) / "hub")
    if xdg_cache := current_environment.get("XDG_CACHE_HOME"):
        cache_roots.append(Path(xdg_cache) / "huggingface" / "hub")
    cache_roots.append(user_home / ".cache" / "huggingface" / "hub")
    repository_directory = "models--Systran--faster-whisper-medium"
    for cache_root in dict.fromkeys(cache_roots):
        candidate = cache_root / repository_directory / "snapshots" / MODEL_REVISION
        if (candidate / "model.bin").is_file() and (
            candidate / "config.json"
        ).is_file():
            return candidate.resolve()
    raise TranscriptionError(
        "o modelo Faster Whisper medium não está instalado no cache local"
    )


def resolve_align_model_directory(
    *,
    environment: Mapping[str, str] | None = None,
    home: Path | None = None,
) -> Path:
    current_environment = os.environ if environment is None else environment
    user_home = Path.home() if home is None else home
    candidates: list[Path] = []
    if configured := current_environment.get("DECOUPIT_WHISPERX_ALIGN_MODEL_DIR"):
        candidates.append(Path(configured))
    candidates.extend(
        (
            _data_root(current_environment, user_home)
            / "decoupit"
            / "models"
            / "whisperx",
            _source_root() / "runtime" / "whisperx" / "models",
        )
    )
    for candidate in candidates:
        if (candidate / ALIGN_MODEL_FILENAME).is_file():
            return candidate.expanduser().resolve()
    raise TranscriptionError(
        "o modelo de alinhamento do WhisperX não está instalado; configure "
        "DECOUPIT_WHISPERX_ALIGN_MODEL_DIR"
    )


def _verify_alignment_model(directory: Path, expected_sha256: str) -> None:
    path = directory / ALIGN_MODEL_FILENAME
    try:
        hasher = hashlib.sha256()
        with path.open("rb") as model:
            while chunk := model.read(1024 * 1024):
                hasher.update(chunk)
    except OSError as error:
        raise TranscriptionError(
            "o modelo de alinhamento não está acessível"
        ) from error
    if hasher.hexdigest() != expected_sha256:
        raise TranscriptionError("o modelo de alinhamento possui SHA-256 inesperado")


def runtime_profile() -> dict[str, Any]:
    profile = dict(PROFILE)
    profile["libraries"] = dict(EXPECTED_LIBRARIES)
    return profile


def _validate_interval(start_us: int, end_us: int, label: str) -> None:
    if start_us < 0 or end_us < start_us:
        raise TranscriptionError(f"intervalo inválido em {label}")


def _display_word_texts(
    segment_text: str, words: Sequence[Mapping[str, Any]]
) -> tuple[str, ...]:
    result: list[str] = []
    cursor = 0
    folded_segment = segment_text.casefold()
    for index, word in enumerate(words):
        raw_text = str(word.get("word", ""))
        if not raw_text:
            raise TranscriptionError("o alinhamento retornou uma palavra vazia")
        position = folded_segment.find(raw_text.casefold(), cursor)
        if position >= 0:
            display_text = segment_text[cursor:position] + raw_text
            cursor = position + len(raw_text)
        else:
            display_text = raw_text if index == 0 else f" {raw_text}"
        result.append(display_text)
    return tuple(result)


def _collect_segments(payload: Mapping[str, Any]) -> tuple[TranscriptSegment, ...]:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list):
        raise TranscriptionError("o WhisperX retornou segmentos inválidos")
    result: list[TranscriptSegment] = []
    previous_word_start = 0
    for segment_index, raw_segment in enumerate(raw_segments):
        if not isinstance(raw_segment, Mapping):
            raise TranscriptionError("o WhisperX retornou um segmento inválido")
        try:
            segment_start = _seconds_to_us(
                float(raw_segment["start"]), f"segmento {segment_index}"
            )
            segment_end = _seconds_to_us(
                float(raw_segment["end"]), f"segmento {segment_index}"
            )
        except (KeyError, TypeError, ValueError) as error:
            raise TranscriptionError(
                f"o WhisperX retornou limites inválidos no segmento {segment_index}"
            ) from error
        _validate_interval(segment_start, segment_end, f"segmento {segment_index}")
        raw_words = raw_segment.get("words")
        if not isinstance(raw_words, list):
            raise TranscriptionError(
                f"o WhisperX não retornou palavras no segmento {segment_index}"
            )
        segment_text = str(raw_segment.get("text", ""))
        word_texts = _display_word_texts(segment_text, raw_words)
        words: list[TranscriptWord] = []
        for word_index, (raw_word, word_text) in enumerate(
            zip(raw_words, word_texts, strict=True)
        ):
            if not isinstance(raw_word, Mapping):
                raise TranscriptionError("o WhisperX retornou uma palavra inválida")
            try:
                word_start = _seconds_to_us(
                    float(raw_word["start"]),
                    f"palavra {word_index} do segmento {segment_index}",
                )
                word_end = _seconds_to_us(
                    float(raw_word["end"]),
                    f"palavra {word_index} do segmento {segment_index}",
                )
            except (KeyError, TypeError, ValueError) as error:
                raise TranscriptionError(
                    "o WhisperX não retornou timestamps alinhados para "
                    "todas as palavras"
                ) from error
            _validate_interval(
                word_start,
                word_end,
                f"palavra {word_index} do segmento {segment_index}",
            )
            if (words or result) and word_start < previous_word_start:
                raise TranscriptionError(
                    "o WhisperX retornou palavras fora da ordem temporal"
                )
            previous_word_start = word_start
            try:
                probability = float(raw_word.get("score", 0.0))
            except (TypeError, ValueError) as error:
                raise TranscriptionError(
                    "o WhisperX retornou confiança fonética inválida"
                ) from error
            if not math.isfinite(probability) or not 0 <= probability <= 1:
                raise TranscriptionError(
                    "o WhisperX retornou confiança fonética inválida"
                )
            words.append(
                TranscriptWord(
                    start_us=word_start,
                    end_us=word_end,
                    text=word_text,
                    probability=probability,
                )
            )
        result.append(
            TranscriptSegment(
                start_us=segment_start,
                end_us=segment_end,
                text=segment_text,
                words=tuple(words),
            )
        )
    return tuple(result)


def _read_runtime_output(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TranscriptionError(
            "o runtime WhisperX não produziu JSON válido"
        ) from error
    if not isinstance(payload, dict):
        raise TranscriptionError("o runtime WhisperX produziu um resultado inválido")
    return payload


def _validate_runtime_versions(payload: Mapping[str, Any]) -> None:
    profile = payload.get("profile")
    libraries = profile.get("libraries") if isinstance(profile, Mapping) else None
    if libraries != EXPECTED_LIBRARIES:
        raise TranscriptionError(
            "o runtime WhisperX possui versões diferentes do perfil fixado"
        )


def transcribe_media(
    media_path: Path,
    *,
    runtime_python: Path | None = None,
    model_path: Path | None = None,
    align_model_directory: Path | None = None,
    alignment_model_sha256: str = ALIGN_MODEL_SHA256,
    command_runner: CommandRunner = subprocess.run,
) -> TranscriptionResult:
    try:
        canonical_path = media_path.resolve(strict=True)
    except OSError as error:
        raise TranscriptionError("a mídia normalizada não está acessível") from error
    if not canonical_path.is_file():
        raise TranscriptionError("a mídia normalizada não é um arquivo regular")
    resolved_runtime = (
        resolve_runtime_python() if runtime_python is None else runtime_python
    )
    resolved_model = resolve_model_path() if model_path is None else model_path
    resolved_align_directory = (
        resolve_align_model_directory()
        if align_model_directory is None
        else align_model_directory
    )
    _verify_alignment_model(resolved_align_directory, alignment_model_sha256)
    runner_path = Path(__file__).with_name("whisperx_runner.py").resolve()
    with tempfile.TemporaryDirectory(prefix="decoupit-whisperx-") as temporary:
        output_path = Path(temporary) / "result.json"
        command = [
            str(resolved_runtime),
            "-I",
            str(runner_path),
            "--media",
            str(canonical_path),
            "--whisper-model",
            str(resolved_model),
            "--align-model-dir",
            str(resolved_align_directory),
            "--output",
            str(output_path),
            "--batch-size",
            str(PROFILE["batch_size"]),
            "--chunk-size",
            str(PROFILE["chunk_size"]),
        ]
        try:
            command_runner(
                command,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as error:
            diagnostic = (error.stderr or error.stdout or "").strip()[-2000:]
            suffix = f": {diagnostic}" if diagnostic else ""
            raise TranscriptionError(f"o runtime WhisperX falhou{suffix}") from error
        payload = _read_runtime_output(output_path)
    _validate_runtime_versions(payload)
    transcription = payload.get("transcription")
    aligned = payload.get("aligned")
    if not isinstance(transcription, Mapping) or not isinstance(aligned, Mapping):
        raise TranscriptionError("o runtime WhisperX retornou dados incompletos")
    try:
        language = str(transcription["language"])
        language_probability = float(transcription["language_probability"])
        duration_us = _seconds_to_us(float(transcription["duration"]), "duração")
        duration_after_vad_us = _seconds_to_us(
            float(transcription["duration_after_vad"]), "duração após VAD"
        )
    except (KeyError, TypeError, ValueError) as error:
        raise TranscriptionError(
            "o runtime WhisperX retornou metadados inválidos"
        ) from error
    if (
        not language
        or not math.isfinite(language_probability)
        or not 0 <= language_probability <= 1
    ):
        raise TranscriptionError("o runtime WhisperX retornou idioma inválido")
    return TranscriptionResult(
        language=language,
        language_probability=language_probability,
        duration_us=duration_us,
        duration_after_vad_us=duration_after_vad_us,
        segments=_collect_segments(aligned),
        profile=runtime_profile(),
        raw_output=payload,
    )


def write_result(path: Path, result: TranscriptionResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial_path = path.with_suffix(f"{path.suffix}.part")
    partial_path.unlink(missing_ok=True)
    try:
        with partial_path.open("x", encoding="utf-8") as output:
            output.write(result.to_json())
            output.flush()
            os.fsync(output.fileno())
        os.replace(partial_path, path)
    finally:
        partial_path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Transcreve uma mídia local com WhisperX isolado."
    )
    parser.add_argument("media", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    result = transcribe_media(arguments.media)
    write_result(arguments.output, result)


if __name__ == "__main__":
    main(sys.argv[1:])
