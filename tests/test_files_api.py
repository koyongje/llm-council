import pytest
from fastapi.testclient import TestClient

import backend.main
from backend import storage


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    d = tmp_path / "conversations"
    d.mkdir()
    monkeypatch.setattr(storage, "DATA_DIR", str(d))
    return d


@pytest.fixture
def uploads_dir(tmp_path, monkeypatch):
    d = tmp_path / "uploads"
    d.mkdir()
    monkeypatch.setattr(storage, "UPLOADS_DIR", str(d))
    return d


@pytest.fixture
def client(data_dir, uploads_dir):
    return TestClient(backend.main.app)


def test_upload_pdf_attaches_to_conversation(client):
    cid = client.post("/api/conversations", json={}).json()["id"]
    r = client.post(f"/api/conversations/{cid}/files", files={"file": ("plan.pdf", b"%PDF-1.4 data", "application/pdf")})
    assert r.status_code == 200 and r.json()["filename"] == "plan.pdf" and r.json()["size"] == 13
    assert client.get(f"/api/conversations/{cid}").json()["files"][0]["filename"] == "plan.pdf"
    assert [f.data for f in storage.get_files(cid)] == [b"%PDF-1.4 data"]


def test_rejects_non_pdf(client, uploads_dir):
    cid = client.post("/api/conversations", json={}).json()["id"]
    r = client.post(f"/api/conversations/{cid}/files", files={"file": ("x.pdf", b"PK\x03\x04", "application/pdf")})
    assert r.status_code == 400 and r.json()["detail"] == "Only PDF files are supported"
    assert not any(uploads_dir.rglob("*.pdf"))


def test_rejects_when_total_exceeds_limit(client, monkeypatch):
    monkeypatch.setattr("backend.main.MAX_CONVERSATION_FILES_BYTES", 20)
    cid = client.post("/api/conversations", json={}).json()["id"]
    assert client.post(f"/api/conversations/{cid}/files", files={"file": ("a.pdf", b"%PDF-" + b"x" * 10, "application/pdf")}).status_code == 200
    r = client.post(f"/api/conversations/{cid}/files", files={"file": ("b.pdf", b"%PDF-" + b"x" * 10, "application/pdf")})
    assert r.status_code == 400 and r.json()["detail"] == "Attachments for this conversation would exceed 14 MB"


def test_upload_unknown_conversation_404(client):
    assert client.post("/api/conversations/nope/files", files={"file": ("a.pdf", b"%PDF-", "application/pdf")}).status_code == 404


def test_legacy_conversation_without_files_key_loads(client, data_dir):
    (data_dir / "old.json").write_text('{"id": "old", "created_at": "2025-01-01T00:00:00", "title": "t", "messages": []}')
    assert client.get("/api/conversations/old").json()["files"] == []
    assert storage.get_files("old") == []
