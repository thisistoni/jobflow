from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient


def test_discovery_operations_generate_queries_persist_history_and_priority_roles(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    os.environ["JOBFLOW_DB"] = str(db_path)
    os.environ["FIRECRAWL_API_KEY"] = "test-key"
    os.environ["FIRECRAWL_API_URL"] = "http://firecrawl.test"

    from jobflow.database import connect, init_db
    from jobflow.main import app
    import jobflow.main as main

    init_db(db_path)
    client = TestClient(app)
    preferences = {
        "target_locations": ["Wien"],
        "work_modes": ["hybrid"],
        "min_home_office_days": 2,
        "salary_currency": "EUR",
        "salary_target_min": 50000,
        "salary_target_max": 56000,
        "acceptable_salary_min": 47500,
        "role_families": ["Junior software developer", "Internal tools developer"],
        "priority_role_families": ["Internal tools developer"],
        "priorities": ["German-speaking team"],
        "hard_rules": [],
        "discovery_queries": [],
        "discovery_limit_per_query": 5,
        "language_preference": "German or English",
        "application_language": "match-posting",
        "manual_submission_only": True,
    }
    saved = client.put("/api/preferences", json=preferences)
    assert saved.status_code == 200
    assert saved.json()["priority_role_families"] == ["Internal tools developer"]

    operations = client.get("/api/discovery/operations")
    assert operations.status_code == 200
    assert operations.json()["schedule"] == {
        "enabled": True,
        "timezone": "Europe/Vienna",
        "times": ["07:00", "13:00", "19:00"],
    }
    assert operations.json()["generated_queries"][0] == "Internal tools developer jobs Wien"
    assert operations.json()["next_run_at"]

    unavailable = client.put(
        "/api/discovery/config",
        json={
            "schedule": operations.json()["schedule"],
            "sources_enabled": {"ams_manual": True},
        },
    )
    assert unavailable.status_code == 422

    def fake_search(query: str, limit: int) -> list[dict[str, str]]:
        assert limit == 5
        return [
            {"url": "https://example.com/jobs/1?utm_source=test", "title": "One", "description": query},
            {"url": "https://example.com/jobs/1", "title": "One duplicate", "description": query},
        ]

    monkeypatch.setattr(main, "search_web", fake_search)
    run = client.post("/api/discovery/run")
    assert run.status_code == 200
    assert run.json()["run_id"]
    assert len(run.json()["queries"]) == 2
    assert len(run.json()["results"]) == 1

    after = client.get("/api/discovery/operations").json()
    assert after["last_run"]["status"] == "succeeded"
    assert after["last_run"]["candidate_count"] == 4
    assert after["last_run"]["unique_count"] == 1
    with connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM discovery_candidates").fetchone()[0] == 1

    current_vienna_time = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Vienna")).strftime("%H:%M")
    configured = client.put(
        "/api/discovery/config",
        json={
            "schedule": {"enabled": True, "timezone": "Europe/Vienna", "times": [current_vienna_time]},
            "sources_enabled": {"open_web": True, "company_careers": False},
        },
    )
    assert configured.status_code == 200
    main._run_due_discovery()
    main._run_due_discovery()
    with connect(db_path) as db:
        scheduled = db.execute("SELECT COUNT(*) FROM discovery_runs WHERE trigger = 'scheduled'").fetchone()[0]
    assert scheduled == 1
