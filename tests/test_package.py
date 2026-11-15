from importlib.metadata import version

import decoupit


def test_package_uses_media_ingest_development_version() -> None:
    assert decoupit.__name__ == "decoupit"
    assert version("decoupit") == "0.2.0.dev0"
