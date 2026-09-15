"""Contract tests for api/projects.py via TestClient — no live model."""

import pytest
from fastapi.testclient import TestClient

import config
import projects
import server
import settings
import spaces


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(projects, "PROJECTS_DIR", tmp_path / "projects")
    monkeypatch.setattr(spaces, "SPACES_DIR", tmp_path / "spaces")
    monkeypatch.setattr(settings, "SETTINGS_PATH", tmp_path / "settings.json")
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir()
    (upload_dir / "doc.pdf").write_bytes(b"x")
    monkeypatch.setattr(config, "get_upload_dir", lambda: upload_dir)
    return TestClient(server.app)


def _create(client, name="Proj", goal="Ship it"):
    resp = client.post("/api/projects", json={"name": name, "goal": goal})
    assert resp.status_code == 200
    return resp.json()


def test_create_list_get(client):
    p = _create(client)
    assert p["goal"] == "Ship it"
    assert p["documents"] == []
    assert p["space_id"]
    listing = client.get("/api/projects").json()
    assert [x["id"] for x in listing["projects"]] == [p["id"]]
    assert listing["projects"][0]["document_count"] == 0
    assert listing["active"] is None
    assert client.get(f"/api/projects/{p['id']}").json()["name"] == "Proj"
    assert client.get("/api/projects/nope").status_code == 404


def test_create_requires_name(client):
    assert client.post("/api/projects", json={"name": " "}).status_code == 400


def test_update_and_delete(client):
    p = _create(client)
    resp = client.put(f"/api/projects/{p['id']}", json={"notes": "# n", "goal": "g2"})
    assert resp.status_code == 200
    assert resp.json()["notes"] == "# n"
    assert resp.json()["goal"] == "g2"
    assert client.put(f"/api/projects/{p['id']}", json={"name": ""}).status_code == 400
    assert client.delete(f"/api/projects/{p['id']}").status_code == 200
    assert client.delete(f"/api/projects/{p['id']}").status_code == 404


def test_activate_and_deactivate(client):
    p = _create(client)
    resp = client.post(f"/api/projects/{p['id']}/activate")
    assert resp.status_code == 200
    assert resp.json()["active"] == p["id"]
    assert client.post("/api/projects/nope/activate").status_code == 404
    assert client.post("/api/projects/deactivate").json()["active"] is None


def test_attach_detach_documents(client):
    p = _create(client)
    resp = client.post(
        f"/api/projects/{p['id']}/documents", json={"filename": "doc.pdf"}
    )
    assert resp.status_code == 200
    assert resp.json()["documents"] == ["doc.pdf"]
    assert client.get("/api/projects").json()["projects"][0]["document_count"] == 1
    resp = client.delete(f"/api/projects/{p['id']}/documents/doc.pdf")
    assert resp.status_code == 200
    assert resp.json()["documents"] == []
    assert (
        client.delete(f"/api/projects/{p['id']}/documents/doc.pdf").status_code == 400
    )


def test_attach_rejects_missing_and_traversal(client, tmp_path):
    (tmp_path / "secret.pdf").write_bytes(b"x")
    p = _create(client)
    resp = client.post(
        f"/api/projects/{p['id']}/documents", json={"filename": "nope.pdf"}
    )
    assert resp.status_code == 404
    resp = client.post(
        f"/api/projects/{p['id']}/documents", json={"filename": "../secret.pdf"}
    )
    assert resp.status_code == 400
    assert (
        client.post(
            "/api/projects/nope/documents", json={"filename": "doc.pdf"}
        ).status_code
        == 404
    )


def test_append_notes_and_links(client):
    p = _create(client)
    resp = client.post(
        f"/api/projects/{p['id']}/notes/append",
        json={"text": "finding", "heading": "Arena"},
    )
    assert resp.status_code == 200
    assert resp.json()["notes"] == "## Arena\n\nfinding\n"
    assert (
        client.post(
            f"/api/projects/{p['id']}/notes/append", json={"text": " "}
        ).status_code
        == 400
    )

    resp = client.post(
        f"/api/projects/{p['id']}/links",
        json={"kind": "arena", "id": "j1", "title": "t"},
    )
    assert resp.status_code == 200
    assert resp.json()["links"][0]["kind"] == "arena"
    resp = client.post(
        f"/api/projects/{p['id']}/links", json={"kind": "coding", "id": "j2"}
    )
    assert resp.status_code == 400
