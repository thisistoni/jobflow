from __future__ import annotations

import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


class FakeReactiveResumeClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        if api_key != "good-secret":
            from jobflow.reactive_resume import ReactiveResumeError

            raise ReactiveResumeError("Reactive Resume API returned HTTP 401")
        self.base_url = base_url

    def list_resumes(self) -> list[dict[str, Any]]:
        return [
            {"id": "canonical-id", "name": "Hermes Canonical Base CV", "updatedAt": "2026-08-01T12:00:00Z"},
            {"id": "historical-id", "name": "Hermes Starting Template", "updatedAt": "2026-07-01T12:00:00Z"},
            {"id": "other-id", "name": "Other approved base", "updatedAt": "2026-08-02T12:00:00Z"},
        ]

    def get_resume(self, resume_id: str) -> dict[str, Any]:
        names = {
            "canonical-id": "Hermes Canonical Base CV",
            "historical-id": "Hermes Starting Template",
            "other-id": "Other approved base",
        }
        return {
            "id": resume_id,
            "name": names[resume_id],
            "updatedAt": "2026-08-02T12:00:00Z",
            "data": {"metadata": {"template": "chikorita"}},
        }

    def export_pdf(self, resume_id: str) -> bytes:
        assert resume_id in {"canonical-id", "other-id"}
        return b"%PDF-1.4\n% mocked reference\n"


def test_reactive_resume_secret_reference_and_pdf_contract(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    monkeypatch.setenv("JOBFLOW_DB", str(db_path))
    monkeypatch.setenv("JOBFLOW_SECRET_KEY", Fernet.generate_key().decode())

    from jobflow import database, main

    monkeypatch.setattr(main, "ReactiveResumeClient", FakeReactiveResumeClient)
    database.init_db()

    client = TestClient(main.app)
    initial = client.get("/api/integrations/reactive-resume")
    assert initial.status_code == 200
    assert initial.json()["encryption_ready"] is True
    assert initial.json()["configured"] is False

    rejected = client.post(
        "/api/integrations/reactive-resume/connect",
        json={"api_key": "bad-secret", "base_url": "https://rxresu.me/api/openapi"},
    )
    assert rejected.status_code == 502
    assert "bad-secret" not in rejected.text

    connected = client.post(
        "/api/integrations/reactive-resume/connect",
        json={"api_key": "good-secret", "base_url": "https://rxresu.me/api/openapi"},
    )
    assert connected.status_code == 200
    body = connected.json()
    assert "good-secret" not in connected.text
    assert body["configured"] is True
    assert body["verified"] is True
    assert body["reference"]["name"] == "Hermes Canonical Base CV"
    assert body["reference"]["template"] == "chikorita"
    assert any(option["historical_source"] for option in body["available_resumes"])

    with database.connect(db_path) as db:
        row = db.execute("SELECT encrypted_api_key FROM reactive_resume_config WHERE id = 1").fetchone()
    assert row["encrypted_api_key"] != "good-secret"
    from jobflow.reactive_resume import decrypt_api_key

    assert decrypt_api_key(row["encrypted_api_key"]) == "good-secret"

    historical = client.put(
        "/api/integrations/reactive-resume/reference",
        json={"resume_id": "historical-id"},
    )
    assert historical.status_code == 422
    assert client.get("/api/integrations/reactive-resume").json()["verified"] is True

    selected = client.put(
        "/api/integrations/reactive-resume/reference",
        json={"resume_id": "other-id"},
    )
    assert selected.status_code == 200
    assert selected.json()["reference"]["name"] == "Other approved base"

    pdf = client.get("/api/integrations/reactive-resume/reference.pdf")
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert pdf.headers["cache-control"] == "private, no-store"
    assert pdf.headers["content-disposition"].startswith("inline;")

    disconnected = client.delete("/api/integrations/reactive-resume")
    assert disconnected.status_code == 200
    assert disconnected.json()["configured"] is False


def test_reactive_resume_refuses_cross_origin_api_key_redirect() -> None:
    from jobflow.reactive_resume import ReactiveResumeClient, ReactiveResumeError

    captured: list[str | None] = []

    class TargetHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            captured.append(self.headers.get("x-api-key"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b"[]")

        def log_message(self, format: str, *args: Any) -> None:
            return

    target = ThreadingHTTPServer(("127.0.0.1", 0), TargetHandler)
    target_thread = threading.Thread(target=target.serve_forever, daemon=True)
    target_thread.start()

    class SourceHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{target.server_port}/resumes")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            return

    source = ThreadingHTTPServer(("127.0.0.1", 0), SourceHandler)
    source_thread = threading.Thread(target=source.serve_forever, daemon=True)
    source_thread.start()
    try:
        client = ReactiveResumeClient("redirect-secret", f"http://127.0.0.1:{source.server_port}")
        try:
            client.list_resumes()
        except ReactiveResumeError:
            pass
        else:
            raise AssertionError("cross-origin redirect unexpectedly succeeded")
        assert captured == []
    finally:
        source.shutdown()
        source.server_close()
        target.shutdown()
        target.server_close()
