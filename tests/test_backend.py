from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


@pytest.fixture()
def knowledge_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root = tmp_path / "solutions"
    root.mkdir()
    monkeypatch.setattr(main, "SOLUTIONS_DIR", str(root))
    return root


@pytest.fixture()
def meta_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    target = tmp_path / "solutions-meta.json"
    monkeypatch.setattr(main, "META_FILE", str(target))
    return target


@pytest.mark.parametrize("user_id", ["41314", 41314, ""])
def test_dmy_id_endpoint_returns_configured_user_id(user_id, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "DMY_ID", user_id)
    response = TestClient(main.app).get("/api/id/dmy")

    assert response.status_code == 200
    assert response.json() == user_id


def test_solution_delete_rejects_empty_path():
    client = TestClient(main.app)
    response = client.post("/api/solutions/delete", json={})

    assert response.status_code == 422


def test_meta_update_never_resets_elapsed_time(meta_file: Path):
    client = TestClient(main.app)

    assert client.post("/api/solutions/meta", json={
        "path": "contest/problem", "elapsed": 125, "completed": False,
    }).status_code == 200
    assert client.post("/api/solutions/meta", json={
        "path": "contest/problem", "elapsed": 0, "completed": False,
    }).status_code == 200

    assert client.get("/api/solutions/meta").json()["contest/problem"]["elapsed"] == 125


def test_meta_batch_merges_instead_of_replacing_existing_entries(meta_file: Path):
    main.save_meta({
        "first": {"elapsed": 60, "completed": False},
        "second": {"elapsed": 90, "completed": False},
    })
    client = TestClient(main.app)

    response = client.post("/api/solutions/meta/batch", json={
        "items": {"first": {"elapsed": 70, "completed": False}},
    })

    assert response.status_code == 200
    assert client.get("/api/solutions/meta").json() == {
        "first": {"elapsed": 70, "completed": False},
        "second": {"elapsed": 90, "completed": False},
    }


def test_meta_delete_removes_only_requested_tree(meta_file: Path):
    main.save_meta({
        "folder/one": {"elapsed": 10, "completed": False},
        "folder/two": {"elapsed": 20, "completed": False},
        "other": {"elapsed": 30, "completed": False},
    })
    client = TestClient(main.app)

    response = client.post("/api/solutions/meta/delete", json={"path": "folder"})

    assert response.status_code == 200
    assert client.get("/api/solutions/meta").json() == {
        "other": {"elapsed": 30, "completed": False},
    }
