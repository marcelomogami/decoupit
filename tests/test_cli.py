from typing import Any

import pytest

from decoupit import cli


def test_cli_runs_server_on_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    invocation: dict[str, Any] = {}

    def fake_run(app: str, **options: Any) -> None:
        invocation.update(app=app, **options)

    monkeypatch.setattr(cli.uvicorn, "run", fake_run)

    cli.main(["--port", "8123"])

    assert invocation == {
        "app": "decoupit.web:create_app",
        "factory": True,
        "host": "127.0.0.1",
        "port": 8123,
    }
