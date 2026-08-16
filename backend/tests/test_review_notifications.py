from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


def test_push_subscribe_and_test_notification(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    monkeypatch.setenv("JOBFLOW_DB", str(db_path))

    from jobflow.database import connect, init_db
    from jobflow.main import app
    import jobflow.main as main

    init_db(db_path)
    sent: list[dict[str, Any]] = []
    monkeypatch.setattr(main, "webpush", lambda **kwargs: sent.append(kwargs))

    client = TestClient(app)
    status = client.get("/api/notifications/status")
    assert status.status_code == 200
    assert len(status.json()["public_key"]) > 80
    assert (tmp_path / "jobflow-vapid-private.pem").exists()

    subscription = _push_subscription("https://push.example/sub/1")
    subscribed = client.post("/api/notifications/subscribe", json={"subscription": subscription})
    assert subscribed.status_code == 200
    assert subscribed.json()["subscribed"] is True
    with connect(db_path) as db:
        assert db.execute("SELECT COUNT(*) FROM push_subscriptions WHERE disabled_at IS NULL").fetchone()[0] == 1

    tested = client.post("/api/notifications/test")
    assert tested.status_code == 200
    assert tested.json() == {"sent": 1, "failed": 0}
    assert sent[0]["subscription_info"]["endpoint"] == subscription["endpoint"]
    assert json.loads(sent[0]["data"])["title"] == "JobFlow notifications are enabled"

    unsubscribed = client.post("/api/notifications/unsubscribe", json={"subscription": subscription})
    assert unsubscribed.status_code == 200
    assert unsubscribed.json()["subscribed"] is False


def test_pack_version_review_backlog_pauses_discovery_without_search_call(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    monkeypatch.setenv("JOBFLOW_DB", str(db_path))
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")
    monkeypatch.setenv("FIRECRAWL_API_URL", "http://firecrawl.test")

    from jobflow.database import connect, encode_json, init_db
    from jobflow.main import app
    import jobflow.main as main

    init_db(db_path)
    for index in range(3):
        _ready_job(db_path, f"job-{index}", version=2 if index == 0 else 1)
    with connect(db_path) as db:
        db.execute(
            """
            INSERT INTO review_decisions(id, job_id, pack_version, decision, reasons_json, note, created_at, updated_at)
            VALUES ('old-decision', 'job-0', 1, 'approve', '[]', '', ?, ?)
            """,
            ("2026-08-02T08:00:00+00:00", "2026-08-02T08:00:00+00:00"),
        )
        db.execute(
            "UPDATE discovery_sources SET enabled = 1 WHERE id = 'open_web'"
        )
        db.execute(
            """
            INSERT INTO preferences (
                id, target_locations_json, work_modes_json, salary_currency,
                role_families_json, priorities_json, hard_rules_json,
                discovery_queries_json, discovery_limit_per_query, updated_at
            )
            VALUES ('default', '[]', '[]', 'EUR', '[]', '[]', '[]', ?, 5, ?)
            ON CONFLICT(id) DO UPDATE SET discovery_queries_json = excluded.discovery_queries_json
            """,
            (encode_json(["python vienna"]), "2026-08-02T08:00:00+00:00"),
        )

    client = TestClient(app)
    assert client.get("/api/review/status").json()["backlog_count"] == 3
    monkeypatch.setattr(main, "search_web", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("external search called")))
    paused = client.post("/api/discovery/run")
    assert paused.status_code == 200
    assert paused.json()["paused_for_review"] is True
    assert "3/3" in paused.json()["paused_reason"]
    with connect(db_path) as db:
        run = db.execute("SELECT paused_for_review, paused_reason FROM discovery_runs").fetchone()
        assert run["paused_for_review"] == 1
        assert "3/3" in run["paused_reason"]

    approved = client.post("/api/jobs/job-0/review-decision", json={"decision": "approve", "reasons": [], "note": ""})
    assert approved.status_code == 200
    assert approved.json()["application_task"] is None
    assert client.get("/api/review/status").json()["backlog_count"] == 2

    calls: list[str] = []
    monkeypatch.setattr(main, "search_web", lambda query, _limit: calls.append(query) or [])
    unpaused = client.post("/api/discovery/run")
    assert unpaused.status_code == 200
    assert unpaused.json()["paused_for_review"] is False
    assert calls == ["python vienna"]


def test_approval_does_not_create_or_queue_application_task(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    monkeypatch.setenv("JOBFLOW_DB", str(db_path))

    from jobflow.database import init_db
    from jobflow.main import app

    init_db(db_path)
    _ready_job(db_path, "job-1")
    client = TestClient(app)
    token = client.post("/api/agent-tokens", json={"label": "reporter"}).json()["token"]
    approved = client.post("/api/jobs/job-1/review-decision", json={"decision": "approve"})
    assert approved.status_code == 200
    assert approved.json()["application_task"] is None

    report = client.post(
        "/api/jobs/job-1/application-task/report",
        headers={"Authorization": f"Bearer {token}"},
        json={"state": "needs_input", "required_fields": ["salary expectation"]},
    )
    assert report.status_code == 409


def test_application_report_requires_current_pack_approval(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    monkeypatch.setenv("JOBFLOW_DB", str(db_path))

    from jobflow.database import init_db
    from jobflow.main import app

    init_db(db_path)
    _ready_job(db_path, "job-unapproved")
    client = TestClient(app)
    token = client.post("/api/agent-tokens", json={"label": "reporter"}).json()["token"]
    report = client.post(
        "/api/jobs/job-unapproved/application-task/report",
        headers={"Authorization": f"Bearer {token}"},
        json={"state": "needs_input", "required_fields": ["salary"]},
    )
    assert report.status_code == 409


def test_changing_pack_review_keeps_application_task_empty(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    monkeypatch.setenv("JOBFLOW_DB", str(db_path))

    from jobflow.database import init_db
    from jobflow.main import app

    init_db(db_path)
    _ready_job(db_path, "job-changed")
    client = TestClient(app)
    approved = client.post("/api/jobs/job-changed/review-decision", json={"decision": "approve"})
    assert approved.status_code == 200
    assert approved.json()["application_task"] is None
    declined = client.post("/api/jobs/job-changed/review-decision", json={"decision": "decline"})
    assert declined.status_code == 200
    assert declined.json()["application_task"] is None


def test_request_changes_webhook_records_success_and_failure_without_failing_feedback(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    monkeypatch.setenv("JOBFLOW_DB", str(db_path))
    monkeypatch.setenv("JOBFLOW_REVISION_WEBHOOK_URL", "https://hooks.example/revise")
    monkeypatch.setenv("JOBFLOW_REVISION_WEBHOOK_SECRET", "secret")

    from jobflow.database import connect, init_db
    from jobflow.main import app
    import jobflow.main as main

    init_db(db_path)
    _ready_job(db_path, "job-success")
    calls: list[Any] = []

    class FakeWebhookResponse:
        status = 202

        def __enter__(self) -> "FakeWebhookResponse":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_urlopen(request: Any, timeout: int) -> FakeWebhookResponse:
        calls.append(request)
        assert timeout == 10
        body = request.data
        assert request.headers["X-jobflow-signature"] == "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        timestamp = request.headers["X-webhook-timestamp"]
        assert request.headers["X-webhook-signature-v2"] == hmac.new(
            b"secret",
            timestamp.encode("ascii") + b"." + body,
            hashlib.sha256,
        ).hexdigest()
        assert json.loads(body)["job_id"] == "job-success"
        return FakeWebhookResponse()

    monkeypatch.setattr(main, "urlopen", fake_urlopen)
    client = TestClient(app)
    changed = client.post(
        "/api/jobs/job-success/review-decision",
        json={"decision": "request_changes", "reasons": ["Letter needs changes"], "note": "Focus Python."},
    )
    assert changed.status_code == 200
    assert changed.json()["application_pack"]["revision_state"] == "changes_requested"
    assert calls
    with connect(db_path) as db:
        assert db.execute("SELECT status FROM revision_requests WHERE job_id = 'job-success'").fetchone()["status"] == "dispatched"

    _ready_job(db_path, "job-failure")
    monkeypatch.setattr(main, "urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    legacy = client.post(
        "/api/jobs/job-failure/feedback",
        json={"rating": "maybe", "reasons": ["CV needs changes"], "note": "Add stronger evidence."},
    )
    assert legacy.status_code == 200
    with connect(db_path) as db:
        assert db.execute("SELECT status FROM revision_requests WHERE job_id = 'job-failure'").fetchone()["status"] == "failed"


def _ready_job(db_path: Path, job_id: str, *, version: int = 1) -> None:
    from jobflow.database import connect, encode_json

    now = "2026-08-02T08:00:00+00:00"
    with connect(db_path) as db:
        db.execute(
            """
            INSERT INTO jobs (
                id, source_url, title, company, location, score, verdict, confidence, status,
                extracted_description, salary_min_annual, salary_currency, work_mode,
                fit_evidence_json, source_evidence_json, missing_info_json, hard_gate_reasons_json,
                requirements_json, responsibilities_json, technologies_json, first_seen_at, updated_at
            )
            VALUES (?, ?, 'Software Developer', 'Example GmbH', 'Wien', 82, 'strong', 'high', 'inbox',
                ?, 58000, 'EUR', 'Hybrid', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                f"https://example.com/{job_id}",
                "Complete verified source description. " * 8,
                encode_json({}),
                encode_json({}),
                encode_json([]),
                encode_json([]),
                encode_json(["Python"]),
                encode_json(["Build internal tools"]),
                encode_json(["Python"]),
                now,
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO application_packs (
                job_id, status, version, revision_state, revision_reasons_json, revision_note,
                resume_id, resume_name, resume_pdf_pages, letter_subject, letter_body,
                agent_model, agent_run_id, critic_notes, created_at, updated_at
            )
            VALUES (?, 'ready', ?, 'current', '[]', '', 'resume-1', 'Pack', 1,
                    'Bewerbung', 'Letter', 'openai/gpt-5.6-luna', 'run-1', 'Claims checked.', ?, ?)
            """,
            (job_id, version, now, now),
        )


def _push_subscription(endpoint: str) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "expirationTime": None,
        "keys": {
            "p256dh": "BDu9qBf7cWJ6JTVnx0nseVBqywKzRsDcPmUTvHRf0x6AA8VyJNaE0Yh8JkT3hE9WNa_6Dbi47VVb1Xl5sFNUcLU",
            "auth": "abc123abc123abc123abcw",
        },
    }
