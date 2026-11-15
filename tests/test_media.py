import json
import subprocess
from pathlib import Path

import pytest

from decoupit.media import MediaProbeError, probe_source


def test_probe_source_reads_vfr_metadata_without_modifying_file(
    tmp_path: Path,
) -> None:
    source = tmp_path / "phone.mp4"
    source.write_bytes(b"immutable source bytes")
    before = source.stat()
    probe_output = {
        "streams": [
            {
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "r_frame_rate": "30/1",
                "avg_frame_rate": "524182500/17471897",
                "duration": "60.032",
            },
            {
                "codec_type": "audio",
                "codec_name": "aac",
                "sample_rate": "48000",
                "channels": 2,
            },
        ],
        "format": {"format_name": "mov,mp4", "duration": "60.032"},
    }

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        assert command[-1] == str(source.resolve())
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(probe_output), stderr=""
        )

    inspected = probe_source(source, runner=fake_run)
    after = source.stat()

    assert inspected.path == source.resolve()
    assert inspected.size_bytes == before.st_size
    assert inspected.duration_us == 60_032_000
    assert inspected.frame_rate_mode == "variable"
    assert inspected.video_codec == "h264"
    assert inspected.audio_codec == "aac"
    assert source.read_bytes() == b"immutable source bytes"
    assert after.st_mtime_ns == before.st_mtime_ns


def test_probe_source_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(MediaProbeError, match="não existe"):
        probe_source(tmp_path / "missing.mp4")


def test_probe_source_rejects_video_without_dimensions(tmp_path: Path) -> None:
    source = tmp_path / "invalid.mp4"
    source.write_bytes(b"not relevant to mocked ffprobe")
    output = {
        "streams": [{"codec_type": "video", "codec_name": "h264"}],
        "format": {},
    }

    def fake_run(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command, 0, stdout=json.dumps(output), stderr=""
        )

    with pytest.raises(MediaProbeError, match="dimensões válidas"):
        probe_source(source, runner=fake_run)
