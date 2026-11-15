from importlib.metadata import version

import decoupit


def test_package_uses_initial_development_version() -> None:
    assert decoupit.__name__ == "decoupit"
    assert version("decoupit") == "0.1.0.dev0"
