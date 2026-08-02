from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_feedback_persists_and_adds_activity(tmp_path: Path) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    os.environ["JOBFLOW_DB"] = str(db_path)

    from jobflow.database import connect, encode_json, init_db
    from jobflow.main import app

    init_db(db_path)
    with connect(db_path) as db:
        db.execute(
            """
            INSERT INTO jobs (
                id, source_url, title, company, status, fit_evidence_json,
                source_evidence_json, missing_info_json, hard_gate_reasons_json,
                requirements_json, responsibilities_json, technologies_json,
                first_seen_at, updated_at
            )
            VALUES (?, ?, ?, ?, 'inbox', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job-1",
                "https://example.com/job",
                "Junior Builder",
                "Example GmbH",
                encode_json({}),
                encode_json({}),
                encode_json([]),
                encode_json([]),
                encode_json([]),
                encode_json([]),
                encode_json([]),
                "2026-08-02T08:00:00+00:00",
                "2026-08-02T08:00:00+00:00",
            ),
        )

    client = TestClient(app)
    response = client.post(
        "/api/jobs/job-1/feedback",
        json={"rating": "bad", "reasons": ["Salary below target"], "note": "Too low."},
    )

    assert response.status_code == 200
    assert response.json()["rating"] == "bad"
    detail = client.get("/api/jobs/job-1").json()
    assert detail["status"] == "bad"
    assert detail["feedback"]["reasons"] == ["Salary below target"]
    activity = client.get("/api/activity").json()
    assert activity[0]["kind"] == "feedback"
    assert "Example GmbH" in activity[0]["title"]
