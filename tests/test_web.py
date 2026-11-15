from pathlib import Path

from fastapi.testclient import TestClient

from decoupit.paths import resolve_app_paths
from decoupit.web import create_app


def test_status_page_and_health_endpoint(tmp_path: Path) -> None:
    paths = resolve_app_paths(environment={}, home=tmp_path)

    with TestClient(create_app(paths=paths)) as client:
        page = client.get("/")
        health = client.get("/api/health")

    assert page.status_code == 200
    assert "DecoupIt" in page.text
    assert "0.1.0.dev0" in page.text
    assert health.status_code == 200
    assert health.json() == {"status": "ready", "version": "0.1.0.dev0"}
    assert paths.data.is_dir()
    assert paths.cache.is_dir()


def test_unknown_host_is_rejected(tmp_path: Path) -> None:
    app = create_app(paths=resolve_app_paths(environment={}, home=tmp_path))

    with TestClient(app, base_url="http://example.invalid") as client:
        response = client.get("/")

    assert response.status_code == 400
