from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import os
import re
import secrets
import time
import uuid
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request as UrlRequest, urlopen
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pywebpush import WebPushException, webpush

from .application_pipeline import ApplicationDraft, analyze_karriere_job, application_draft_quality_issues
from .agentmail import (
    AgentMailConfigError,
    AgentMailProviderError,
    configured as agentmail_configured,
    fetch_karriere_alerts,
    karriere_alerts_active,
)
from .database import connect, database_path, decode_json, encode_json, init_db, utc_now
from .firecrawl import FirecrawlConfigError, FirecrawlProviderError, scrape_url, search_web
from .importer import _stable_id, canonicalize_url
from .karriere_camofox import (
    CamofoxConfigError,
    CamofoxProviderError,
    KarriereExpiredError,
    KarriereJobDetail,
    camofox_available,
    crawl_karriere,
    refresh_karriere_detail,
)
from .letter_pdf import render_application_letter_pdf
from .models import (
    ActivityItem,
    AgentApplicationReportIn,
    AgentPackIn,
    ApplicationTaskOut,
    ApplicationPackOut,
    ApplicationPackVersionOut,
    DailyPulseItem,
    DashboardPulseOut,
    DiscoveryConfigIn,
    DiscoveryOperationsOut,
    DiscoveryRunOut,
    DiscoveryRunResult,
    DiscoveryRunSummary,
    DiscoveryScheduleConfig,
    DiscoveryScrapeIn,
    DiscoveryScrapeResult,
    DiscoverySearchIn,
    DiscoverySearchResult,
    DiscoverySourceConfig,
    EvidenceItem,
    FeedbackIn,
    FeedbackOut,
    JobAnalysisIn,
    JobDetail,
    JobIngestIn,
    JobListItem,
    Preferences,
    ProfileDocumentOut,
    PushStatusOut,
    PushSubscriptionIn,
    RegeneratePackIn,
    ReactiveResumeConnectIn,
    ReactiveResumeOption,
    ReactiveResumeReference,
    ReactiveResumeReferenceIn,
    ReactiveResumeStatus,
    ReviewDecisionIn,
    ReviewDecisionOut,
    ReviewStatusOut,
    TestNotificationOut,
)
from .reactive_resume import (
    DEFAULT_BASE_URL as REACTIVE_RESUME_DEFAULT_BASE_URL,
    ReactiveResumeClient,
    ReactiveResumeError,
    SecretStoreError,
    decrypt_api_key,
    encrypt_api_key,
    encryption_ready,
    validate_base_url,
)


AUTH_USERNAME_ENV = "JOBFLOW_AUTH_USERNAME"
AUTH_PASSWORD_ENV = "JOBFLOW_AUTH_PASSWORD"
AUTH_COOKIE_SECURE_ENV = "JOBFLOW_AUTH_COOKIE_SECURE"
AUTH_COOKIE_NAME = "jobflow_session"
AUTH_COOKIE_MAX_AGE_SECONDS = 7 * 24 * 60 * 60
STATIC_DIR_ENV = "JOBFLOW_STATIC_DIR"
REVISION_WEBHOOK_URL_ENV = "JOBFLOW_REVISION_WEBHOOK_URL"
REVISION_WEBHOOK_SECRET_ENV = "JOBFLOW_REVISION_WEBHOOK_SECRET"
PROFILE_DOCUMENT_MAX_BYTES = 20 * 1024 * 1024
PROFILE_DOCUMENT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".doc", ".docx"}
OPEN_AUTH_API_PATHS = {"/api/auth/status", "/api/auth/login", "/api/auth/logout"}
_scheduler_heartbeat_at: datetime | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    _auth_config()
    _cookie_secure()
    init_db()
    scheduler = asyncio.create_task(_discovery_scheduler())
    try:
        yield
    finally:
        scheduler.cancel()
        with suppress(asyncio.CancelledError):
            await scheduler


app = FastAPI(title="JobFlow", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def app_auth(request: Request, call_next: Any) -> Any:
    path = request.url.path
    if path == "/health" or not _is_api_path(path) or path in OPEN_AUTH_API_PATHS:
        return await call_next(request)

    config = _auth_config()
    if config is None:
        return await call_next(request)

    if not (
        _valid_basic_auth(request.headers.get("Authorization"), config)
        or _valid_agent_token(request.headers.get("Authorization"))
        or _valid_session(request, config) is not None
    ):
        return _auth_unauthorized()

    return await call_next(request)


class AuthLoginIn(BaseModel):
    username: str
    password: str


class AuthStatusOut(BaseModel):
    auth_required: bool
    authenticated: bool
    expires_at: int | None = None


class AgentTokenCreateIn(BaseModel):
    label: str = "Hermes JobFlow agents"


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/auth/status", response_model=AuthStatusOut)
def auth_status(request: Request) -> AuthStatusOut:
    config = _auth_config()
    if config is None:
        return AuthStatusOut(auth_required=False, authenticated=True)
    expires_at = _valid_session(request, config)
    return AuthStatusOut(
        auth_required=True,
        authenticated=expires_at is not None or _valid_basic_auth(request.headers.get("Authorization"), config),
        expires_at=expires_at,
    )


@app.post("/api/auth/login", response_model=AuthStatusOut)
def auth_login(payload: AuthLoginIn) -> JSONResponse | AuthStatusOut:
    config = _auth_config()
    if config is None:
        return AuthStatusOut(auth_required=False, authenticated=True)
    if not _credentials_match(payload.username, payload.password, config):
        return _auth_unauthorized("Invalid username or password")

    expires_at = int(time.time()) + AUTH_COOKIE_MAX_AGE_SECONDS
    response = JSONResponse(
        AuthStatusOut(auth_required=True, authenticated=True, expires_at=expires_at).model_dump(),
    )
    response.set_cookie(
        AUTH_COOKIE_NAME,
        _encode_session(payload.username, expires_at, config),
        max_age=AUTH_COOKIE_MAX_AGE_SECONDS,
        httponly=True,
        secure=_cookie_secure(),
        samesite="strict",
        path="/",
    )
    return response


@app.post("/api/auth/logout", response_model=AuthStatusOut)
def auth_logout() -> JSONResponse:
    config = _auth_config()
    response = JSONResponse(AuthStatusOut(auth_required=config is not None, authenticated=False).model_dump())
    response.delete_cookie(AUTH_COOKIE_NAME, path="/", secure=_cookie_secure(), samesite="strict")
    return response


@app.post("/api/agent-tokens")
def create_agent_token(payload: AgentTokenCreateIn) -> dict[str, str]:
    token = secrets.token_urlsafe(32)
    now = utc_now()
    with connect() as db:
        db.execute(
            "INSERT INTO agent_tokens(id, label, token_hash, created_at) VALUES (?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                payload.label.strip()[:120] or "Hermes JobFlow agents",
                hashlib.sha256(token.encode()).hexdigest(),
                now,
            ),
        )
    return {"token": token, "created_at": now}


@app.get("/api/notifications/status", response_model=PushStatusOut)
def notification_status() -> PushStatusOut:
    public_key = _vapid_public_key()
    with connect() as db:
        count = db.execute(
            "SELECT COUNT(*) FROM push_subscriptions WHERE disabled_at IS NULL"
        ).fetchone()[0]
    return PushStatusOut(public_key=public_key, subscribed=count > 0, subscription_count=count)


@app.post("/api/notifications/subscribe", response_model=PushStatusOut)
def subscribe_notifications(payload: PushSubscriptionIn, request: Request) -> PushStatusOut:
    endpoint = _subscription_endpoint(payload.subscription)
    now = utc_now()
    with connect() as db:
        existing = db.execute(
            "SELECT id, created_at FROM push_subscriptions WHERE endpoint = ?",
            (endpoint,),
        ).fetchone()
        subscription_id = existing["id"] if existing else str(uuid.uuid4())
        created_at = existing["created_at"] if existing else now
        db.execute(
            """
            INSERT INTO push_subscriptions (
                id, endpoint, subscription_json, user_agent, created_at, updated_at, last_error, disabled_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
            ON CONFLICT(endpoint) DO UPDATE SET
                subscription_json = excluded.subscription_json,
                user_agent = excluded.user_agent,
                updated_at = excluded.updated_at,
                last_error = NULL,
                disabled_at = NULL
            """,
            (
                subscription_id,
                endpoint,
                encode_json(payload.subscription),
                (request.headers.get("User-Agent") or "")[:300],
                created_at,
                now,
            ),
        )
    return notification_status()


@app.post("/api/notifications/unsubscribe", response_model=PushStatusOut)
def unsubscribe_notifications(payload: PushSubscriptionIn) -> PushStatusOut:
    endpoint = _subscription_endpoint(payload.subscription)
    with connect() as db:
        db.execute(
            "UPDATE push_subscriptions SET disabled_at = ?, updated_at = ? WHERE endpoint = ?",
            (utc_now(), utc_now(), endpoint),
        )
    return notification_status()


@app.post("/api/notifications/test", response_model=TestNotificationOut)
def test_notification() -> TestNotificationOut:
    sent, failed = _send_notification_to_all(
        {
            "title": "JobFlow notifications are enabled",
            "body": "You will be notified when review or application tasks need attention.",
            "url": "/",
            "tag": "jobflow-test",
        }
    )
    return TestNotificationOut(sent=sent, failed=failed)


@app.get("/api/jobs", response_model=list[JobListItem])
def list_jobs(
    filter: Literal["inbox", "strong", "maybe", "low", "reviewed", "unanalyzed", "all"] = "inbox",
    limit: int = Query(50, ge=1, le=200),
) -> list[JobListItem]:
    clauses: list[str] = []
    params: list[Any] = []
    ready_clause = _ready_pack_sql()
    if filter == "inbox":
        clauses.append(ready_clause)
    elif filter == "strong":
        clauses.append(f"{ready_clause} AND (j.verdict = 'strong' OR j.score >= 70)")
    elif filter == "maybe":
        clauses.append("j.status = 'maybe'")
    elif filter == "low":
        clauses.append("j.status = 'bad'")
    elif filter == "reviewed":
        clauses.append("j.status = 'good'")
    elif filter == "unanalyzed":
        clauses.append("j.status = 'inbox' AND j.score IS NULL")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with connect() as db:
        rows = db.execute(
            f"""
            SELECT j.*, f.rating, f.reasons_json, f.note, f.updated_at AS feedback_updated_at
            FROM jobs j
            LEFT JOIN feedback f ON f.job_id = j.id
            {where}
            ORDER BY COALESCE(j.score, -1) DESC, j.updated_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [_job_list_item(row) for row in rows]


@app.post("/api/jobs", response_model=JobDetail)
def ingest_job(payload: JobIngestIn) -> JobDetail:
    try:
        source_url = canonicalize_url(payload.source_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    job_id = _stable_id(source_url)
    now = utc_now()
    first_seen_at = payload.first_seen_at or now
    with connect() as db:
        existing = db.execute(
            """
            SELECT j.*, f.rating, f.reasons_json, f.note, f.updated_at AS feedback_updated_at
            FROM jobs j
            LEFT JOIN feedback f ON f.job_id = j.id
            WHERE j.source_url = ?
            """,
            (source_url,),
        ).fetchone()
        if existing is not None:
            return _job_detail(existing)
        db.execute(
            """
            INSERT INTO jobs (
                id, source_id, source_name, source_url, title, company, location,
                raw_description, extracted_description, status, fit_evidence_json,
                source_evidence_json, missing_info_json, hard_gate_reasons_json,
                requirements_json, responsibilities_json, technologies_json,
                first_seen_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'inbox', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                payload.source_id,
                payload.source_name,
                source_url,
                payload.title,
                payload.company,
                payload.location,
                payload.raw_description,
                payload.extracted_description,
                encode_json({}),
                encode_json({}),
                encode_json([]),
                encode_json([]),
                encode_json([]),
                encode_json([]),
                encode_json([]),
                first_seen_at,
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO activity (id, kind, title, body, job_id, created_at)
            VALUES (?, 'ingest', ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                f"Added {payload.company}",
                payload.title,
                job_id,
                now,
            ),
        )
        row = db.execute(
            """
            SELECT j.*, f.rating, f.reasons_json, f.note, f.updated_at AS feedback_updated_at
            FROM jobs j
            LEFT JOIN feedback f ON f.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=500, detail="Job was not created")
    return _job_detail(row)


@app.get("/api/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: str) -> JobDetail:
    with connect() as db:
        row = db.execute(
            """
            SELECT j.*, f.rating, f.reasons_json, f.note, f.updated_at AS feedback_updated_at
            FROM jobs j
            LEFT JOIN feedback f ON f.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    item = _job_detail(row)
    return item


@app.get("/api/jobs/{job_id}/cv.pdf")
def get_job_cv(job_id: str, version: int | None = Query(default=None, ge=1)) -> Response:
    pack = _application_pack(job_id)
    if pack is None or pack.status != "ready" or not pack.resume_id:
        raise HTTPException(status_code=404, detail="Prepared CV is not ready")
    selected = _application_pack_version(job_id, version) if version is not None else None
    resume_id = selected.resume_id if selected is not None else pack.resume_id
    if version is not None and (selected is None or not resume_id):
        raise HTTPException(status_code=404, detail="Prepared CV version was not found")
    if not resume_id:
        raise HTTPException(status_code=404, detail="Prepared CV is not ready")
    try:
        _, client = _configured_reactive_resume_client()
        pdf = client.export_pdf(resume_id)
    except (ReactiveResumeError, SecretStoreError, ValueError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="jobflow-{job_id[:12]}-cv.pdf"'},
    )


@app.get("/api/jobs/{job_id}/application-letter.pdf")
def get_job_application_letter(job_id: str, version: int | None = Query(default=None, ge=1)) -> Response:
    pack = _application_pack(job_id)
    if pack is None or pack.status != "ready" or not pack.letter_body:
        raise HTTPException(status_code=404, detail="Application letter is not ready")
    selected = _application_pack_version(job_id, version) if version is not None else None
    if version is not None and selected is None:
        raise HTTPException(status_code=404, detail="Application letter version was not found")
    with connect() as db:
        job = db.execute("SELECT title, company FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    subject = (selected.letter_subject if selected is not None else pack.letter_subject) or f"Bewerbung als {job['title']}"
    body = selected.letter_body if selected is not None else pack.letter_body
    if not body:
        raise HTTPException(status_code=404, detail="Application letter version was not found")
    pdf = render_application_letter_pdf(
        company=job["company"],
        subject=subject,
        body=body,
    )
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="jobflow-{job_id[:12]}-anschreiben.pdf"'},
    )


@app.put("/api/jobs/{job_id}/analysis", response_model=JobDetail)
def update_job_analysis(job_id: str, payload: JobAnalysisIn) -> JobDetail:
    now = utc_now()
    analysis = payload.model_dump()
    with connect() as db:
        job = db.execute("SELECT title, company FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        db.execute(
            """
            UPDATE jobs SET
                score = ?,
                verdict = ?,
                confidence = ?,
                summary = ?,
                salary_display = ?,
                salary_min_annual = ?,
                salary_max_annual = ?,
                salary_currency = ?,
                work_mode = ?,
                home_office_days = ?,
                language_environment = ?,
                fit_evidence_json = ?,
                source_evidence_json = ?,
                missing_info_json = ?,
                hard_gate_reasons_json = ?,
                requirements_json = ?,
                responsibilities_json = ?,
                technologies_json = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                payload.score,
                payload.verdict,
                payload.confidence,
                payload.summary,
                payload.salary_display,
                payload.salary_min_annual,
                payload.salary_max_annual,
                payload.salary_currency,
                payload.work_mode,
                payload.home_office_days,
                payload.language_environment,
                encode_json(analysis["fit_evidence"]),
                encode_json(analysis["source_evidence"]),
                encode_json(analysis["missing_info"]),
                encode_json(analysis["hard_gate_reasons"]),
                encode_json(analysis["requirements"]),
                encode_json(analysis["responsibilities"]),
                encode_json(analysis["technologies"]),
                now,
                job_id,
            ),
        )
        db.execute(
            """
            INSERT INTO activity (id, kind, title, body, job_id, created_at)
            VALUES (?, 'analysis', ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                f"Analyzed {job['company']}",
                f"{job['title']} · {payload.score}% · {payload.verdict}",
                job_id,
                now,
            ),
        )
        row = db.execute(
            """
            SELECT j.*, f.rating, f.reasons_json, f.note, f.updated_at AS feedback_updated_at
            FROM jobs j
            LEFT JOIN feedback f ON f.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_detail(row)


@app.post("/api/jobs/{job_id}/feedback", response_model=FeedbackOut)
def submit_feedback(job_id: str, payload: FeedbackIn) -> FeedbackOut:
    with connect() as db:
        pack = db.execute(
            "SELECT status FROM application_packs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if pack is None or pack["status"] != "ready":
        return _store_legacy_feedback_only(job_id, payload)
    decision_map = {"good": "approve", "maybe": "request_changes", "bad": "decline"}
    detail = _apply_review_decision(
        job_id,
        ReviewDecisionIn(decision=decision_map[payload.rating], reasons=payload.reasons, note=payload.note),
        legacy_rating=payload.rating,
    )
    if detail.feedback is None:
        raise HTTPException(status_code=500, detail="Feedback was not saved")
    return detail.feedback


@app.get("/api/review/status", response_model=ReviewStatusOut)
def review_status() -> ReviewStatusOut:
    return _review_status()


@app.post("/api/jobs/{job_id}/review-decision", response_model=JobDetail)
def submit_review_decision(job_id: str, payload: ReviewDecisionIn) -> JobDetail:
    return _apply_review_decision(job_id, payload)


@app.post("/api/jobs/{job_id}/application-task/report", response_model=JobDetail)
def report_application_task(job_id: str, payload: AgentApplicationReportIn, request: Request) -> JobDetail:
    _require_agent_auth(request)
    if payload.state == "submitted":
        raise HTTPException(
            status_code=409,
            detail="A progress report cannot authorize or record final submission",
        )
    now = utc_now()
    with connect() as db:
        job = db.execute("SELECT title, company FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        pack = db.execute("SELECT version FROM application_packs WHERE job_id = ?", (job_id,)).fetchone()
        if pack is None:
            raise HTTPException(status_code=409, detail="Application task requires an application pack")
        decision = db.execute(
            "SELECT decision FROM review_decisions WHERE job_id = ? AND pack_version = ?",
            (job_id, pack["version"]),
        ).fetchone()
        if decision is None or decision["decision"] != "approve":
            raise HTTPException(
                status_code=409,
                detail="Application preparation requires explicit approval of the current pack version",
            )
        existing = db.execute(
            "SELECT id, created_at FROM application_tasks WHERE job_id = ? AND pack_version = ?",
            (job_id, pack["version"]),
        ).fetchone()
        if existing is None:
            raise HTTPException(status_code=409, detail="Approved application task was not created")
        task_id = existing["id"] if existing else str(uuid.uuid4())
        created_at = existing["created_at"] if existing else now
        db.execute(
            """
            INSERT INTO application_tasks (
                id, job_id, pack_version, state, required_fields_json,
                questions_json, report, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, pack_version) DO UPDATE SET
                state = excluded.state,
                required_fields_json = excluded.required_fields_json,
                questions_json = excluded.questions_json,
                report = excluded.report,
                updated_at = excluded.updated_at
            """,
            (
                task_id,
                job_id,
                pack["version"],
                payload.state,
                encode_json(_clean_list(payload.required_fields)),
                encode_json(_clean_list(payload.questions)),
                payload.report.strip(),
                created_at,
                now,
            ),
        )
        db.execute(
            "UPDATE jobs SET updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        db.execute(
            "INSERT INTO activity (id, kind, title, body, job_id, created_at) VALUES (?, 'application_task', ?, ?, ?, ?)",
            (
                str(uuid.uuid4()),
                f"Application task updated for {job['company']}",
                f"{job['title']} · {payload.state.replace('_', ' ')}",
                job_id,
                now,
            ),
        )
        row = db.execute(
            """
            SELECT j.*, f.rating, f.reasons_json, f.note, f.updated_at AS feedback_updated_at
            FROM jobs j
            LEFT JOIN feedback f ON f.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
    if payload.state in {"needs_input", "failed"}:
        _notify_application_task(job_id, payload.state)
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_detail(row)


def _apply_review_decision(
    job_id: str,
    payload: ReviewDecisionIn,
    *,
    legacy_rating: Literal["good", "maybe", "bad"] | None = None,
) -> JobDetail:
    now = utc_now()
    revision_request_id: str | None = None
    reasons = _clean_list(payload.reasons)[:8]
    note = payload.note.strip()
    with connect() as db:
        row = db.execute(
            """
            SELECT j.*, f.rating, f.reasons_json, f.note, f.updated_at AS feedback_updated_at
            FROM jobs j
            LEFT JOIN feedback f ON f.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Job not found")
        pack = db.execute(
            "SELECT * FROM application_packs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if pack is None or pack["status"] != "ready":
            raise HTTPException(status_code=409, detail="A ready application pack is required before review")

        existing_decision = db.execute(
            "SELECT id, created_at FROM review_decisions WHERE job_id = ? AND pack_version = ?",
            (job_id, pack["version"]),
        ).fetchone()
        decision_id = existing_decision["id"] if existing_decision else str(uuid.uuid4())
        decision_created_at = existing_decision["created_at"] if existing_decision else now
        db.execute(
            """
            INSERT INTO review_decisions (
                id, job_id, pack_version, decision, reasons_json, note, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id, pack_version) DO UPDATE SET
                decision = excluded.decision,
                reasons_json = excluded.reasons_json,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (
                decision_id,
                job_id,
                pack["version"],
                payload.decision,
                encode_json(reasons),
                note,
                decision_created_at,
                now,
            ),
        )

        rating = legacy_rating or {
            "approve": "good",
            "decline": "bad",
            "request_changes": "maybe",
        }[payload.decision]
        existing_feedback = db.execute("SELECT id, created_at FROM feedback WHERE job_id = ?", (job_id,)).fetchone()
        feedback_id = existing_feedback["id"] if existing_feedback else str(uuid.uuid4())
        feedback_created_at = existing_feedback["created_at"] if existing_feedback else now
        db.execute(
            """
            INSERT INTO feedback (id, job_id, rating, reasons_json, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                rating = excluded.rating,
                reasons_json = excluded.reasons_json,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (feedback_id, job_id, rating, encode_json(reasons), note, feedback_created_at, now),
        )
        db.execute(
            "UPDATE jobs SET status = ?, reviewed_at = ?, updated_at = ? WHERE id = ?",
            (rating, now, now, job_id),
        )

        if payload.decision == "approve":
            db.execute(
                "DELETE FROM application_tasks WHERE job_id = ? AND pack_version = ? AND state != 'submitted'",
                (job_id, pack["version"]),
            )
            activity_title = f"Approved application pack for {row['company']}"
            activity_body = f"{row['title']} · CV and letter approved. Nothing was sent or uploaded."
        elif payload.decision == "request_changes":
            db.execute(
                "DELETE FROM application_tasks WHERE job_id = ? AND pack_version = ? AND state != 'submitted'",
                (job_id, pack["version"]),
            )
            db.execute(
                """
                INSERT OR IGNORE INTO application_pack_versions(
                    job_id, version, revision_state, revision_reasons_json, revision_note,
                    resume_id, resume_name, resume_pdf_pages, letter_subject, letter_body,
                    agent_model, agent_run_id, critic_notes, created_at
                )
                SELECT job_id, version, revision_state, revision_reasons_json, revision_note,
                       resume_id, resume_name, resume_pdf_pages, letter_subject, letter_body,
                       agent_model, agent_run_id, critic_notes, updated_at
                FROM application_packs
                WHERE job_id = ? AND status = 'ready'
                """,
                (job_id,),
            )
            db.execute(
                """
                UPDATE application_packs
                SET status = 'preparing',
                    revision_state = 'changes_requested',
                    revision_reasons_json = ?,
                    revision_note = ?,
                    error = 'Queued for the Luna application agent.',
                    updated_at = ?
                WHERE job_id = ?
                """,
                (encode_json(reasons), note, now, job_id),
            )
            revision_request_id = str(uuid.uuid4())
            db.execute(
                """
                INSERT INTO revision_requests (
                    id, job_id, pack_version, reasons_json, note, status, created_at
                ) VALUES (?, ?, ?, ?, ?, 'queued', ?)
                """,
                (revision_request_id, job_id, pack["version"], encode_json(reasons), note, now),
            )
            activity_title = f"Queued AI revision for {row['company']}"
            activity_body = "Feedback is saved for Luna to produce the next CV and letter version."
        else:
            db.execute(
                "DELETE FROM application_tasks WHERE job_id = ? AND pack_version = ? AND state != 'submitted'",
                (job_id, pack["version"]),
            )
            activity_title = f"Declined {row['company']}"
            activity_body = f"{row['title']} · {', '.join(reasons) if reasons else 'No quick reason'}"

        db.execute(
            """
            INSERT INTO activity (id, kind, title, body, job_id, created_at)
            VALUES (?, 'review_decision', ?, ?, ?, ?)
            """,
            (str(uuid.uuid4()), activity_title, activity_body, job_id, now),
        )
        updated = db.execute(
            """
            SELECT j.*, f.rating, f.reasons_json, f.note, f.updated_at AS feedback_updated_at
            FROM jobs j
            LEFT JOIN feedback f ON f.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
    if revision_request_id:
        _dispatch_revision_webhook(revision_request_id)
    _update_review_pause_state()
    if updated is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_detail(updated)


def _store_legacy_feedback_only(job_id: str, payload: FeedbackIn) -> FeedbackOut:
    now = utc_now()
    with connect() as db:
        job = db.execute("SELECT title, company FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        existing = db.execute("SELECT id, created_at FROM feedback WHERE job_id = ?", (job_id,)).fetchone()
        feedback_id = existing["id"] if existing else str(uuid.uuid4())
        created_at = existing["created_at"] if existing else now
        reasons = _clean_list(payload.reasons)[:8]
        note = payload.note.strip()
        db.execute(
            """
            INSERT INTO feedback (id, job_id, rating, reasons_json, note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                rating = excluded.rating,
                reasons_json = excluded.reasons_json,
                note = excluded.note,
                updated_at = excluded.updated_at
            """,
            (feedback_id, job_id, payload.rating, encode_json(reasons), note, created_at, now),
        )
        db.execute(
            "UPDATE jobs SET status = ?, reviewed_at = ?, updated_at = ? WHERE id = ?",
            (payload.rating, now, now, job_id),
        )
        db.execute(
            """
            INSERT INTO activity (id, kind, title, body, job_id, created_at)
            VALUES (?, 'feedback', ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                f"Marked {job['company']} as {payload.rating}",
                f"{job['title']} · {', '.join(reasons) if reasons else 'No quick reason'}",
                job_id,
                now,
            ),
        )
    return FeedbackOut(rating=payload.rating, reasons=reasons, note=note, updated_at=now)


def _review_status() -> ReviewStatusOut:
    with connect() as db:
        config = db.execute("SELECT review_threshold FROM discovery_config WHERE id = 'default'").fetchone()
    threshold = int(config["review_threshold"] if config and config["review_threshold"] else 3)
    backlog = _review_backlog_count()
    paused = backlog >= threshold
    reason = f"Review backlog is {backlog}/{threshold}; approve, decline, or request changes before more discovery." if paused else None
    return ReviewStatusOut(
        backlog_count=backlog,
        threshold=threshold,
        paused_for_review=paused,
        paused_reason=reason,
    )


def _review_backlog_count() -> int:
    with connect() as db:
        return int(db.execute(
            """
            SELECT COUNT(*)
            FROM jobs j
            JOIN application_packs p ON p.job_id = j.id
            WHERE p.status = 'ready'
              AND COALESCE(p.revision_state, 'current') != 'changes_requested'
              AND COALESCE(j.imported_state, '') != 'expired'
              AND NOT EXISTS (
                SELECT 1 FROM review_decisions rd
                WHERE rd.job_id = j.id AND rd.pack_version = p.version
              )
            """
        ).fetchone()[0])


def _update_review_pause_state() -> ReviewStatusOut:
    status = _review_status()
    with connect() as db:
        db.execute(
            """
            UPDATE discovery_config
            SET paused_for_review = ?, paused_reason = ?, updated_at = ?
            WHERE id = 'default'
            """,
            (1 if status.paused_for_review else 0, status.paused_reason, utc_now()),
        )
    return status


_REJECTED_AGENT_LETTER_OPENING = re.compile(
    r"\b(?:hiermit\s+bewerbe\s+ich\s+mich|ich\s+bewerbe\s+mich|ich\s+möchte\s+mich\s+bewerben|"
    r"ihre\s+stellenanzeige|die\s+ausgeschriebene\s+position|sie\s+suchen|"
    r"die\s+position\s+verbindet|in\s+dieser\s+rolle|die\s+aufgabe\s+umfasst)\b",
    re.IGNORECASE,
)
_RECRUITING_METADATA_IN_BODY = re.compile(
    r"\((?:junior|m\s*/\s*w\s*/\s*d|w\s*/\s*m\s*/\s*x|f\s*/\s*m\s*/\s*d|all\s+genders)\)",
    re.IGNORECASE,
)
_ADVERTISED_TECH_LEARNING = re.compile(
    r"\b(?:technologien|tech[- ]?stack|java|sql|javascript|typescript)\b[^.!?]{0,180}"
    r"\b(?:vertiefen|erlernen|ausbauen)\b",
    re.IGNORECASE,
)
_INFORMAL_LETTER_SIGNOFF = re.compile(
    r"mit\s+freundlichen\s+grüßen\s*\n+\s*toni\s*$",
    re.IGNORECASE,
)


def _agent_letter_opening(body: str) -> str:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    if not paragraphs:
        return ""
    opening = paragraphs[0]
    if opening.casefold().startswith("sehr geehrt"):
        if len(paragraphs) > 1:
            opening = paragraphs[1]
        elif "," in opening:
            opening = opening.split(",", 1)[1].strip()
    return opening


@app.post("/api/jobs/{job_id}/agent-pack", response_model=JobDetail)
def create_agent_pack(job_id: str, payload: AgentPackIn) -> JobDetail:
    opening = _agent_letter_opening(payload.letter_body)
    if _REJECTED_AGENT_LETTER_OPENING.search(opening):
        raise HTTPException(
            status_code=422,
            detail=(
                "Application letter opening must lead with verified candidate evidence; "
                "do not announce the application or explain the vacancy back to the employer."
            ),
        )
    with connect() as db:
        row = db.execute(
            """
            SELECT j.*, f.rating, f.reasons_json, f.note, f.updated_at AS feedback_updated_at
            FROM jobs j
            LEFT JOIN feedback f ON f.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if _RECRUITING_METADATA_IN_BODY.search(payload.letter_body):
        raise HTTPException(
            status_code=422,
            detail="Application letter body must not repeat recruiting metadata such as (Junior) or gender markers.",
        )
    if _ADVERTISED_TECH_LEARNING.search(payload.letter_body):
        raise HTTPException(
            status_code=422,
            detail="Application letter must present candidate evidence instead of promising to learn the advertised stack.",
        )
    if _INFORMAL_LETTER_SIGNOFF.search(payload.letter_body):
        raise HTTPException(
            status_code=422,
            detail="Application letter must use Antonio Beslic rather than the informal name Toni in the sign-off.",
        )
    draft = ApplicationDraft(
        resume_headline=payload.resume_headline,
        resume_summary_html=payload.resume_summary_html,
        subject=payload.letter_subject,
        body=payload.letter_body,
    )
    existing_pack = _application_pack(job_id)
    prepared = _prepare_application_pack(
        job_id,
        _karriere_detail_from_row(row),
        _analysis_from_row(row),
        force=True,
        revision_reasons=payload.revision_reasons,
        revision_note=payload.revision_note,
        revision_state="regenerated" if existing_pack is not None else "current",
        draft=draft,
        agent_model=payload.agent_model,
        agent_run_id=payload.agent_run_id,
        critic_notes=payload.critic_notes,
    )
    if not prepared:
        failed_pack = _application_pack(job_id)
        detail = failed_pack.error if failed_pack is not None else "Agent pack validation failed"
        raise HTTPException(status_code=422, detail=detail)
    now = utc_now()
    with connect() as db:
        db.execute(
            "UPDATE jobs SET status = 'inbox', reviewed_at = NULL, updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        updated = db.execute(
            """
            SELECT j.*, f.rating, f.reasons_json, f.note, f.updated_at AS feedback_updated_at
            FROM jobs j
            LEFT JOIN feedback f ON f.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
    if updated is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_detail(updated)


@app.post("/api/jobs/{job_id}/regenerate-pack", response_model=JobDetail)
def regenerate_pack(job_id: str, payload: RegeneratePackIn) -> JobDetail:
    with connect() as db:
        row = db.execute(
            """
            SELECT j.*, f.rating, f.reasons_json, f.note, f.updated_at AS feedback_updated_at
            FROM jobs j
            LEFT JOIN feedback f ON f.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Job not found")
    feedback_reasons = payload.reasons or decode_json(row["reasons_json"], [])
    feedback_note = payload.note.strip() or (row["note"] or "")
    now = utc_now()
    with connect() as db:
        db.execute(
            """
            UPDATE application_packs
            SET revision_state = 'changes_requested', revision_reasons_json = ?,
                revision_note = ?, error = 'Queued for the Luna application agent.', updated_at = ?
            WHERE job_id = ?
            """,
            (encode_json(feedback_reasons), feedback_note, now, job_id),
        )
        db.execute(
            "UPDATE jobs SET status = 'maybe', updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        db.execute(
            """
            INSERT INTO activity (id, kind, title, body, job_id, created_at)
            VALUES (?, 'package', ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                f"Queued AI regeneration for {row['company']}",
                "The Luna application agent will create the next CV and letter version.",
                job_id,
                now,
            ),
        )
        updated = db.execute(
            """
            SELECT j.*, f.rating, f.reasons_json, f.note, f.updated_at AS feedback_updated_at
            FROM jobs j
            LEFT JOIN feedback f ON f.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
    if updated is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_detail(updated)


@app.post("/api/jobs/{job_id}/cancel-pack-regeneration", response_model=JobDetail)
def cancel_pack_regeneration(job_id: str) -> JobDetail:
    now = utc_now()
    with connect() as db:
        pack = db.execute(
            "SELECT revision_state FROM application_packs WHERE job_id = ?",
            (job_id,),
        ).fetchone()
        if pack is None:
            raise HTTPException(status_code=404, detail="Application pack not found")
        if pack["revision_state"] != "changes_requested":
            raise HTTPException(status_code=409, detail="No pack regeneration is queued")
        db.execute(
            """
            UPDATE application_packs
            SET revision_state = 'current', revision_reasons_json = '[]',
                revision_note = '', error = NULL, updated_at = ?
            WHERE job_id = ?
            """,
            (now, job_id),
        )
        db.execute(
            "UPDATE jobs SET status = 'inbox', updated_at = ? WHERE id = ?",
            (now, job_id),
        )
        db.execute(
            """
            INSERT INTO activity (id, kind, title, body, job_id, created_at)
            VALUES (?, 'package', 'Cancelled AI regeneration',
                    'The existing application pack remains current.', ?, ?)
            """,
            (str(uuid.uuid4()), job_id, now),
        )
        updated = db.execute(
            """
            SELECT j.*, f.rating, f.reasons_json, f.note, f.updated_at AS feedback_updated_at
            FROM jobs j
            LEFT JOIN feedback f ON f.job_id = j.id
            WHERE j.id = ?
            """,
            (job_id,),
        ).fetchone()
    if updated is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_detail(updated)


@app.get("/api/preferences", response_model=Preferences)
def get_preferences() -> Preferences:
    with connect() as db:
        row = db.execute("SELECT * FROM preferences WHERE id = 'default'").fetchone()
    if row is None:
        return Preferences(updated_at=None)
    return _preferences_from_row(row)


@app.put("/api/preferences", response_model=Preferences)
def update_preferences(payload: Preferences) -> Preferences:
    now = utc_now()
    with connect() as db:
        db.execute(
            """
            INSERT INTO preferences (
                id, profile_summary, target_locations_json, work_modes_json, min_home_office_days,
                salary_currency, salary_target_min, salary_target_max, acceptable_salary_min,
                role_families_json, priority_role_families_json, priorities_json, hard_rules_json,
                discovery_queries_json, discovery_limit_per_query,
                language_preference, application_language, manual_submission_only, updated_at
            )
            VALUES ('default', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                profile_summary = excluded.profile_summary,
                target_locations_json = excluded.target_locations_json,
                work_modes_json = excluded.work_modes_json,
                min_home_office_days = excluded.min_home_office_days,
                salary_currency = excluded.salary_currency,
                salary_target_min = excluded.salary_target_min,
                salary_target_max = excluded.salary_target_max,
                acceptable_salary_min = excluded.acceptable_salary_min,
                role_families_json = excluded.role_families_json,
                priority_role_families_json = excluded.priority_role_families_json,
                priorities_json = excluded.priorities_json,
                hard_rules_json = excluded.hard_rules_json,
                discovery_queries_json = excluded.discovery_queries_json,
                discovery_limit_per_query = excluded.discovery_limit_per_query,
                language_preference = excluded.language_preference,
                application_language = excluded.application_language,
                manual_submission_only = excluded.manual_submission_only,
                updated_at = excluded.updated_at
            """,
            (
                payload.profile_summary.strip(),
                encode_json(payload.target_locations),
                encode_json(payload.work_modes),
                payload.min_home_office_days or 0,
                payload.salary_currency,
                payload.salary_target_min or 0,
                payload.salary_target_max,
                payload.salary_target_min or 0,
                encode_json(payload.role_families),
                encode_json(payload.priority_role_families),
                encode_json(payload.priorities),
                encode_json(payload.hard_rules),
                encode_json(payload.discovery_queries),
                payload.discovery_limit_per_query,
                payload.language_preference,
                payload.application_language,
                1 if payload.manual_submission_only else 0,
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO activity (id, kind, title, body, created_at)
            VALUES (?, 'preferences', 'Preferences updated', 'Search profile rules were edited.', ?)
            """,
            (str(uuid.uuid4()), now),
        )
    result = payload.model_copy(update={
        "profile_summary": payload.profile_summary.strip(),
        "min_home_office_days": payload.min_home_office_days or 0,
        "salary_target_min": payload.salary_target_min or 0,
        "acceptable_salary_min": payload.salary_target_min or 0,
        "updated_at": now,
    })
    return result


@app.get("/api/profile/documents", response_model=list[ProfileDocumentOut])
def list_profile_documents() -> list[ProfileDocumentOut]:
    with connect() as db:
        rows = db.execute(
            "SELECT id, original_name, media_type, size, created_at FROM profile_documents ORDER BY created_at DESC, id DESC"
        ).fetchall()
    return [
        ProfileDocumentOut(
            id=row["id"],
            name=row["original_name"],
            media_type=row["media_type"],
            size=row["size"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


@app.post("/api/profile/documents", response_model=ProfileDocumentOut, status_code=201)
async def upload_profile_document(
    request: Request,
    name: str = Query(min_length=1, max_length=240),
) -> ProfileDocumentOut:
    safe_name = Path(name).name.strip()
    suffix = Path(safe_name).suffix.lower()
    if not safe_name or safe_name != name.strip() or suffix not in PROFILE_DOCUMENT_EXTENSIONS:
        raise HTTPException(status_code=422, detail="Upload a PDF, image, DOC, or DOCX file with a valid filename")
    content = await request.body()
    if not content:
        raise HTTPException(status_code=422, detail="The uploaded file is empty")
    if len(content) > PROFILE_DOCUMENT_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Files may be at most 20 MB")

    document_id = str(uuid.uuid4())
    stored_name = f"{document_id}{suffix}"
    directory = _profile_document_directory()
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / stored_name
    temporary = directory / f".{stored_name}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        now = utc_now()
        media_type = (request.headers.get("content-type") or "application/octet-stream").split(";", 1)[0]
        with connect() as db:
            db.execute(
                "INSERT INTO profile_documents (id, original_name, stored_name, media_type, size, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (document_id, safe_name, stored_name, media_type, len(content), now),
            )
            db.execute(
                "INSERT INTO activity (id, kind, title, body, created_at) VALUES (?, 'profile_document', 'Supporting document added', ?, ?)",
                (str(uuid.uuid4()), safe_name, now),
            )
    except Exception:
        temporary.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise
    return ProfileDocumentOut(id=document_id, name=safe_name, media_type=media_type, size=len(content), created_at=now)


@app.get("/api/profile/documents/{document_id}")
def download_profile_document(document_id: str) -> FileResponse:
    with connect() as db:
        row = db.execute(
            "SELECT original_name, stored_name, media_type FROM profile_documents WHERE id = ?",
            (document_id,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    path = _profile_document_directory() / row["stored_name"]
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Stored document file is missing")
    return FileResponse(path, media_type=row["media_type"], filename=row["original_name"])


@app.delete("/api/profile/documents/{document_id}", status_code=204)
def delete_profile_document(document_id: str) -> Response:
    with connect() as db:
        row = db.execute(
            "SELECT original_name, stored_name FROM profile_documents WHERE id = ?",
            (document_id,),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Document not found")
        path = _profile_document_directory() / row["stored_name"]
        path.unlink(missing_ok=True)
        db.execute("DELETE FROM profile_documents WHERE id = ?", (document_id,))
        db.execute(
            "INSERT INTO activity (id, kind, title, body, created_at) VALUES (?, 'profile_document', 'Supporting document removed', ?, ?)",
            (str(uuid.uuid4()), row["original_name"], utc_now()),
        )
    return Response(status_code=204)


def _profile_document_directory() -> Path:
    return database_path().parent / "profile-documents"


@app.post("/api/discovery/search", response_model=list[DiscoverySearchResult])
def discovery_search(payload: DiscoverySearchIn) -> list[DiscoverySearchResult]:
    try:
        return [DiscoverySearchResult(**item) for item in search_web(payload.query, payload.limit)]
    except (FirecrawlConfigError, FirecrawlProviderError) as exc:
        raise _firecrawl_http_exception(exc) from exc


@app.post("/api/discovery/scrape", response_model=DiscoveryScrapeResult)
def discovery_scrape(payload: DiscoveryScrapeIn) -> DiscoveryScrapeResult:
    _validate_scrape_url(payload.url)
    try:
        return DiscoveryScrapeResult(**scrape_url(payload.url))
    except (FirecrawlConfigError, FirecrawlProviderError) as exc:
        raise _firecrawl_http_exception(exc) from exc


@app.get("/api/discovery/operations", response_model=DiscoveryOperationsOut)
def discovery_operations() -> DiscoveryOperationsOut:
    return _discovery_operations()


@app.put("/api/discovery/config", response_model=DiscoveryOperationsOut)
def update_discovery_config(payload: DiscoveryConfigIn) -> DiscoveryOperationsOut:
    try:
        ZoneInfo(payload.schedule.timezone)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Unknown discovery timezone") from exc
    now = utc_now()
    effective_sources = {source.id: source for source in _discovery_operations().sources}
    with connect() as db:
        known_sources = {row["id"]: dict(row) for row in db.execute("SELECT * FROM discovery_sources").fetchall()}
        unknown = sorted(set(payload.sources_enabled) - set(known_sources))
        if unknown:
            raise HTTPException(status_code=422, detail=f"Unknown discovery source: {unknown[0]}")
        for source_id, enabled in payload.sources_enabled.items():
            source = effective_sources[source_id]
            if enabled and source.status != "available":
                raise HTTPException(status_code=422, detail=f"{source.label} is {source.status.replace('_', ' ')}")
            db.execute(
                "UPDATE discovery_sources SET enabled = ?, updated_at = ? WHERE id = ?",
                (1 if enabled else 0, now, source_id),
            )
        db.execute(
            """
            UPDATE discovery_config
            SET schedule_enabled = ?, timezone = ?, schedule_times_json = ?, updated_at = ?
            WHERE id = 'default'
            """,
            (1 if payload.schedule.enabled else 0, payload.schedule.timezone, encode_json(payload.schedule.times), now),
        )
        db.execute(
            """
            INSERT INTO activity (id, kind, title, body, created_at)
            VALUES (?, 'discovery_config', 'Discovery schedule updated', ?, ?)
            """,
            (str(uuid.uuid4()), f"{payload.schedule.timezone} · {' / '.join(payload.schedule.times)}", now),
        )
    return _discovery_operations()


@app.post("/api/discovery/run", response_model=DiscoveryRunOut)
def discovery_run() -> DiscoveryRunOut:
    return _execute_discovery("manual")


@app.get("/api/activity", response_model=list[ActivityItem])
def activity(limit: int = Query(50, ge=1, le=200)) -> list[ActivityItem]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM activity ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [ActivityItem(**dict(row)) for row in rows]


@app.get("/api/dashboard/pulse", response_model=DashboardPulseOut)
def dashboard_pulse(days: int = Query(20, ge=7, le=31)) -> DashboardPulseOut:
    vienna = ZoneInfo("Europe/Vienna")
    today = datetime.now(timezone.utc).astimezone(vienna).date()
    first_day = today - timedelta(days=days - 1)
    counts = {first_day + timedelta(days=index): 0 for index in range(days)}
    with connect() as db:
        rows = db.execute("SELECT first_seen_at FROM jobs").fetchall()
    for row in rows:
        try:
            seen = datetime.fromisoformat(row["first_seen_at"].replace("Z", "+00:00"))
        except (AttributeError, TypeError, ValueError):
            continue
        if seen.tzinfo is None:
            seen = seen.replace(tzinfo=timezone.utc)
        local_day = seen.astimezone(vienna).date()
        if local_day in counts:
            counts[local_day] += 1
    pulse_days = [DailyPulseItem(date=day.isoformat(), count=count) for day, count in counts.items()]
    return DashboardPulseOut(days=pulse_days, today_count=counts[today])


@app.get("/api/integrations/reactive-resume", response_model=ReactiveResumeStatus)
def reactive_resume_status() -> ReactiveResumeStatus:
    return _reactive_resume_status()


@app.post("/api/integrations/reactive-resume/connect", response_model=ReactiveResumeStatus)
def reactive_resume_connect(payload: ReactiveResumeConnectIn) -> ReactiveResumeStatus:
    if not encryption_ready():
        raise HTTPException(status_code=503, detail="Encrypted secret storage is not configured")
    try:
        base_url = validate_base_url(payload.base_url)
        api_key = payload.api_key.get_secret_value()
        client = ReactiveResumeClient(api_key, base_url)
        resumes = client.list_resumes()
        options = _reactive_resume_options(resumes)
        canonical = [row for row in resumes if row.get("name") in {"Base CV", "Hermes Canonical Base CV"}]
        canonical.sort(key=lambda row: 0 if row.get("name") == "Base CV" else 1)
        reference = _reactive_resume_reference(client.get_resume(str(canonical[0]["id"]))) if canonical else None
        encrypted = encrypt_api_key(api_key)
    except (ValueError, ReactiveResumeError, SecretStoreError, KeyError) as exc:
        _record_reactive_resume_error(str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    now = utc_now()
    with connect() as db:
        db.execute(
            """
            UPDATE reactive_resume_config
            SET base_url = ?, encrypted_api_key = ?, configured_at = ?, verified_at = ?,
                last_error = NULL, reference_resume_id = ?, reference_resume_name = ?,
                reference_template = ?, reference_updated_at = ?, resumes_json = ?, updated_at = ?
            WHERE id = 1
            """,
            (
                base_url,
                encrypted,
                now,
                now,
                reference.id if reference else None,
                reference.name if reference else None,
                reference.template if reference else None,
                reference.updated_at if reference else None,
                encode_json([option.model_dump() for option in options]),
                now,
            ),
        )
        db.execute(
            "INSERT INTO activity(id, kind, title, body, job_id, created_at) VALUES (?, ?, ?, ?, NULL, ?)",
            (str(uuid.uuid4()), "integration", "Reactive Resume connected", "Reference CV connection verified", now),
        )
    return _reactive_resume_status()


@app.post("/api/integrations/reactive-resume/refresh", response_model=ReactiveResumeStatus)
def reactive_resume_refresh() -> ReactiveResumeStatus:
    row, client = _configured_reactive_resume_client()
    try:
        resumes = client.list_resumes()
        options = _reactive_resume_options(resumes)
        reference_id = row["reference_resume_id"]
        reference = None
        if reference_id:
            if not any(str(item.get("id", "")) == reference_id for item in resumes):
                raise ReactiveResumeError("Selected reference CV no longer exists")
            reference = _reactive_resume_reference(client.get_resume(reference_id))
    except ReactiveResumeError as exc:
        _record_reactive_resume_error(str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    now = utc_now()
    with connect() as db:
        db.execute(
            """
            UPDATE reactive_resume_config
            SET verified_at = ?, last_error = NULL, reference_resume_name = ?, reference_template = ?,
                reference_updated_at = ?, resumes_json = ?, updated_at = ?
            WHERE id = 1
            """,
            (
                now,
                reference.name if reference else None,
                reference.template if reference else None,
                reference.updated_at if reference else None,
                encode_json([option.model_dump() for option in options]),
                now,
            ),
        )
    return _reactive_resume_status()


@app.put("/api/integrations/reactive-resume/reference", response_model=ReactiveResumeStatus)
def reactive_resume_select_reference(payload: ReactiveResumeReferenceIn) -> ReactiveResumeStatus:
    _, client = _configured_reactive_resume_client()
    try:
        resumes = client.list_resumes()
    except ReactiveResumeError as exc:
        _record_reactive_resume_error(str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    selected = next((row for row in resumes if str(row.get("id", "")) == payload.resume_id), None)
    if selected is None:
        raise HTTPException(status_code=422, detail="Selected Reactive Resume CV was not found")
    if selected.get("name") == "Hermes Starting Template":
        raise HTTPException(
            status_code=422,
            detail="Hermes Starting Template is historical and cannot be the tailoring reference",
        )
    try:
        reference = _reactive_resume_reference(client.get_resume(payload.resume_id))
    except ReactiveResumeError as exc:
        _record_reactive_resume_error(str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    now = utc_now()
    with connect() as db:
        db.execute(
            """
            UPDATE reactive_resume_config
            SET reference_resume_id = ?, reference_resume_name = ?, reference_template = ?,
                reference_updated_at = ?, verified_at = ?, last_error = NULL, updated_at = ?
            WHERE id = 1
            """,
            (reference.id, reference.name, reference.template, reference.updated_at, now, now),
        )
    return _reactive_resume_status()


@app.delete("/api/integrations/reactive-resume", response_model=ReactiveResumeStatus)
def reactive_resume_disconnect() -> ReactiveResumeStatus:
    now = utc_now()
    with connect() as db:
        db.execute(
            """
            UPDATE reactive_resume_config
            SET base_url = ?, encrypted_api_key = NULL, configured_at = NULL, verified_at = NULL,
                last_error = NULL, reference_resume_id = NULL, reference_resume_name = NULL,
                reference_template = NULL, reference_updated_at = NULL, resumes_json = '[]', updated_at = ?
            WHERE id = 1
            """,
            (REACTIVE_RESUME_DEFAULT_BASE_URL, now),
        )
    return _reactive_resume_status()


@app.get("/api/integrations/reactive-resume/reference.pdf")
def reactive_resume_reference_pdf(download: bool = False) -> Response:
    row, client = _configured_reactive_resume_client()
    resume_id = row["reference_resume_id"]
    if not resume_id:
        raise HTTPException(status_code=404, detail="No Reactive Resume reference CV is selected")
    try:
        pdf = client.export_pdf(resume_id)
    except ReactiveResumeError as exc:
        _record_reactive_resume_error(str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    disposition = "attachment" if download else "inline"
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, no-store",
            "Content-Disposition": f'{disposition}; filename="jobflow-reference-cv.pdf"',
        },
    )


def _reactive_resume_status() -> ReactiveResumeStatus:
    with connect() as db:
        row = db.execute("SELECT * FROM reactive_resume_config WHERE id = 1").fetchone()
    configured = bool(row["encrypted_api_key"])
    reference = None
    if row["reference_resume_id"] and row["reference_resume_name"]:
        reference = ReactiveResumeReference(
            id=row["reference_resume_id"],
            name=row["reference_resume_name"],
            template=row["reference_template"],
            updated_at=row["reference_updated_at"],
        )
    options = [ReactiveResumeOption.model_validate(item) for item in decode_json(row["resumes_json"], [])]
    ready = encryption_ready()
    return ReactiveResumeStatus(
        encryption_ready=ready,
        configured=configured,
        verified=bool(configured and ready and row["verified_at"] and not row["last_error"]),
        base_url=row["base_url"],
        configured_at=row["configured_at"],
        last_verified_at=row["verified_at"],
        last_error=row["last_error"],
        reference=reference,
        available_resumes=options,
    )


def _configured_reactive_resume_client() -> tuple[Any, ReactiveResumeClient]:
    with connect() as db:
        row = db.execute("SELECT * FROM reactive_resume_config WHERE id = 1").fetchone()
    if not row["encrypted_api_key"]:
        raise HTTPException(status_code=409, detail="Reactive Resume is not connected")
    if not encryption_ready():
        raise HTTPException(status_code=503, detail="Encrypted secret storage is unavailable")
    try:
        api_key = decrypt_api_key(row["encrypted_api_key"])
        client = ReactiveResumeClient(api_key, row["base_url"])
    except (SecretStoreError, ValueError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return row, client


def _reactive_resume_options(resumes: list[dict[str, Any]]) -> list[ReactiveResumeOption]:
    options: list[ReactiveResumeOption] = []
    for row in resumes:
        resume_id = str(row.get("id", "")).strip()
        name = str(row.get("name", "")).strip()
        if not resume_id or not name:
            continue
        display_name = "Base CV" if name in {"Base CV", "Hermes Canonical Base CV"} else name
        options.append(
            ReactiveResumeOption(
                id=resume_id,
                name=display_name,
                updated_at=str(row.get("updatedAt")) if row.get("updatedAt") else None,
                historical_source=name == "Hermes Starting Template",
            )
        )
    return sorted(options, key=lambda option: option.name.casefold())


def _reactive_resume_reference(detail: dict[str, Any]) -> ReactiveResumeReference:
    resume_id = str(detail.get("id", "")).strip()
    name = str(detail.get("name", "")).strip()
    if not resume_id or not name:
        raise ReactiveResumeError("Reactive Resume detail is missing reference metadata")
    raw_data = detail.get("data")
    data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
    raw_metadata = data.get("metadata")
    metadata: dict[str, Any] = raw_metadata if isinstance(raw_metadata, dict) else {}
    template = str(metadata.get("template")) if metadata.get("template") else None
    updated_at = str(detail.get("updatedAt")) if detail.get("updatedAt") else None
    display_name = "Base CV" if name in {"Base CV", "Hermes Canonical Base CV"} else name
    return ReactiveResumeReference(id=resume_id, name=display_name, template=template, updated_at=updated_at)


def _record_reactive_resume_error(message: str) -> None:
    safe = message[:300]
    with connect() as db:
        db.execute(
            "UPDATE reactive_resume_config SET last_error = ?, updated_at = ? WHERE id = 1",
            (safe, utc_now()),
        )


def _discovery_operations() -> DiscoveryOperationsOut:
    with connect() as db:
        config = db.execute("SELECT * FROM discovery_config WHERE id = 'default'").fetchone()
        source_rows = db.execute("SELECT * FROM discovery_sources ORDER BY rowid").fetchall()
        run_rows = db.execute(
            "SELECT * FROM discovery_runs ORDER BY started_at DESC, id DESC LIMIT 20"
        ).fetchall()
    if config is None:
        raise HTTPException(status_code=500, detail="Discovery configuration is unavailable")
    schedule = DiscoveryScheduleConfig(
        enabled=bool(config["schedule_enabled"]),
        timezone=config["timezone"],
        times=decode_json(config["schedule_times_json"], ["07:00", "13:00", "19:00"]),
    )
    provider_ready = bool(os.environ.get("FIRECRAWL_API_URL") and os.environ.get("FIRECRAWL_API_KEY"))
    camofox_ready = camofox_available()
    sources: list[DiscoverySourceConfig] = []
    for row in source_rows:
        status = row["status"]
        detail = row["detail"]
        label = row["label"]
        if row["id"] in {"open_web", "company_careers"} and not provider_ready:
            status = "setup_required"
            detail = "Configure the JobFlow search provider before enabling this source."
        if row["id"] == "karriere_alerts":
            if camofox_ready:
                status = "available"
                label = "karriere.at via Camofox"
                detail = "Crawls public search and job-detail pages, then normalizes new jobs into JobFlow."
            elif agentmail_configured() and karriere_alerts_active():
                status = "available"
                label = "karriere.at Job Alarm fallback"
                detail = "Camofox is unavailable; official Job Alarm links remain connected as a fallback."
            elif agentmail_configured():
                status = "setup_required"
                detail = "Camofox is unavailable; AgentMail is connected as a fallback."
            else:
                status = "setup_required"
                detail = "Connect JobFlow to the private Camofox browser service."
        sources.append(
            DiscoverySourceConfig(
                id=row["id"],
                label=label,
                enabled=bool(row["enabled"]),
                status=status,
                detail=detail,
            )
        )
    preferences = get_preferences()
    enabled_source_ids = {source.id for source in sources if source.enabled and source.status == "available"}
    runs = [_discovery_run_summary(row) for row in run_rows]
    heartbeat = _scheduler_heartbeat_at
    scheduler_alive = heartbeat is not None and datetime.now(timezone.utc) - heartbeat <= timedelta(seconds=45)
    return DiscoveryOperationsOut(
        schedule=schedule,
        scheduler_alive=scheduler_alive,
        scheduler_heartbeat_at=heartbeat.replace(microsecond=0).isoformat() if heartbeat else None,
        sources=sources,
        generated_queries=_generated_discovery_queries(preferences, enabled_source_ids),
        next_run_at=_next_discovery_run(schedule),
        review=_review_status(),
        last_run=runs[0] if runs else None,
        recent_runs=runs,
    )


def _generated_discovery_queries(preferences: Preferences, enabled_source_ids: set[str]) -> list[str]:
    custom = _clean_list(preferences.discovery_queries)
    if custom:
        return custom[:12]
    priority_roles = _clean_list(preferences.priority_role_families)
    roles = priority_roles + [
        role for role in _clean_list(preferences.role_families)
        if role.casefold() not in {priority.casefold() for priority in priority_roles}
    ]
    locations = _specific_discovery_locations(preferences.target_locations) or ["Wien"]
    queries: list[str] = []
    for role in roles[:12]:
        for location in locations[:2]:
            suffix = " company careers" if enabled_source_ids == {"company_careers"} else " jobs"
            searchable_role = " ".join(role.replace("_", " ").split())
            queries.append(f"{searchable_role}{suffix} {location}")
            if len(queries) >= 12:
                return queries
    return queries


def _execute_discovery(trigger: Literal["manual", "scheduled"]) -> DiscoveryRunOut:
    run_id = str(uuid.uuid4())
    started_at = utc_now()
    preferences = get_preferences()
    operations = _discovery_operations()
    enabled_sources = {source.id for source in operations.sources if source.enabled and source.status == "available"}
    queries = _generated_discovery_queries(preferences, enabled_sources)
    with connect() as db:
        db.execute(
            """
            INSERT INTO discovery_runs (id, trigger, status, started_at, queries_json)
            VALUES (?, ?, 'running', ?, ?)
            """,
            (run_id, trigger, started_at, encode_json(queries)),
        )

    review = _update_review_pause_state()
    if review.paused_for_review:
        finished_at = utc_now()
        with connect() as db:
            db.execute(
                """
                UPDATE discovery_runs
                SET status = 'succeeded', finished_at = ?, paused_for_review = 1, paused_reason = ?
                WHERE id = ?
                """,
                (finished_at, review.paused_reason, run_id),
            )
            db.execute(
                """
                INSERT INTO activity (id, kind, title, body, created_at)
                VALUES (?, 'discovery_paused', 'Discovery paused for review', ?, ?)
                """,
                (str(uuid.uuid4()), review.paused_reason or "", finished_at),
            )
        _notify_review_threshold(review)
        return DiscoveryRunOut(
            run_id=run_id,
            queries=queries,
            limit_per_query=preferences.discovery_limit_per_query,
            results=[],
            paused_for_review=True,
            paused_reason=review.paused_reason,
        )

    try:
        if not enabled_sources:
            raise HTTPException(status_code=400, detail="Enable at least one available discovery source")
        web_enabled = bool(enabled_sources & {"open_web", "company_careers"})
        if web_enabled and not queries:
            raise HTTPException(status_code=400, detail="Add at least one role or custom search phrase")
        candidates: dict[str, DiscoveryRunResult] = {}
        candidate_count = 0
        karriere_details: list[KarriereJobDetail] = []
        if web_enabled:
            for query in queries:
                results = search_web(query, preferences.discovery_limit_per_query)
                candidate_count += len(results)
                for item in results:
                    try:
                        canonical_url = canonicalize_url(item["url"])
                    except ValueError:
                        continue
                    candidate = candidates.get(canonical_url)
                    if candidate is None:
                        candidates[canonical_url] = DiscoveryRunResult(
                            url=canonical_url,
                            title=item["title"],
                            description=item["description"],
                            source="open_web",
                            matched_queries=[query],
                        )
                    elif query not in candidate.matched_queries:
                        candidate.matched_queries.append(query)
        if "karriere_alerts" in enabled_sources:
            if camofox_available():
                raw_count, karriere_details = crawl_karriere(
                    queries,
                    limit_per_query=preferences.discovery_limit_per_query,
                    max_details=min(24, max(8, len(queries) * 2)),
                )
                candidate_count += raw_count
                for item in karriere_details:
                    candidates[item.url] = DiscoveryRunResult(
                        url=item.url,
                        title=item.title,
                        description=f"{item.company} · {item.location or 'location unavailable'}",
                        source="karriere_camofox",
                        matched_queries=item.matched_queries,
                    )
            else:
                with connect() as db:
                    seen_ids = {row["message_id"] for row in db.execute("SELECT message_id FROM agentmail_messages")}
                alerts = fetch_karriere_alerts(seen_ids)
                candidate_count += len(alerts.candidates)
                for item in alerts.candidates:
                    candidate = candidates.get(item.url)
                    if candidate is None:
                        candidates[item.url] = DiscoveryRunResult(
                            url=item.url,
                            title=item.title,
                            description="Official karriere.at Job Alarm link.",
                            source="karriere_alerts",
                            matched_queries=["karriere.at Job Alarm"],
                        )
                with connect() as db:
                    db.executemany(
                        "INSERT OR IGNORE INTO agentmail_messages(message_id, received_at, subject, link_count, processed_at) VALUES (?, ?, ?, ?, ?)",
                        [(item.message_id, item.received_at, item.subject, item.link_count, utc_now()) for item in alerts.messages],
                    )
            _append_untrusted_karriere_details(karriere_details)
    except (FirecrawlConfigError, FirecrawlProviderError) as exc:
        _finish_failed_discovery_run(run_id, str(exc))
        raise _firecrawl_http_exception(exc) from exc
    except AgentMailConfigError as exc:
        _finish_failed_discovery_run(run_id, str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except AgentMailProviderError as exc:
        _finish_failed_discovery_run(run_id, str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except CamofoxConfigError as exc:
        _finish_failed_discovery_run(run_id, str(exc))
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except CamofoxProviderError as exc:
        _finish_failed_discovery_run(run_id, str(exc))
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except HTTPException as exc:
        _finish_failed_discovery_run(run_id, str(exc.detail))
        raise
    except Exception as exc:
        _finish_failed_discovery_run(run_id, str(exc))
        raise

    finished_at = utc_now()
    result_items = list(candidates.values())
    jobs_added, jobs_evaluated, packs_prepared = _promote_karriere_details(
        karriere_details,
        preferences,
    )
    with connect() as db:
        db.executemany(
            """
            INSERT INTO discovery_candidates (run_id, url, source, title, description, matched_queries_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (run_id, item.url, item.source, item.title, item.description, encode_json(item.matched_queries))
                for item in result_items
            ],
        )
        db.execute(
            """
            UPDATE discovery_runs
            SET status = 'succeeded', finished_at = ?, candidate_count = ?, unique_count = ?,
                jobs_added = ?, jobs_evaluated = ?, packs_prepared = ?
            WHERE id = ?
            """,
            (
                finished_at,
                candidate_count,
                len(result_items),
                jobs_added,
                jobs_evaluated,
                packs_prepared,
                run_id,
            ),
        )
        db.execute(
            """
            INSERT INTO activity (id, kind, title, body, created_at)
            VALUES (?, 'discovery', ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                "Discovery search completed",
                f"{len(result_items)} unique candidates · {jobs_added} new jobs · {packs_prepared} prepared packs.",
                finished_at,
            ),
        )
    return DiscoveryRunOut(
        run_id=run_id,
        queries=queries,
        limit_per_query=preferences.discovery_limit_per_query,
        results=result_items,
        jobs_added=jobs_added,
        jobs_evaluated=jobs_evaluated,
        packs_prepared=packs_prepared,
        paused_for_review=False,
        paused_reason=None,
    )


def _promote_karriere_details(
    details: list[KarriereJobDetail],
    preferences: Preferences,
) -> tuple[int, int, int]:
    jobs_added = 0
    jobs_evaluated = 0
    packs_prepared = 0
    for detail in details:
        with connect() as db:
            existing = db.execute(
                "SELECT * FROM jobs WHERE source_url = ?",
                (detail.url,),
            ).fetchone()
        if existing is not None and not _karriere_detail_complete(detail):
            preserved = _karriere_detail_from_row(existing)
            if _karriere_detail_complete(preserved):
                detail = preserved
        created = ingest_job(
            JobIngestIn(
                source_id=detail.source_id,
                source_name="karriere.at",
                source_url=detail.url,
                title=detail.title,
                company=detail.company,
                location=detail.location,
                raw_description=detail.description,
                extracted_description=detail.description,
            )
        )
        if existing is None:
            jobs_added += 1
        else:
            # A repeated crawl refreshes source truth while preserving Toni's
            # lifecycle decision. This corrects stale/wrong locations and lets
            # newly available structured descriptions replace shell metadata.
            with connect() as db:
                db.execute(
                    """
                    UPDATE jobs SET title = ?, company = ?, location = ?,
                        raw_description = ?, extracted_description = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        detail.title,
                        detail.company,
                        detail.location,
                        detail.description,
                        detail.description,
                        utc_now(),
                        created.id,
                    ),
                )
        if created.status == "bad":
            continue
        analysis = analyze_karriere_job(detail, preferences)
        duplicate_winner = _semantic_duplicate_winner(created.id)
        if duplicate_winner is not None:
            analysis.hard_gate_reasons.append("Duplicate advertisement already represented by another JobFlow record.")
            analysis.verdict = "reject"
        update_job_analysis(created.id, analysis)
        if existing is None or existing["score"] is None:
            jobs_evaluated += 1
        if created.status == "maybe":
            # Scheduled runs may refresh source facts, but a requested revision
            # stays pending until Toni explicitly regenerates it.
            continue
        current_pack = _application_pack(created.id)
        if not _analysis_allows_pack(analysis):
            if current_pack is not None and current_pack.status == "ready" and created.status == "inbox":
                _record_application_pack_version(created.id, current_pack)
                _store_application_pack(
                    created.id,
                    status="failed",
                    error="Current verified source facts do not pass the saved hard gates.",
                    revision_state="current",
                    now=utc_now(),
                )
            continue
        # Search and source normalization are deterministic. Application content is
        # created only by the scheduled Luna evaluator/writer through /agent-pack.
        # Existing packs can still be invalidated when refreshed source facts fail
        # the hard gates, but no template content is generated here.
    return jobs_added, jobs_evaluated, packs_prepared


def _semantic_duplicate_winner(job_id: str) -> str | None:
    """Return one canonical record for same-employer adverts differing only by gender markers."""
    with connect() as db:
        current = db.execute(
            "SELECT id, title, company, extracted_description, first_seen_at FROM jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        if current is None or len((current["extracted_description"] or "").strip()) < 500:
            return None
        rows = db.execute(
            """
            SELECT id, title, extracted_description, first_seen_at FROM jobs
            WHERE LOWER(TRIM(company)) = LOWER(TRIM(?))
            """,
            (current["company"],),
        ).fetchall()
    current_title = _normalize_duplicate_text(current["title"])
    current_description = _normalize_duplicate_text(current["extracted_description"])
    matches = [
        row for row in rows
        if _normalize_duplicate_text(row["title"]) == current_title
        and _normalize_duplicate_text(row["extracted_description"]) == current_description
    ]
    matches.sort(key=lambda row: (row["first_seen_at"], row["id"]))
    if not matches or matches[0]["id"] == job_id:
        return None
    return str(matches[0]["id"])


def _normalize_duplicate_text(value: str) -> str:
    folded = value.casefold()
    folded = re.sub(r"\((?:all genders|[mwfdx*/:\s-]+)\)", " ", folded)
    return " ".join(re.sub(r"[^a-z0-9äöüß+#.]+", " ", folded).split())


def _pack_needs_writer_upgrade(pack: Any) -> bool:
    body = (pack.letter_body or "").casefold()
    return any(marker in body for marker in (
        "die ausschreibung nennt",
        "für diese rolle greife ich besonders",
        "design, develop, and maintain",
    ))


def _append_untrusted_karriere_details(
    details: list[KarriereJobDetail],
    *,
    max_details: int = 12,
) -> None:
    """Boundedly self-heal incomplete Inbox rows omitted by current listings."""
    seen = {detail.url for detail in details}
    with connect() as db:
        rows = db.execute(
            """
            SELECT * FROM jobs
            WHERE status = 'inbox'
              AND source_name = 'karriere.at'
              AND source_url LIKE 'https://www.karriere.at/jobs/%'
              AND (
                LENGTH(TRIM(COALESCE(extracted_description, ''))) < 180
                OR requirements_json = '[]'
                OR responsibilities_json = '[]'
                OR EXISTS (
                  SELECT 1 FROM application_packs ap
                  WHERE ap.job_id = jobs.id
                    AND ap.status = 'ready'
                    AND (
                      NOT EXISTS (
                        SELECT 1 FROM application_pack_versions apv
                        WHERE apv.job_id = jobs.id
                      )
                      OR ap.letter_body LIKE '%Die Ausschreibung nennt%'
                      OR ap.letter_body LIKE '%Für diese Rolle greife ich besonders%'
                      OR ap.letter_body LIKE '%design, develop, and maintain%'
                    )
                )
              )
            ORDER BY CASE WHEN EXISTS (
              SELECT 1 FROM application_packs upgrade
              WHERE upgrade.job_id = jobs.id
                AND upgrade.status = 'ready'
                AND (
                  upgrade.letter_body LIKE '%Die Ausschreibung nennt%'
                  OR upgrade.letter_body LIKE '%Für diese Rolle greife ich besonders%'
                  OR upgrade.letter_body LIKE '%design, develop, and maintain%'
                )
            ) THEN 0 ELSE 1 END,
            updated_at DESC
            LIMIT ?
            """,
            (max_details,),
        ).fetchall()
    for row in rows:
        if row["source_url"] in seen:
            continue
        detail = _karriere_detail_from_row(row)
        try:
            refresh_karriere_detail(detail)
        except KarriereExpiredError:
            _expire_ready_job(row["id"])
            continue
        except CamofoxProviderError:
            continue
        details.append(detail)
        seen.add(detail.url)


def _expire_ready_job(job_id: str) -> None:
    now = utc_now()
    with connect() as db:
        db.execute(
            """
            UPDATE application_packs
            SET status = 'failed', error = 'Source advertisement has expired.', updated_at = ?
            WHERE job_id = ? AND status = 'ready'
            """,
            (now, job_id),
        )
        db.execute(
            "UPDATE jobs SET imported_state = 'expired', updated_at = ? WHERE id = ?",
            (now, job_id),
        )


def _prepare_application_pack(
    job_id: str,
    detail: KarriereJobDetail,
    analysis: JobAnalysisIn,
    *,
    force: bool = False,
    revision_reasons: list[str] | None = None,
    revision_note: str = "",
    revision_state: Literal["current", "regenerated"] = "current",
    draft: ApplicationDraft | None = None,
    agent_model: str | None = None,
    agent_run_id: str | None = None,
    critic_notes: str | None = None,
) -> bool:
    existing = _application_pack(job_id)
    if existing is not None and existing.status == "ready" and not force:
        return False
    if existing is not None and existing.status == "ready" and force:
        _record_application_pack_version(job_id, existing)
    if not _analysis_allows_pack(analysis):
        _store_application_pack(
            job_id,
            status="failed",
            error="Pack blocked because required source facts or hard gates are not satisfied.",
            revision_reasons=revision_reasons or [],
            revision_note=revision_note,
            revision_state=revision_state,
            now=utc_now(),
        )
        return False
    if draft is None or not agent_model or not agent_run_id or not critic_notes:
        _store_application_pack(
            job_id,
            status="failed",
            error="An agent-authored draft with model, run, and critic metadata is required.",
            revision_reasons=revision_reasons or [],
            revision_note=revision_note,
            revision_state=revision_state,
            now=utc_now(),
        )
        return False
    quality_issues = application_draft_quality_issues(detail, draft)
    if quality_issues:
        _store_application_pack(
            job_id,
            status="failed",
            letter_subject=draft.subject,
            letter_body=draft.body,
            revision_reasons=revision_reasons or [],
            revision_note=revision_note,
            revision_state=revision_state,
            error="Draft quality gate failed: " + "; ".join(quality_issues)[:240],
            now=utc_now(),
        )
        return False
    now = utc_now()
    version = (existing.version + 1) if force and existing else (existing.version if existing else 1)
    _store_application_pack(
        job_id,
        status="preparing",
        letter_subject=draft.subject,
        letter_body=draft.body,
        version=version,
        revision_state=revision_state,
        revision_reasons=revision_reasons or [],
        revision_note=revision_note,
        agent_model=agent_model,
        agent_run_id=agent_run_id,
        critic_notes=critic_notes,
        error=None,
        now=now,
    )
    try:
        config, client = _configured_reactive_resume_client()
        reference_id = config["reference_resume_id"]
        if not reference_id:
            raise ReactiveResumeError("Base CV is not selected")
        slug = f"jobflow-{job_id[:16]}-v{version}"
        resume_name = f"{detail.company} · {detail.title}"[:160]
        resume_id = next(
            (
                str(item["id"])
                for item in client.list_resumes()
                if str(item.get("slug", "")) == slug and item.get("id")
            ),
            "",
        )
        if not resume_id:
            resume_id = client.duplicate_resume(
                reference_id,
                name=resume_name,
                slug=slug,
                tags=["jobflow", "prepared"],
            )
        resume = client.get_resume(resume_id)
        operations = [
            {"op": "replace", "path": "/basics/headline", "value": draft.resume_headline},
            {"op": "replace", "path": "/summary/content", "value": draft.resume_summary_html},
        ]
        try:
            client.patch_resume(
                resume_id,
                operations=operations,
                expected_updated_at=str(resume.get("updatedAt")) if resume.get("updatedAt") else None,
            )
        except ReactiveResumeError as exc:
            if "HTTP 409" not in str(exc):
                raise
            # This is a new JobFlow-owned duplicate. Reactive Resume can serialize
            # timestamps at lower precision than its database; retrying without the
            # optimistic timestamp is bounded to these two deterministic fields.
            client.patch_resume(resume_id, operations=operations, expected_updated_at=None)
        verified = client.get_resume(resume_id)
        raw_data = verified.get("data")
        data: dict[str, Any] = raw_data if isinstance(raw_data, dict) else {}
        raw_basics = data.get("basics")
        basics: dict[str, Any] = raw_basics if isinstance(raw_basics, dict) else {}
        raw_summary = data.get("summary")
        summary: dict[str, Any] = raw_summary if isinstance(raw_summary, dict) else {}
        if basics.get("headline") != draft.resume_headline or summary.get("content") != draft.resume_summary_html:
            raise ReactiveResumeError("Job-specific CV read-back verification failed")
        pdf = client.export_pdf(resume_id)
        pages = len(re.findall(rb"/Type\s*/Page\b", pdf))
        if pages != 1:
            raise ReactiveResumeError(f"Job-specific CV rendered to {pages} pages instead of one")
        _store_application_pack(
            job_id,
            status="ready",
            resume_id=resume_id,
            resume_name=resume_name,
            resume_pdf_pages=pages,
            letter_subject=draft.subject,
            letter_body=draft.body,
            version=version,
            revision_state=revision_state,
            revision_reasons=revision_reasons or [],
            revision_note=revision_note,
            agent_model=agent_model,
            agent_run_id=agent_run_id,
            critic_notes=critic_notes,
            error=None,
            now=utc_now(),
        )
        ready_pack = _application_pack(job_id)
        if ready_pack is not None:
            _record_application_pack_version(job_id, ready_pack)
        with connect() as db:
            db.execute(
                "INSERT INTO activity(id, kind, title, body, job_id, created_at) VALUES (?, 'package', ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()),
                    f"Prepared application pack for {detail.company}",
                    "Job-specific one-page CV and German application letter are ready.",
                    job_id,
                    utc_now(),
                ),
            )
        _notify_pack_ready(job_id, version, revision_state)
        _update_review_pause_state()
        return True
    except (HTTPException, ReactiveResumeError, SecretStoreError, ValueError, KeyError) as exc:
        _store_application_pack(
            job_id,
            status="failed",
            letter_subject=draft.subject,
            letter_body=draft.body,
            version=version,
            revision_state=revision_state,
            revision_reasons=revision_reasons or [],
            revision_note=revision_note,
            error=str(exc)[:300],
            now=utc_now(),
        )
        return False


def _store_application_pack(
    job_id: str,
    *,
    status: Literal["preparing", "ready", "failed"],
    now: str,
    version: int | None = None,
    revision_state: Literal["current", "changes_requested", "regenerated"] = "current",
    revision_reasons: list[str] | None = None,
    revision_note: str = "",
    resume_id: str | None = None,
    resume_name: str | None = None,
    resume_pdf_pages: int | None = None,
    letter_subject: str | None = None,
    letter_body: str | None = None,
    agent_model: str | None = None,
    agent_run_id: str | None = None,
    critic_notes: str | None = None,
    error: str | None = None,
) -> None:
    with connect() as db:
        db.execute(
            """
            INSERT INTO application_packs(
                job_id, status, version, revision_state, revision_reasons_json, revision_note,
                resume_id, resume_name, resume_pdf_pages, letter_subject, letter_body,
                agent_model, agent_run_id, critic_notes, error, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(job_id) DO UPDATE SET
                status = excluded.status,
                version = COALESCE(excluded.version, application_packs.version),
                revision_state = excluded.revision_state,
                revision_reasons_json = excluded.revision_reasons_json,
                revision_note = excluded.revision_note,
                resume_id = COALESCE(excluded.resume_id, application_packs.resume_id),
                resume_name = COALESCE(excluded.resume_name, application_packs.resume_name),
                resume_pdf_pages = COALESCE(excluded.resume_pdf_pages, application_packs.resume_pdf_pages),
                letter_subject = COALESCE(excluded.letter_subject, application_packs.letter_subject),
                letter_body = COALESCE(excluded.letter_body, application_packs.letter_body),
                agent_model = COALESCE(excluded.agent_model, application_packs.agent_model),
                agent_run_id = COALESCE(excluded.agent_run_id, application_packs.agent_run_id),
                critic_notes = COALESCE(excluded.critic_notes, application_packs.critic_notes),
                error = excluded.error,
                updated_at = excluded.updated_at
            """,
            (
                job_id,
                status,
                version or 1,
                revision_state,
                encode_json(revision_reasons or []),
                revision_note.strip(),
                resume_id,
                resume_name,
                resume_pdf_pages,
                letter_subject,
                letter_body,
                agent_model,
                agent_run_id,
                critic_notes,
                error,
                now,
                now,
            ),
        )


def _application_pack(job_id: str) -> ApplicationPackOut | None:
    with connect() as db:
        row = db.execute("SELECT * FROM application_packs WHERE job_id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return ApplicationPackOut(
        status=row["status"],
        version=row["version"] or 1,
        revision_state=row["revision_state"] or "current",
        revision_reasons=decode_json(row["revision_reasons_json"], []),
        revision_note=row["revision_note"] or "",
        resume_id=row["resume_id"],
        resume_name=row["resume_name"],
        resume_pdf_pages=row["resume_pdf_pages"],
        letter_subject=row["letter_subject"],
        letter_body=row["letter_body"],
        agent_model=row["agent_model"],
        agent_run_id=row["agent_run_id"],
        critic_notes=row["critic_notes"],
        error=row["error"],
        updated_at=row["updated_at"],
        versions=_application_pack_versions(job_id),
    )


def _application_pack_versions(job_id: str) -> list[ApplicationPackVersionOut]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM application_pack_versions WHERE job_id = ? ORDER BY version DESC",
            (job_id,),
        ).fetchall()
    return [
        ApplicationPackVersionOut(
            version=row["version"],
            revision_state=row["revision_state"] or "current",
            revision_reasons=decode_json(row["revision_reasons_json"], []),
            revision_note=row["revision_note"] or "",
            resume_id=row["resume_id"],
            resume_name=row["resume_name"],
            resume_pdf_pages=row["resume_pdf_pages"],
            letter_subject=row["letter_subject"],
            letter_body=row["letter_body"],
            agent_model=row["agent_model"],
            agent_run_id=row["agent_run_id"],
            critic_notes=row["critic_notes"],
            created_at=row["created_at"],
        )
        for row in rows
    ]


def _application_pack_version(job_id: str, version: int) -> ApplicationPackVersionOut | None:
    return next((item for item in _application_pack_versions(job_id) if item.version == version), None)


def _record_application_pack_version(job_id: str, pack: ApplicationPackOut) -> None:
    if pack.status != "ready":
        return
    with connect() as db:
        db.execute(
            """
            INSERT OR IGNORE INTO application_pack_versions(
                job_id, version, revision_state, revision_reasons_json, revision_note,
                resume_id, resume_name, resume_pdf_pages, letter_subject, letter_body,
                agent_model, agent_run_id, critic_notes, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                pack.version,
                pack.revision_state,
                encode_json(pack.revision_reasons),
                pack.revision_note,
                pack.resume_id,
                pack.resume_name,
                pack.resume_pdf_pages,
                pack.letter_subject,
                pack.letter_body,
                pack.agent_model,
                pack.agent_run_id,
                pack.critic_notes,
                pack.updated_at,
            ),
        )


def _analysis_allows_pack(analysis: JobAnalysisIn) -> bool:
    blocking_missing = {
        "Source description",
        "Requirements",
        "Responsibilities",
        "Exact work location",
    }
    return (
        analysis.score >= 55
        and not analysis.hard_gate_reasons
        and not (blocking_missing & set(analysis.missing_info))
    )


def _karriere_detail_complete(detail: KarriereJobDetail) -> bool:
    return (
        len(detail.description.strip()) >= 180
        and bool(detail.requirements)
        and bool(detail.responsibilities)
    )


def _ready_pack_sql() -> str:
    return """
        j.status = 'inbox'
        AND COALESCE(j.hard_gate_reasons_json, '[]') = '[]'
        AND LENGTH(TRIM(COALESCE(j.extracted_description, ''))) >= 180
        AND COALESCE(j.requirements_json, '[]') != '[]'
        AND COALESCE(j.responsibilities_json, '[]') != '[]'
        AND j.location IS NOT NULL
        AND j.salary_min_annual IS NOT NULL
        AND EXISTS (
            SELECT 1
            FROM application_packs p
            WHERE p.job_id = j.id
              AND p.status = 'ready'
              AND COALESCE(p.revision_state, 'current') != 'changes_requested'
              AND p.resume_id IS NOT NULL
              AND p.letter_body IS NOT NULL
              AND p.resume_pdf_pages = 1
              AND NOT EXISTS (
                SELECT 1
                FROM review_decisions rd
                WHERE rd.job_id = p.job_id
                  AND rd.pack_version = p.version
              )
        )
    """


def _karriere_detail_from_row(row: Any) -> KarriereJobDetail:
    return KarriereJobDetail(
        url=row["source_url"],
        source_id=row["source_id"] or row["id"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        description=row["extracted_description"] or row["raw_description"] or row["summary"] or "",
        salary_display=row["salary_display"],
        salary_min_annual=row["salary_min_annual"],
        salary_max_annual=row["salary_max_annual"],
        work_mode=row["work_mode"],
        requirements=decode_json(row["requirements_json"], []),
        responsibilities=decode_json(row["responsibilities_json"], []),
        technologies=decode_json(row["technologies_json"], []),
        home_office_days=row["home_office_days"],
    )


def _analysis_from_row(row: Any) -> JobAnalysisIn:
    return JobAnalysisIn(
        score=row["score"] or 0,
        verdict=row["verdict"] or "reject",
        confidence=row["confidence"],
        summary=row["summary"],
        fit_evidence=_normalized_fit_evidence(decode_json(row["fit_evidence_json"], {})),
        missing_info=decode_json(row["missing_info_json"], []),
        hard_gate_reasons=decode_json(row["hard_gate_reasons_json"], []),
        requirements=decode_json(row["requirements_json"], []),
        responsibilities=decode_json(row["responsibilities_json"], []),
        technologies=decode_json(row["technologies_json"], []),
        salary_display=row["salary_display"],
        salary_min_annual=row["salary_min_annual"],
        salary_max_annual=row["salary_max_annual"],
        salary_currency=row["salary_currency"],
        work_mode=row["work_mode"],
        home_office_days=row["home_office_days"],
        language_environment=row["language_environment"],
        source_evidence=decode_json(row["source_evidence_json"], {}),
    )


def _finish_failed_discovery_run(run_id: str, error: str) -> None:
    finished_at = utc_now()
    with connect() as db:
        db.execute(
            "UPDATE discovery_runs SET status = 'failed', finished_at = ?, error = ? WHERE id = ?",
            (finished_at, error[:500], run_id),
        )
        db.execute(
            """
            INSERT INTO activity (id, kind, title, body, created_at)
            VALUES (?, 'discovery_error', 'Discovery search failed', ?, ?)
            """,
            (str(uuid.uuid4()), error[:500], finished_at),
        )


def _discovery_run_summary(row: Any) -> DiscoveryRunSummary:
    return DiscoveryRunSummary(
        id=row["id"],
        trigger=row["trigger"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        queries=decode_json(row["queries_json"], []),
        candidate_count=row["candidate_count"],
        unique_count=row["unique_count"],
        jobs_added=row["jobs_added"],
        jobs_evaluated=row["jobs_evaluated"],
        packs_prepared=row["packs_prepared"],
        error=row["error"],
        paused_for_review=bool(row["paused_for_review"]),
        paused_reason=row["paused_reason"],
    )


def _next_discovery_run(schedule: DiscoveryScheduleConfig) -> str | None:
    if not schedule.enabled:
        return None
    zone = ZoneInfo(schedule.timezone)
    now = datetime.now(timezone.utc).astimezone(zone)
    for day_offset in range(2):
        day = now.date() + timedelta(days=day_offset)
        for text in schedule.times:
            hour, minute = (int(part) for part in text.split(":"))
            candidate = datetime(day.year, day.month, day.day, hour, minute, tzinfo=zone)
            if candidate > now:
                return candidate.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return None


async def _discovery_scheduler() -> None:
    global _scheduler_heartbeat_at
    while True:
        _scheduler_heartbeat_at = datetime.now(timezone.utc)
        try:
            await asyncio.to_thread(_run_due_discovery)
        except Exception:
            pass
        finally:
            _scheduler_heartbeat_at = datetime.now(timezone.utc)
        await asyncio.sleep(20)


def _run_due_discovery() -> None:
    _send_daily_review_reminder()
    with connect() as db:
        config = db.execute("SELECT * FROM discovery_config WHERE id = 'default'").fetchone()
        if config is None or not config["schedule_enabled"]:
            return
        zone = ZoneInfo(config["timezone"])
        local_now = datetime.now(timezone.utc).astimezone(zone)
        current_time = local_now.strftime("%H:%M")
        times = decode_json(config["schedule_times_json"], [])
        if current_time not in times:
            return
        slot = f"{local_now.date().isoformat()}T{current_time}@{config['timezone']}"
        cursor = db.execute(
            """
            UPDATE discovery_config SET last_scheduled_slot = ?
            WHERE id = 'default' AND (last_scheduled_slot IS NULL OR last_scheduled_slot != ?)
            """,
            (slot, slot),
        )
        reserved = cursor.rowcount == 1
    if reserved:
        _execute_discovery("scheduled")


def _feedback_from_row(row: Any) -> FeedbackOut | None:
    if row["rating"] is None:
        return None
    return FeedbackOut(
        rating=row["rating"],
        reasons=decode_json(row["reasons_json"], []),
        note=row["note"] or "",
        updated_at=row["feedback_updated_at"],
    )


def _review_decision_for_pack(job_id: str, pack_version: int | None) -> ReviewDecisionOut | None:
    if pack_version is None:
        return None
    with connect() as db:
        row = db.execute(
            "SELECT * FROM review_decisions WHERE job_id = ? AND pack_version = ?",
            (job_id, pack_version),
        ).fetchone()
    if row is None:
        return None
    return ReviewDecisionOut(
        job_id=row["job_id"],
        pack_version=row["pack_version"],
        decision=row["decision"],
        reasons=decode_json(row["reasons_json"], []),
        note=row["note"] or "",
        updated_at=row["updated_at"],
    )


def _application_task(job_id: str, pack_version: int | None = None) -> ApplicationTaskOut | None:
    params: tuple[Any, ...]
    where = "job_id = ?"
    params = (job_id,)
    if pack_version is not None:
        where += " AND pack_version = ?"
        params = (job_id, pack_version)
    with connect() as db:
        row = db.execute(
            f"SELECT * FROM application_tasks WHERE {where} ORDER BY pack_version DESC LIMIT 1",
            params,
        ).fetchone()
    if row is None:
        return None
    return ApplicationTaskOut(
        id=row["id"],
        job_id=row["job_id"],
        pack_version=row["pack_version"],
        state=row["state"],
        required_fields=decode_json(row["required_fields_json"], []),
        questions=decode_json(row["questions_json"], []),
        report=row["report"] or "",
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


def _job_list_item(row: Any) -> JobListItem:
    pack = _application_pack(row["id"])
    return JobListItem(
        id=row["id"],
        title=row["title"],
        company=row["company"],
        location=row["location"],
        score=row["score"],
        verdict=row["verdict"],
        confidence=row["confidence"],
        status=row["status"],
        summary=row["summary"],
        salary_display=row["salary_display"],
        work_mode=row["work_mode"],
        missing_info=decode_json(row["missing_info_json"], []),
        first_seen_at=row["first_seen_at"],
        source_url=row["source_url"],
        feedback=_feedback_from_row(row),
        review_decision=_review_decision_for_pack(row["id"], pack.version if pack is not None else None),
        pack_status=pack.status if pack is not None else None,
        pack_revision_state=pack.revision_state if pack is not None else None,
    )


def _normalized_fit_evidence(value: Any) -> dict[str, list[EvidenceItem]]:
    if not isinstance(value, dict):
        return {}
    normalized: dict[str, list[EvidenceItem]] = {}
    for key, raw_items in value.items():
        items = raw_items if isinstance(raw_items, list) else [raw_items]
        cleaned: list[EvidenceItem] = []
        for item in items:
            if isinstance(item, str) and item.strip():
                cleaned.append(EvidenceItem(origin="legacy import", text=item.strip()))
            elif isinstance(item, dict) and isinstance(item.get("text"), str) and item["text"].strip():
                cleaned.append(EvidenceItem(
                    origin=str(item.get("origin")) if item.get("origin") else None,
                    text=item["text"].strip(),
                    profile_fact_ref=str(item.get("profile_fact_ref")) if item.get("profile_fact_ref") else None,
                ))
        if cleaned:
            normalized[str(key)] = cleaned
    return normalized


def _job_detail(row: Any) -> JobDetail:
    base = _job_list_item(row).model_dump()
    pack = _application_pack(row["id"])
    return JobDetail(
        **base,
        source_name=row["source_name"],
        raw_description=row["raw_description"],
        extracted_description=row["extracted_description"],
        fit_evidence=_normalized_fit_evidence(decode_json(row["fit_evidence_json"], {})),
        source_evidence=decode_json(row["source_evidence_json"], {}),
        hard_gate_reasons=decode_json(row["hard_gate_reasons_json"], []),
        requirements=decode_json(row["requirements_json"], []),
        responsibilities=decode_json(row["responsibilities_json"], []),
        technologies=decode_json(row["technologies_json"], []),
        salary_min_annual=row["salary_min_annual"],
        salary_max_annual=row["salary_max_annual"],
        salary_currency=row["salary_currency"],
        home_office_days=row["home_office_days"],
        language_environment=row["language_environment"],
        imported_state=row["imported_state"],
        updated_at=row["updated_at"],
        reviewed_at=row["reviewed_at"],
        application_pack=pack,
        application_task=_application_task(row["id"], pack.version if pack is not None else None),
    )


def _preferences_from_row(row: Any) -> Preferences:
    return Preferences(
        profile_summary=row["profile_summary"] or "",
        target_locations=decode_json(row["target_locations_json"], []),
        work_modes=decode_json(row["work_modes_json"], []),
        min_home_office_days=row["min_home_office_days"] or 0,
        salary_currency=row["salary_currency"],
        salary_target_min=row["salary_target_min"] or 0,
        salary_target_max=row["salary_target_max"],
        # Salary target minimum is the sole public and scoring source of truth.
        acceptable_salary_min=row["salary_target_min"] or 0,
        role_families=decode_json(row["role_families_json"], []),
        priority_role_families=decode_json(row["priority_role_families_json"], []),
        priorities=decode_json(row["priorities_json"], []),
        hard_rules=decode_json(row["hard_rules_json"], []),
        discovery_queries=decode_json(row["discovery_queries_json"], []),
        discovery_limit_per_query=row["discovery_limit_per_query"] or 5,
        language_preference=row["language_preference"],
        application_language=row["application_language"],
        manual_submission_only=bool(row["manual_submission_only"]),
        updated_at=row["updated_at"],
    )


def _firecrawl_http_exception(exc: FirecrawlConfigError | FirecrawlProviderError) -> HTTPException:
    if isinstance(exc, FirecrawlConfigError):
        return HTTPException(status_code=503, detail=str(exc))
    return HTTPException(status_code=502, detail=str(exc))


def _validate_scrape_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(status_code=422, detail="URL must be absolute HTTP or HTTPS")


def _clean_list(values: list[str]) -> list[str]:
    cleaned: list[str] = []
    for value in values:
        text = " ".join(str(value).split())
        if text and text not in cleaned:
            cleaned.append(text)
    return cleaned


def _specific_discovery_locations(values: list[str]) -> list[str]:
    cleaned = _clean_list(values)
    if len(cleaned) <= 1:
        return cleaned
    broad = {"at", "austria", "österreich", "osterreich"}
    specific = [value for value in cleaned if value.casefold() not in broad]
    return specific or cleaned


def _subscription_endpoint(subscription: dict[str, object]) -> str:
    endpoint = str(subscription.get("endpoint") or "").strip()
    keys = subscription.get("keys")
    if not endpoint or not isinstance(keys, dict) or not keys.get("p256dh") or not keys.get("auth"):
        raise HTTPException(status_code=422, detail="Push subscription must include endpoint, p256dh, and auth")
    return endpoint


def _vapid_private_key_path() -> Path:
    return database_path().parent / "jobflow-vapid-private.pem"


def _vapid_public_key() -> str:
    private_key = _load_or_create_vapid_private_key()
    public_numbers = private_key.public_key().public_numbers()
    raw = (
        b"\x04"
        + public_numbers.x.to_bytes(32, "big")
        + public_numbers.y.to_bytes(32, "big")
    )
    return _b64url_encode(raw)


def _load_or_create_vapid_private_key() -> ec.EllipticCurvePrivateKey:
    path = _vapid_private_key_path()
    if path.exists():
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    path.parent.mkdir(parents=True, exist_ok=True)
    private_key = ec.generate_private_key(ec.SECP256R1())
    path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return private_key


def _send_notification_to_all(payload: dict[str, object]) -> tuple[int, int]:
    _load_or_create_vapid_private_key()
    with connect() as db:
        rows = db.execute(
            "SELECT id, subscription_json FROM push_subscriptions WHERE disabled_at IS NULL"
        ).fetchall()
    sent = 0
    failed = 0
    for row in rows:
        subscription = decode_json(row["subscription_json"], {})
        try:
            webpush(
                subscription_info=subscription,
                data=json.dumps(payload, separators=(",", ":"), ensure_ascii=False),
                vapid_private_key=str(_vapid_private_key_path()),
                vapid_claims={"sub": os.environ.get("JOBFLOW_VAPID_SUBJECT", "mailto:jobflow@localhost")},
            )
            sent += 1
        except WebPushException as exc:
            failed += 1
            status_code = getattr(getattr(exc, "response", None), "status_code", None)
            disabled_at = utc_now() if status_code in {404, 410} else None
            with connect() as db:
                db.execute(
                    """
                    UPDATE push_subscriptions
                    SET last_error = ?, disabled_at = COALESCE(?, disabled_at), updated_at = ?
                    WHERE id = ?
                    """,
                    (str(exc)[:300], disabled_at, utc_now(), row["id"]),
                )
        except Exception as exc:
            failed += 1
            with connect() as db:
                db.execute(
                    "UPDATE push_subscriptions SET last_error = ?, updated_at = ? WHERE id = ?",
                    (str(exc)[:300], utc_now(), row["id"]),
                )
    return sent, failed


def _notify_once(
    key: str,
    event_kind: str,
    payload: dict[str, object],
    *,
    job_id: str | None = None,
) -> None:
    now = utc_now()
    with connect() as db:
        inserted = db.execute(
            """
            INSERT OR IGNORE INTO notification_dedupe(key, event_kind, job_id, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (key, event_kind, job_id, now),
        ).rowcount
    if inserted:
        _send_notification_to_all(payload)


def _notify_pack_ready(job_id: str, version: int, revision_state: str) -> None:
    with connect() as db:
        job = db.execute("SELECT title, company FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        return
    revised = version > 1 or revision_state == "regenerated"
    _notify_once(
        f"{'pack_revised' if revised else 'pack_ready'}:{job_id}:{version}",
        "pack_revised" if revised else "pack_ready",
        {
            "title": "Revised pack ready" if revised else "Application pack ready",
            "body": f"{job['company']} · {job['title']}",
            "url": f"/?job={job_id}",
            "tag": f"jobflow-pack-{job_id}-{version}",
        },
        job_id=job_id,
    )
    _notify_review_threshold(_review_status())


def _notify_review_threshold(status: ReviewStatusOut) -> None:
    if not status.paused_for_review:
        return
    with connect() as db:
        rows = db.execute(
            """
            SELECT j.id, p.version
            FROM jobs j
            JOIN application_packs p ON p.job_id = j.id
            WHERE p.status = 'ready'
              AND COALESCE(j.imported_state, '') != 'expired'
              AND NOT EXISTS (
                SELECT 1 FROM review_decisions rd
                WHERE rd.job_id = j.id AND rd.pack_version = p.version
              )
            ORDER BY j.updated_at DESC, j.id
            """
        ).fetchall()
    fingerprint = hashlib.sha256(
        "|".join(f"{row['id']}:{row['version']}" for row in rows).encode("utf-8")
    ).hexdigest()[:16]
    _notify_once(
        f"review_threshold:{status.threshold}:{fingerprint}",
        "review_threshold",
        {
            "title": "JobFlow discovery paused",
            "body": status.paused_reason or "Review ready packs before more discovery.",
            "url": "/",
            "tag": "jobflow-review-threshold",
        },
    )


def _send_daily_review_reminder() -> None:
    status = _review_status()
    if status.backlog_count <= 0:
        return
    local_day = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Vienna")).date().isoformat()
    _notify_once(
        f"daily_review_reminder:{local_day}",
        "daily_review_reminder",
        {
            "title": "JobFlow review reminder",
            "body": f"{status.backlog_count} ready pack{'s' if status.backlog_count != 1 else ''} waiting for a decision.",
            "url": "/",
            "tag": "jobflow-daily-review-reminder",
        },
    )


def _notify_application_task(job_id: str, state: str) -> None:
    with connect() as db:
        row = db.execute("SELECT title, company FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return
    titles = {
        "needs_input": "Application needs input",
        "submitted": "Application marked submitted",
        "failed": "Application task failed",
    }
    _notify_once(
        f"application_task:{state}:{job_id}",
        f"application_{state}",
        {
            "title": titles.get(state, "Application task updated"),
            "body": f"{row['company']} · {row['title']}",
            "url": f"/?job={job_id}",
            "tag": f"jobflow-application-{job_id}",
        },
        job_id=job_id,
    )


def _dispatch_revision_webhook(request_id: str) -> None:
    webhook_url = os.environ.get(REVISION_WEBHOOK_URL_ENV, "").strip()
    now = utc_now()
    if not webhook_url:
        with connect() as db:
            db.execute(
                "UPDATE revision_requests SET status = 'skipped', dispatched_at = ? WHERE id = ?",
                (now, request_id),
            )
        return
    with connect() as db:
        row = db.execute("SELECT * FROM revision_requests WHERE id = ?", (request_id,)).fetchone()
    if row is None:
        return
    payload = {
        "request_id": row["id"],
        "job_id": row["job_id"],
        "pack_version": row["pack_version"],
        "reasons": decode_json(row["reasons_json"], []),
        "note": row["note"] or "",
        "created_at": row["created_at"],
    }
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    secret = os.environ.get(REVISION_WEBHOOK_SECRET_ENV, "").encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if secret:
        headers["X-JobFlow-Signature"] = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
        webhook_timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        signed_payload = webhook_timestamp.encode("ascii") + b"." + body
        headers["X-Webhook-Timestamp"] = webhook_timestamp
        headers["X-Webhook-Signature-V2"] = hmac.new(
            secret,
            signed_payload,
            hashlib.sha256,
        ).hexdigest()
    try:
        request = UrlRequest(webhook_url, data=body, headers=headers, method="POST")
        with urlopen(request, timeout=10) as response:
            status = getattr(response, "status", 200)
            if status >= 400:
                raise URLError(f"HTTP {status}")
        with connect() as db:
            db.execute(
                "UPDATE revision_requests SET status = 'dispatched', error = NULL, dispatched_at = ? WHERE id = ?",
                (utc_now(), request_id),
            )
    except Exception as exc:
        with connect() as db:
            db.execute(
                "UPDATE revision_requests SET status = 'failed', error = ?, dispatched_at = ? WHERE id = ?",
                (str(exc)[:500], utc_now(), request_id),
            )


def _require_agent_auth(request: Request) -> None:
    if not _valid_agent_token(request.headers.get("Authorization")):
        raise HTTPException(status_code=401, detail="Agent token required")


def _auth_config() -> tuple[str, str] | None:
    username = os.environ.get(AUTH_USERNAME_ENV)
    password = os.environ.get(AUTH_PASSWORD_ENV)
    if bool(username) != bool(password):
        raise RuntimeError(f"{AUTH_USERNAME_ENV} and {AUTH_PASSWORD_ENV} must be set together")
    if not username and not password:
        return None
    return username, password


def _is_api_path(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def _valid_basic_auth(header: str | None, config: tuple[str, str]) -> bool:
    credentials = _decode_basic_auth(header)
    if credentials is None:
        return False
    username, password = credentials
    return _credentials_match(username, password, config)


def _valid_agent_token(header: str | None) -> bool:
    if not header or not header.startswith("Bearer "):
        return False
    token = header[7:].strip()
    if len(token) < 32:
        return False
    digest = hashlib.sha256(token.encode()).hexdigest()
    with connect() as db:
        row = db.execute(
            "SELECT id FROM agent_tokens WHERE token_hash = ? AND revoked_at IS NULL",
            (digest,),
        ).fetchone()
        if row is None:
            return False
        db.execute("UPDATE agent_tokens SET last_used_at = ? WHERE id = ?", (utc_now(), row["id"]))
    return True


def _credentials_match(username: str, password: str, config: tuple[str, str]) -> bool:
    expected_username, expected_password = config
    username_matches = secrets.compare_digest(username.encode("utf-8"), expected_username.encode("utf-8"))
    password_matches = secrets.compare_digest(password.encode("utf-8"), expected_password.encode("utf-8"))
    return username_matches and password_matches


def _decode_basic_auth(header: str | None) -> tuple[str, str] | None:
    if not header or not header.startswith("Basic "):
        return None
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    username, separator, password = decoded.partition(":")
    if not separator:
        return None
    return username, password


def _encode_session(username: str, expires_at: int, config: tuple[str, str]) -> str:
    payload = json.dumps({"exp": expires_at, "u": username}, separators=(",", ":"), sort_keys=True).encode("utf-8")
    body = _b64url_encode(payload)
    signature = _sign_session_body(body, config)
    return f"{body}.{signature}"


def _valid_session(request: Request, config: tuple[str, str]) -> int | None:
    token = request.cookies.get(AUTH_COOKIE_NAME)
    if not token:
        return None
    body, separator, signature = token.partition(".")
    if not separator or not body or not signature:
        return None
    expected_signature = _sign_session_body(body, config)
    if not hmac.compare_digest(signature, expected_signature):
        return None
    try:
        payload = json.loads(_b64url_decode(body).decode("utf-8"))
    except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if payload.get("u") != config[0]:
        return None
    expires_at = payload.get("exp")
    if not isinstance(expires_at, int) or expires_at <= int(time.time()):
        return None
    return expires_at


def _sign_session_body(body: str, config: tuple[str, str]) -> str:
    return _b64url_encode(hmac.new(_session_secret(config), body.encode("ascii"), hashlib.sha256).digest())


def _session_secret(config: tuple[str, str]) -> bytes:
    return f"{config[0]}\0{config[1]}".encode("utf-8")


def _b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64url_decode(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def _cookie_secure() -> bool:
    raw = os.environ.get(AUTH_COOKIE_SECURE_ENV, "false").strip().lower()
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"", "0", "false", "no", "off"}:
        return False
    raise RuntimeError(f"{AUTH_COOKIE_SECURE_ENV} must be true or false")


def _auth_unauthorized(detail: str = "Authentication required") -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=401)


def _mount_static_files() -> None:
    static_dir = os.environ.get(STATIC_DIR_ENV)
    if not static_dir:
        return
    path = Path(static_dir).expanduser().resolve()
    if path.is_dir():
        app.mount("/", StaticFiles(directory=path, html=True), name="frontend")


_mount_static_files()
