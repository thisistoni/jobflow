from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .database import connect, decode_json, encode_json, init_db, utc_now
from .firecrawl import FirecrawlConfigError, FirecrawlProviderError, scrape_url, search_web
from .importer import _stable_id, canonicalize_url
from .models import (
    ActivityItem,
    DiscoveryRunOut,
    DiscoveryRunResult,
    DiscoveryScrapeIn,
    DiscoveryScrapeResult,
    DiscoverySearchIn,
    DiscoverySearchResult,
    FeedbackIn,
    FeedbackOut,
    JobAnalysisIn,
    JobDetail,
    JobIngestIn,
    JobListItem,
    Preferences,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="JobFlow", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/jobs", response_model=list[JobListItem])
def list_jobs(
    filter: Literal["inbox", "strong", "maybe", "low", "reviewed", "unanalyzed", "all"] = "inbox",
    limit: int = Query(50, ge=1, le=200),
) -> list[JobListItem]:
    clauses: list[str] = []
    params: list[Any] = []
    if filter == "inbox":
        clauses.append("j.status = 'inbox'")
    elif filter == "strong":
        clauses.append("j.status = 'inbox' AND (j.verdict = 'strong' OR j.score >= 70)")
    elif filter == "maybe":
        clauses.append("j.status = 'inbox' AND (j.verdict = 'maybe' OR (j.score BETWEEN 55 AND 69))")
    elif filter == "low":
        clauses.append("j.status = 'inbox' AND (j.verdict = 'reject' OR j.score < 55)")
    elif filter == "reviewed":
        clauses.append("j.status != 'inbox'")
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
                id, source_name, source_url, title, company, location,
                raw_description, extracted_description, status, fit_evidence_json,
                source_evidence_json, missing_info_json, hard_gate_reasons_json,
                requirements_json, responsibilities_json, technologies_json,
                first_seen_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'inbox', ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
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
    now = utc_now()
    with connect() as db:
        job = db.execute("SELECT title, company FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        existing = db.execute("SELECT id, created_at FROM feedback WHERE job_id = ?", (job_id,)).fetchone()
        feedback_id = existing["id"] if existing else str(uuid.uuid4())
        created_at = existing["created_at"] if existing else now
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
            (
                feedback_id,
                job_id,
                payload.rating,
                encode_json(payload.reasons),
                payload.note.strip(),
                created_at,
                now,
            ),
        )
        db.execute(
            "UPDATE jobs SET status = ?, reviewed_at = ?, updated_at = ? WHERE id = ?",
            (payload.rating, now, now, job_id),
        )
        reason_text = ", ".join(payload.reasons) if payload.reasons else "No quick reason"
        db.execute(
            """
            INSERT INTO activity (id, kind, title, body, job_id, created_at)
            VALUES (?, 'feedback', ?, ?, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                f"Marked {job['company']} as {payload.rating}",
                f"{job['title']} · {reason_text}",
                job_id,
                now,
            ),
        )
    return FeedbackOut(rating=payload.rating, reasons=payload.reasons, note=payload.note.strip(), updated_at=now)


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
                id, target_locations_json, work_modes_json, min_home_office_days,
                salary_currency, salary_target_min, salary_target_max, acceptable_salary_min,
                role_families_json, priorities_json, hard_rules_json,
                discovery_queries_json, discovery_limit_per_query,
                language_preference, application_language, manual_submission_only, updated_at
            )
            VALUES ('default', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                target_locations_json = excluded.target_locations_json,
                work_modes_json = excluded.work_modes_json,
                min_home_office_days = excluded.min_home_office_days,
                salary_currency = excluded.salary_currency,
                salary_target_min = excluded.salary_target_min,
                salary_target_max = excluded.salary_target_max,
                acceptable_salary_min = excluded.acceptable_salary_min,
                role_families_json = excluded.role_families_json,
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
                encode_json(payload.target_locations),
                encode_json(payload.work_modes),
                payload.min_home_office_days,
                payload.salary_currency,
                payload.salary_target_min,
                payload.salary_target_max,
                payload.acceptable_salary_min,
                encode_json(payload.role_families),
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
    result = payload.model_copy(update={"updated_at": now})
    return result


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


@app.post("/api/discovery/run", response_model=DiscoveryRunOut)
def discovery_run() -> DiscoveryRunOut:
    preferences = get_preferences()
    queries = _clean_list(preferences.discovery_queries)
    if not queries:
        raise HTTPException(status_code=400, detail="No discovery queries are configured")

    candidates: dict[str, DiscoveryRunResult] = {}
    try:
        for query in queries:
            for item in search_web(query, preferences.discovery_limit_per_query):
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
                        matched_queries=[query],
                    )
                elif query not in candidate.matched_queries:
                    candidate.matched_queries.append(query)
    except (FirecrawlConfigError, FirecrawlProviderError) as exc:
        raise _firecrawl_http_exception(exc) from exc

    return DiscoveryRunOut(
        queries=queries,
        limit_per_query=preferences.discovery_limit_per_query,
        results=list(candidates.values()),
    )


@app.get("/api/activity", response_model=list[ActivityItem])
def activity(limit: int = Query(50, ge=1, le=200)) -> list[ActivityItem]:
    with connect() as db:
        rows = db.execute(
            "SELECT * FROM activity ORDER BY created_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [ActivityItem(**dict(row)) for row in rows]


def _feedback_from_row(row: Any) -> FeedbackOut | None:
    if row["rating"] is None:
        return None
    return FeedbackOut(
        rating=row["rating"],
        reasons=decode_json(row["reasons_json"], []),
        note=row["note"] or "",
        updated_at=row["feedback_updated_at"],
    )


def _job_list_item(row: Any) -> JobListItem:
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
        source_url=row["source_url"],
        feedback=_feedback_from_row(row),
    )


def _job_detail(row: Any) -> JobDetail:
    base = _job_list_item(row).model_dump()
    return JobDetail(
        **base,
        source_name=row["source_name"],
        raw_description=row["raw_description"],
        extracted_description=row["extracted_description"],
        fit_evidence=decode_json(row["fit_evidence_json"], {}),
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
        first_seen_at=row["first_seen_at"],
        updated_at=row["updated_at"],
        reviewed_at=row["reviewed_at"],
    )


def _preferences_from_row(row: Any) -> Preferences:
    return Preferences(
        target_locations=decode_json(row["target_locations_json"], []),
        work_modes=decode_json(row["work_modes_json"], []),
        min_home_office_days=row["min_home_office_days"],
        salary_currency=row["salary_currency"],
        salary_target_min=row["salary_target_min"],
        salary_target_max=row["salary_target_max"],
        acceptable_salary_min=row["acceptable_salary_min"],
        role_families=decode_json(row["role_families_json"], []),
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
