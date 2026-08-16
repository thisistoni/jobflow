from pathlib import Path

from fastapi.testclient import TestClient


def test_profile_preferences_and_supporting_document_lifecycle(tmp_path: Path, monkeypatch) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    monkeypatch.setenv("JOBFLOW_DB", str(db_path))

    from jobflow.database import connect, init_db
    from jobflow.main import app

    init_db(db_path)
    client = TestClient(app)

    saved = client.put(
        "/api/preferences",
        json={
            "profile_summary": "Junior builder with HTL education and practical automation experience.",
            "min_home_office_days": 0,
            "salary_target_min": 0,
            "salary_target_max": None,
            "acceptable_salary_min": 52000,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["profile_summary"].startswith("Junior builder")
    assert saved.json()["min_home_office_days"] == 0
    assert saved.json()["salary_target_min"] == 0
    assert saved.json()["acceptable_salary_min"] == 0

    assert client.get("/api/profile/documents").json() == []
    content = b"%PDF-1.4\nMatura certificate\n%%EOF\n"
    uploaded = client.post(
        "/api/profile/documents",
        params={"name": "Matura-Zeugnis.pdf"},
        headers={"Content-Type": "application/pdf"},
        content=content,
    )
    assert uploaded.status_code == 201
    document = uploaded.json()
    assert document["name"] == "Matura-Zeugnis.pdf"
    assert document["size"] == len(content)

    listing = client.get("/api/profile/documents")
    assert listing.status_code == 200
    assert listing.json() == [document]

    downloaded = client.get(f"/api/profile/documents/{document['id']}")
    assert downloaded.status_code == 200
    assert downloaded.content == content
    assert "Matura-Zeugnis.pdf" in downloaded.headers["content-disposition"]

    with connect(db_path) as db:
        stored_name = db.execute(
            "SELECT stored_name FROM profile_documents WHERE id = ?", (document["id"],)
        ).fetchone()["stored_name"]
    stored_path = tmp_path / "profile-documents" / stored_name
    assert stored_path.is_file()

    invalid = client.post(
        "/api/profile/documents",
        params={"name": "malware.exe"},
        headers={"Content-Type": "application/octet-stream"},
        content=b"not allowed",
    )
    assert invalid.status_code == 422

    deleted = client.delete(f"/api/profile/documents/{document['id']}")
    assert deleted.status_code == 204
    assert not stored_path.exists()
    assert client.get("/api/profile/documents").json() == []
