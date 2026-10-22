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


OLD_ID = "5f0c2a9e-1b7d-4c1e-9a43-0d6f3b8e7a21"


def test_legacy_conversation_without_files_key_loads(client, data_dir):
    (data_dir / f"{OLD_ID}.json").write_text(
        '{"id": "%s", "created_at": "2025-01-01T00:00:00", "title": "t", "messages": []}' % OLD_ID)
    assert client.get(f"/api/conversations/{OLD_ID}").json()["files"] == []
    assert storage.get_files(OLD_ID) == []


@pytest.mark.parametrize("bad_id", ["..%5C..%5Cx", "not-a-uuid", "..%2F..%2Fx"])
def test_invalid_conversation_id_404(client, bad_id):
    assert client.get(f"/api/conversations/{bad_id}").status_code == 404
    r = client.post(f"/api/conversations/{bad_id}/files", files={"file": ("a.pdf", b"%PDF-", "application/pdf")})
    assert r.status_code == 404
    assert client.post(f"/api/conversations/{bad_id}/message", json={"content": "q"}).status_code == 404


def test_invalid_id_never_touches_filesystem(data_dir, uploads_dir):
    (data_dir.parent / "x.json").write_text('{"id": "x", "created_at": "t", "messages": []}')
    assert storage.get_conversation("../x") is None
    assert storage.get_files("../../x") == []
    with pytest.raises(ValueError):
        storage.add_file("../../x", "a.pdf", b"%PDF-")


def test_get_files_skips_missing_pdf(client, uploads_dir):
    cid = client.post("/api/conversations", json={}).json()["id"]
    for name in ("a.pdf", "b.pdf"):
        client.post(f"/api/conversations/{cid}/files", files={"file": (name, b"%PDF-1", "application/pdf")})
    next(uploads_dir.rglob("*.pdf")).unlink()
    assert len(storage.get_files(cid)) == 1
