from __future__ import annotations

import os
from pathlib import Path

from fastapi.testclient import TestClient


def test_ingest_is_idempotent_and_analysis_removes_unanalyzed(tmp_path: Path) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    os.environ["JOBFLOW_DB"] = str(db_path)

    from jobflow.database import init_db
    from jobflow.main import app

    init_db(db_path)
    client = TestClient(app)
    payload = {
        "source_url": "https://Example.com/jobs/42?utm_source=newsletter&b=2&a=1",
        "title": "Backend Engineer",
        "company": "Example GmbH",
        "location": "Vienna",
        "description": "Build APIs and internal workflow tools.",
        "source_name": "Example Careers",
        "first_seen_at": "2026-08-02T08:00:00+00:00",
    }

    created = client.post("/api/jobs", json=payload)
    duplicate = client.post(
        "/api/jobs",
        json={**payload, "source_url": "https://example.com/jobs/42?a=1&b=2&utm_campaign=again"},
    )

    assert created.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == created.json()["id"]
    assert created.json()["source_url"] == "https://example.com/jobs/42?a=1&b=2"
    assert client.get("/api/jobs?filter=unanalyzed").json()[0]["id"] == created.json()["id"]
    activity = client.get("/api/activity").json()
    assert [item["kind"] for item in activity] == ["ingest"]

    analysis = client.put(
        f"/api/jobs/{created.json()['id']}/analysis",
        json={
            "score": 82,
            "verdict": "strong",
            "confidence": "medium",
            "summary": "Good backend fit with salary still missing.",
            "fit_evidence": {"role": [{"text": "Build APIs and internal workflow tools."}]},
            "missing_info": ["Salary range"],
            "hard_gate_reasons": [],
            "requirements": ["Python", "FastAPI"],
            "responsibilities": ["Build APIs"],
            "technologies": ["Python", "FastAPI"],
            "salary_display": "Not listed",
            "salary_min_annual": 65000,
            "salary_max_annual": 80000,
            "salary_currency": "EUR",
            "work_mode": "hybrid",
            "home_office_days": 3,
            "language_environment": "English",
            "source_evidence": {"description": ["Build APIs and internal workflow tools."]},
        },
    )

    assert analysis.status_code == 200
    detail = analysis.json()
    assert detail["score"] == 82
    assert detail["feedback"] is None
    assert detail["salary_max_annual"] == 80000
    assert detail["fit_evidence"]["role"][0]["text"] == "Build APIs and internal workflow tools."
    assert client.get("/api/jobs?filter=unanalyzed").json() == []
    final_activity = client.get("/api/activity").json()
    assert sorted(item["kind"] for item in final_activity) == ["analysis", "ingest"]
