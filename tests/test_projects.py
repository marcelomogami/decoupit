from pathlib import Path

from decoupit.database import connect_database, initialize_database
from decoupit.projects import create_project, list_projects


def test_create_and_list_empty_project(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        created = create_project(connection, name="  Vídeo da Akemi  ")
        projects = list_projects(connection)

    assert created.name == "Vídeo da Akemi"
    assert created.status == "active"
    assert projects == [created]


def test_projects_are_listed_in_creation_order(tmp_path: Path) -> None:
    database_path = tmp_path / "decoupit.sqlite3"
    initialize_database(database_path)

    with connect_database(database_path) as connection:
        first = create_project(connection, name="Primeiro", project_id="a")
        second = create_project(connection, name="Segundo", project_id="b")

        assert list_projects(connection) == [first, second]
