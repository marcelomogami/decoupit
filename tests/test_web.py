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
    assert "0.1.0" in page.text
    assert health.status_code == 200
    assert health.json() == {"status": "ready", "version": "0.1.0"}
    assert paths.data.is_dir()
    assert paths.cache.is_dir()
    assert paths.database.is_file()


def test_unknown_host_is_rejected(tmp_path: Path) -> None:
    app = create_app(paths=resolve_app_paths(environment={}, home=tmp_path))

    with TestClient(app, base_url="http://example.invalid") as client:
        response = client.get("/")

    assert response.status_code == 400


def test_create_project_and_list_it_after_restart(tmp_path: Path) -> None:
    paths = resolve_app_paths(environment={}, home=tmp_path)

    with TestClient(create_app(paths=paths)) as client:
        created = client.post(
            "/api/projects",
            json={"name": "  Projeto vazio  "},
            headers={"Origin": "http://testserver"},
        )

    with TestClient(create_app(paths=paths)) as client:
        listed = client.get("/api/projects")

    assert created.status_code == 201
    assert created.json()["name"] == "Projeto vazio"
    assert created.json()["status"] == "active"
    assert listed.status_code == 200
    assert listed.json() == [created.json()]


def test_cross_origin_project_creation_is_rejected(tmp_path: Path) -> None:
    paths = resolve_app_paths(environment={}, home=tmp_path)

    with TestClient(create_app(paths=paths)) as client:
        rejected = client.post(
            "/api/projects",
            json={"name": "Não deve existir"},
            headers={"Origin": "https://example.invalid"},
        )
        listed = client.get("/api/projects")

    assert rejected.status_code == 403
    assert listed.json() == []


def test_blank_project_name_is_rejected(tmp_path: Path) -> None:
    paths = resolve_app_paths(environment={}, home=tmp_path)

    with TestClient(create_app(paths=paths)) as client:
        response = client.post(
            "/api/projects",
            json={"name": "   "},
            headers={"Origin": "http://testserver"},
        )

    assert response.status_code == 422
