from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from .database import connect, decode_json, encode_json, init_db, utc_now
from .models import ActivityItem, FeedbackIn, FeedbackOut, JobDetail, JobListItem, Preferences



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
    filter: Literal["inbox", "strong", "maybe", "low", "reviewed", "all"] = "inbox",
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
                language_preference, application_language, manual_submission_only, updated_at
            )
            VALUES ('default', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
        fit_evidence=decode_json(row["fit_evidence_json"], {}),
        source_evidence=decode_json(row["source_evidence_json"], {}),
        hard_gate_reasons=decode_json(row["hard_gate_reasons_json"], []),
        requirements=decode_json(row["requirements_json"], []),
        responsibilities=decode_json(row["responsibilities_json"], []),
        technologies=decode_json(row["technologies_json"], []),
        salary_min_annual=row["salary_min_annual"],
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
        language_preference=row["language_preference"],
        application_language=row["application_language"],
        manual_submission_only=bool(row["manual_submission_only"]),
        updated_at=row["updated_at"],
    )
