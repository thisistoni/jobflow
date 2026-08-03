from __future__ import annotations

import os
from pathlib import Path
from typing import Any

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


def test_request_changes_invalidates_pack_and_regeneration_returns_to_inbox(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    os.environ["JOBFLOW_DB"] = str(db_path)

    from jobflow.database import connect, encode_json, init_db, utc_now
    from jobflow.main import app
    import jobflow.main as main

    init_db(db_path)
    now = "2026-08-02T08:00:00+00:00"
    with connect(db_path) as db:
        db.execute(
            """
            INSERT INTO jobs (
                id, source_url, source_id, source_name, title, company, location,
                extracted_description, score, verdict, confidence, status, summary,
                salary_display, salary_min_annual, salary_currency, work_mode,
                fit_evidence_json, source_evidence_json, missing_info_json, hard_gate_reasons_json,
                requirements_json, responsibilities_json, technologies_json,
                first_seen_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 82, 'strong', 'high', 'inbox', ?, ?, 52000, 'EUR', 'Hybrid', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job-1",
                "https://www.karriere.at/jobs/123456",
                "123456",
                "karriere.at",
                "Junior Software Entwickler:in",
                "Example GmbH",
                "Wien",
                "Wir entwickeln interne Tools mit Python, SQL und Webanwendungen. " * 4,
                "Strong fit.",
                "ab 52.000 €",
                encode_json({}),
                encode_json({}),
                encode_json([]),
                encode_json([]),
                encode_json(["Python", "SQL"]),
                encode_json(["Interne Webanwendungen entwickeln"]),
                encode_json(["Python", "SQL"]),
                now,
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO application_packs (
                job_id, status, version, revision_state, revision_reasons_json, revision_note,
                resume_id, resume_name, resume_pdf_pages, letter_subject, letter_body, created_at, updated_at
            )
            VALUES ('job-1', 'ready', 1, 'current', '[]', '', 'resume-1', 'Example pack', 1, 'Bewerbung', 'Letter', ?, ?)
            """,
            (now, now),
        )

    client = TestClient(app)
    assert [job["id"] for job in client.get("/api/jobs").json()] == ["job-1"]
    changed = client.post(
        "/api/jobs/job-1/feedback",
        json={"rating": "maybe", "reasons": ["Letter needs changes"], "note": "Focus Python."},
    )
    assert changed.status_code == 200
    assert client.get("/api/jobs").json() == []
    review = client.get("/api/jobs?filter=maybe").json()
    assert review[0]["id"] == "job-1"
    assert review[0]["pack_status"] == "preparing"
    assert review[0]["pack_revision_state"] == "changes_requested"

    # A scheduled crawl may refresh facts, but it must neither clear a pending
    # revision nor downgrade a complete stored advert when extraction falls back
    # to an incomplete shell.
    from jobflow.karriere_camofox import KarriereJobDetail
    from jobflow.models import Preferences

    incomplete = KarriereJobDetail(
        url="https://www.karriere.at/jobs/123456",
        source_id="123456",
        title="Junior Software Entwickler:in",
        company="Example GmbH",
        location="Wien",
        description="Temporary shell",
        salary_display="ab 52.000 €",
        salary_min_annual=52_000,
        salary_max_annual=52_000,
        work_mode="Hybrid",
        requirements=[],
        responsibilities=[],
        technologies=[],
    )
    prepare_calls: list[str] = []
    monkeypatch.setattr(main, "_prepare_application_pack", lambda job_id, *_args, **_kwargs: prepare_calls.append(job_id) or True)
    main._promote_karriere_details(
        [incomplete],
        Preferences(
            target_locations=["Wien"],
            work_modes=["Hybrid"],
            salary_target_min=45_000,
            role_families=["software developer"],
        ),
    )
    assert prepare_calls == []
    still_pending = client.get("/api/jobs/job-1").json()
    assert still_pending["status"] == "maybe"
    assert still_pending["application_pack"]["revision_state"] == "changes_requested"
    assert len(still_pending["extracted_description"]) >= 180
    assert still_pending["requirements"] == ["Python", "SQL"]

    def fake_prepare(job_id: str, *_args: Any, **_kwargs: Any) -> bool:
        main._store_application_pack(
            job_id,
            status="ready",
            version=2,
            revision_state="regenerated",
            revision_reasons=["Letter needs changes"],
            revision_note="Focus Python.",
            resume_id="resume-2",
            resume_name="Example pack v2",
            resume_pdf_pages=1,
            letter_subject="Bewerbung",
            letter_body="Regenerated letter",
            now=utc_now(),
        )
        pack = main._application_pack(job_id)
        assert pack is not None
        main._record_application_pack_version(job_id, pack)
        return True

    monkeypatch.setattr(main, "_prepare_application_pack", fake_prepare)
    regenerated = client.post("/api/jobs/job-1/regenerate-pack", json={})
    assert regenerated.status_code == 200
    body = regenerated.json()
    assert body["status"] == "inbox"
    assert body["application_pack"]["version"] == 2
    assert body["application_pack"]["revision_state"] == "regenerated"
    assert [item["version"] for item in body["application_pack"]["versions"]] == [2, 1]
    inbox = client.get("/api/jobs").json()
    assert [job["id"] for job in inbox] == ["job-1"]


def test_inbox_excludes_historical_ready_pack_with_hard_gate(tmp_path: Path) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    os.environ["JOBFLOW_DB"] = str(db_path)

    from jobflow.database import connect, encode_json, init_db
    from jobflow.main import app

    init_db(db_path)
    now = "2026-08-02T08:00:00+00:00"
    with connect(db_path) as db:
        db.execute(
            """
            INSERT INTO jobs (
                id, source_url, title, company, location, score, verdict, status,
                fit_evidence_json, source_evidence_json, missing_info_json, hard_gate_reasons_json,
                requirements_json, responsibilities_json, technologies_json,
                first_seen_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 82, 'strong', 'inbox', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "job-hard-gate",
                "https://example.com/job-hard-gate",
                "Senior Developer",
                "Example GmbH",
                "Graz",
                encode_json({}),
                encode_json({}),
                encode_json([]),
                encode_json(["Location does not clearly match saved targets: Graz"]),
                encode_json(["Python"]),
                encode_json(["Build tools"]),
                encode_json(["Python"]),
                now,
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO application_packs (
                job_id, status, resume_id, resume_name, resume_pdf_pages, letter_body, created_at, updated_at
            )
            VALUES ('job-hard-gate', 'ready', 'resume-1', 'Pack', 1, 'Letter', ?, ?)
            """,
            (now, now),
        )

    client = TestClient(app)
    assert client.get("/api/jobs").json() == []
    assert client.get("/api/jobs?filter=all").json()[0]["id"] == "job-hard-gate"
