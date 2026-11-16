from importlib.metadata import version

import decoupit


def test_package_uses_transcription_release_version() -> None:
    assert decoupit.__name__ == "decoupit"
    assert version("decoupit") == "0.3.0"
