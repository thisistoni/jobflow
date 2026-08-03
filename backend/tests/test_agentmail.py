from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from jobflow.agentmail import (
    AlertCandidate,
    AlertIngestion,
    ProcessedAlertMessage,
    extract_karriere_job_urls,
)


def test_karriere_link_extraction_is_numeric_canonical_and_deduplicated() -> None:
    text = """
    <a href="https://www.karriere.at/jobs/123456?utm_source=alarm&amp;x=1">Job</a>
    https://karriere.at/jobs/123456#details
    https://www.karriere.at/jobs/softwareentwickler-wien
    https://example.com/jobs/999
    """
    assert extract_karriere_job_urls(text) == ["https://www.karriere.at/jobs/123456"]


def test_karriere_alert_source_can_run_without_web_search(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    os.environ["JOBFLOW_DB"] = str(db_path)
    monkeypatch.setenv("AGENTMAIL_API_KEY", "test-agentmail-key")
    monkeypatch.setenv("KARRIERE_ALERTS_ACTIVE", "true")

    from jobflow.database import connect, init_db
    from jobflow.main import app
    import jobflow.main as main

    init_db(db_path)
    client = TestClient(app)
    operations = client.get("/api/discovery/operations").json()
    source = next(item for item in operations["sources"] if item["id"] == "karriere_alerts")
    assert source["status"] == "available"

    configured = client.put(
        "/api/discovery/config",
        json={
            "schedule": operations["schedule"],
            "sources_enabled": {"open_web": False, "karriere_alerts": True},
        },
    )
    assert configured.status_code == 200

    def fake_alerts(seen_message_ids: set[str]) -> AlertIngestion:
        assert seen_message_ids == set()
        return AlertIngestion(
            messages=[ProcessedAlertMessage("message-1", "Neue Jobs", "2026-08-03T08:00:00Z", 1)],
            candidates=[
                AlertCandidate(
                    "https://www.karriere.at/jobs/123456",
                    "Neue Jobs",
                    "message-1",
                    "2026-08-03T08:00:00Z",
                )
            ],
        )

    monkeypatch.setattr(main, "fetch_karriere_alerts", fake_alerts)
    monkeypatch.setattr(main, "search_web", lambda *_: (_ for _ in ()).throw(AssertionError("web search called")))
    run = client.post("/api/discovery/run")
    assert run.status_code == 200
    assert run.json()["results"] == [
        {
            "url": "https://www.karriere.at/jobs/123456",
            "title": "Neue Jobs",
            "description": "Official karriere.at Job Alarm link.",
            "source": "karriere_alerts",
            "matched_queries": ["karriere.at Job Alarm"],
        }
    ]
    with connect(db_path) as db:
        candidate = db.execute("SELECT source FROM discovery_candidates").fetchone()
        assert candidate["source"] == "karriere_alerts"
        assert db.execute("SELECT COUNT(*) FROM agentmail_messages").fetchone()[0] == 1
