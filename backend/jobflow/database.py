from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = ROOT / "data" / "jobflow.sqlite3"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def database_path() -> Path:
    return Path(os.environ.get("JOBFLOW_DB", DEFAULT_DB_PATH)).expanduser().resolve()


def encode_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def decode_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


@contextmanager
def connect(path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    db_path = Path(path) if path is not None else database_path()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db(path: str | Path | None = None) -> None:
    with connect(path) as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                source_id TEXT,
                source_name TEXT,
                source_url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                raw_description TEXT,
                extracted_description TEXT,
                score INTEGER,
                verdict TEXT,
                confidence TEXT,
                status TEXT NOT NULL DEFAULT 'inbox'
                    CHECK (status IN ('inbox', 'good', 'maybe', 'bad')),
                summary TEXT,
                salary_display TEXT,
                salary_min_annual INTEGER,
                salary_max_annual INTEGER,
                salary_currency TEXT,
                work_mode TEXT,
                home_office_days INTEGER,
                language_environment TEXT,
                fit_evidence_json TEXT NOT NULL DEFAULT '[]',
                source_evidence_json TEXT NOT NULL DEFAULT '{}',
                missing_info_json TEXT NOT NULL DEFAULT '[]',
                hard_gate_reasons_json TEXT NOT NULL DEFAULT '[]',
                requirements_json TEXT NOT NULL DEFAULT '[]',
                responsibilities_json TEXT NOT NULL DEFAULT '[]',
                technologies_json TEXT NOT NULL DEFAULT '[]',
                imported_state TEXT,
                first_seen_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                reviewed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
                rating TEXT NOT NULL CHECK (rating IN ('good', 'maybe', 'bad')),
                reasons_json TEXT NOT NULL DEFAULT '[]',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS preferences (
                id TEXT PRIMARY KEY CHECK (id = 'default'),
                profile_summary TEXT NOT NULL DEFAULT '',
                target_locations_json TEXT NOT NULL DEFAULT '[]',
                work_modes_json TEXT NOT NULL DEFAULT '[]',
                min_home_office_days INTEGER,
                salary_currency TEXT NOT NULL DEFAULT 'EUR',
                salary_target_min INTEGER,
                salary_target_max INTEGER,
                acceptable_salary_min INTEGER,
                role_families_json TEXT NOT NULL DEFAULT '[]',
                priority_role_families_json TEXT NOT NULL DEFAULT '[]',
                priorities_json TEXT NOT NULL DEFAULT '[]',
                hard_rules_json TEXT NOT NULL DEFAULT '[]',
                discovery_queries_json TEXT NOT NULL DEFAULT '[]',
                discovery_limit_per_query INTEGER NOT NULL DEFAULT 5,
                language_preference TEXT,
                application_language TEXT,
                manual_submission_only INTEGER NOT NULL DEFAULT 1,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS activity (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS profile_documents (
                id TEXT PRIMARY KEY,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL UNIQUE,
                media_type TEXT NOT NULL,
                size INTEGER NOT NULL CHECK (size >= 0),
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS agent_tokens (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                last_used_at TEXT,
                revoked_at TEXT
            );

            CREATE TABLE IF NOT EXISTS discovery_config (
                id TEXT PRIMARY KEY CHECK (id = 'default'),
                schedule_enabled INTEGER NOT NULL DEFAULT 1,
                timezone TEXT NOT NULL DEFAULT 'Europe/Vienna',
                schedule_times_json TEXT NOT NULL DEFAULT '["07:00","13:00","19:00"]',
                review_threshold INTEGER NOT NULL DEFAULT 3,
                paused_for_review INTEGER NOT NULL DEFAULT 0,
                paused_reason TEXT,
                last_scheduled_slot TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS discovery_sources (
                id TEXT PRIMARY KEY,
                label TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL,
                detail TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS discovery_runs (
                id TEXT PRIMARY KEY,
                trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'scheduled')),
                status TEXT NOT NULL CHECK (status IN ('running', 'succeeded', 'failed')),
                started_at TEXT NOT NULL,
                finished_at TEXT,
                queries_json TEXT NOT NULL DEFAULT '[]',
                candidate_count INTEGER NOT NULL DEFAULT 0,
                unique_count INTEGER NOT NULL DEFAULT 0,
                jobs_added INTEGER NOT NULL DEFAULT 0,
                jobs_evaluated INTEGER NOT NULL DEFAULT 0,
                packs_prepared INTEGER NOT NULL DEFAULT 0,
                paused_for_review INTEGER NOT NULL DEFAULT 0,
                paused_reason TEXT,
                error TEXT
            );

            CREATE TABLE IF NOT EXISTS discovery_candidates (
                run_id TEXT NOT NULL REFERENCES discovery_runs(id) ON DELETE CASCADE,
                url TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'open_web',
                title TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                matched_queries_json TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (run_id, url)
            );

            CREATE INDEX IF NOT EXISTS idx_discovery_candidates_run
            ON discovery_candidates(run_id);

            CREATE TABLE IF NOT EXISTS agentmail_messages (
                message_id TEXT PRIMARY KEY,
                received_at TEXT,
                subject TEXT NOT NULL DEFAULT '',
                link_count INTEGER NOT NULL DEFAULT 0,
                processed_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS reactive_resume_config (
                id INTEGER PRIMARY KEY CHECK(id = 1),
                base_url TEXT NOT NULL,
                encrypted_api_key TEXT,
                configured_at TEXT,
                verified_at TEXT,
                last_error TEXT,
                reference_resume_id TEXT,
                reference_resume_name TEXT,
                reference_template TEXT,
                reference_updated_at TEXT,
                resumes_json TEXT NOT NULL DEFAULT '[]',
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS application_packs (
                job_id TEXT PRIMARY KEY REFERENCES jobs(id) ON DELETE CASCADE,
                status TEXT NOT NULL CHECK (status IN ('preparing', 'ready', 'failed')),
                version INTEGER NOT NULL DEFAULT 1,
                revision_state TEXT NOT NULL DEFAULT 'current'
                    CHECK (revision_state IN ('current', 'changes_requested', 'regenerated')),
                revision_reasons_json TEXT NOT NULL DEFAULT '[]',
                revision_note TEXT NOT NULL DEFAULT '',
                resume_id TEXT,
                resume_name TEXT,
                resume_pdf_pages INTEGER,
                letter_subject TEXT,
                letter_body TEXT,
                agent_model TEXT,
                agent_run_id TEXT,
                critic_notes TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS application_pack_versions (
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                version INTEGER NOT NULL,
                revision_state TEXT NOT NULL DEFAULT 'current',
                revision_reasons_json TEXT NOT NULL DEFAULT '[]',
                revision_note TEXT NOT NULL DEFAULT '',
                resume_id TEXT,
                resume_name TEXT,
                resume_pdf_pages INTEGER,
                letter_subject TEXT,
                letter_body TEXT,
                agent_model TEXT,
                agent_run_id TEXT,
                critic_notes TEXT,
                created_at TEXT NOT NULL,
                PRIMARY KEY (job_id, version)
            );

            CREATE TABLE IF NOT EXISTS review_decisions (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                pack_version INTEGER NOT NULL,
                decision TEXT NOT NULL CHECK (decision IN ('approve', 'decline', 'request_changes')),
                reasons_json TEXT NOT NULL DEFAULT '[]',
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (job_id, pack_version)
            );

            CREATE INDEX IF NOT EXISTS idx_review_decisions_job_version
            ON review_decisions(job_id, pack_version);

            CREATE TABLE IF NOT EXISTS application_tasks (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                pack_version INTEGER NOT NULL,
                state TEXT NOT NULL CHECK (
                    state IN (
                        'not_started',
                        'prepared',
                        'needs_input',
                        'awaiting_final_confirmation',
                        'submitted',
                        'failed'
                    )
                ),
                required_fields_json TEXT NOT NULL DEFAULT '[]',
                questions_json TEXT NOT NULL DEFAULT '[]',
                report TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (job_id, pack_version)
            );

            CREATE TABLE IF NOT EXISTS revision_requests (
                id TEXT PRIMARY KEY,
                job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
                pack_version INTEGER NOT NULL,
                reasons_json TEXT NOT NULL DEFAULT '[]',
                note TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL CHECK (status IN ('queued', 'dispatched', 'failed', 'skipped')),
                error TEXT,
                created_at TEXT NOT NULL,
                dispatched_at TEXT
            );

            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id TEXT PRIMARY KEY,
                endpoint TEXT NOT NULL UNIQUE,
                subscription_json TEXT NOT NULL,
                user_agent TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_error TEXT,
                disabled_at TEXT
            );

            CREATE TABLE IF NOT EXISTS notification_dedupe (
                key TEXT PRIMARY KEY,
                event_kind TEXT NOT NULL,
                job_id TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        _ensure_column(db, "jobs", "source_name", "TEXT")
        _ensure_column(db, "preferences", "profile_summary", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "jobs", "raw_description", "TEXT")
        _ensure_column(db, "jobs", "extracted_description", "TEXT")
        _ensure_column(db, "jobs", "salary_max_annual", "INTEGER")
        _ensure_column(db, "jobs", "salary_currency", "TEXT")
        _ensure_column(db, "preferences", "discovery_queries_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(db, "preferences", "discovery_limit_per_query", "INTEGER NOT NULL DEFAULT 5")
        _ensure_column(db, "preferences", "priority_role_families_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(db, "discovery_candidates", "source", "TEXT NOT NULL DEFAULT 'open_web'")
        _ensure_column(db, "discovery_runs", "jobs_added", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "discovery_runs", "jobs_evaluated", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "discovery_runs", "packs_prepared", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "discovery_runs", "paused_for_review", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "discovery_runs", "paused_reason", "TEXT")
        _ensure_column(db, "discovery_config", "review_threshold", "INTEGER NOT NULL DEFAULT 3")
        _ensure_column(db, "discovery_config", "paused_for_review", "INTEGER NOT NULL DEFAULT 0")
        _ensure_column(db, "discovery_config", "paused_reason", "TEXT")
        _ensure_column(db, "application_packs", "version", "INTEGER NOT NULL DEFAULT 1")
        _ensure_column(db, "application_packs", "revision_state", "TEXT NOT NULL DEFAULT 'current'")
        _ensure_column(db, "application_packs", "revision_reasons_json", "TEXT NOT NULL DEFAULT '[]'")
        _ensure_column(db, "application_packs", "revision_note", "TEXT NOT NULL DEFAULT ''")
        _ensure_column(db, "application_packs", "agent_model", "TEXT")
        _ensure_column(db, "application_packs", "agent_run_id", "TEXT")
        _ensure_column(db, "application_packs", "critic_notes", "TEXT")
        _ensure_column(db, "application_pack_versions", "agent_model", "TEXT")
        _ensure_column(db, "application_pack_versions", "agent_run_id", "TEXT")
        _ensure_column(db, "application_pack_versions", "critic_notes", "TEXT")
        now = utc_now()
        db.execute(
            """
            INSERT OR IGNORE INTO discovery_config (
                id, schedule_enabled, timezone, schedule_times_json, updated_at
            ) VALUES ('default', 1, 'Europe/Vienna', '["07:00","13:00","19:00"]', ?)
            """,
            (now,),
        )
        db.execute(
            """
            INSERT OR IGNORE INTO reactive_resume_config(
                id, base_url, resumes_json, updated_at
            ) VALUES (1, 'https://rxresu.me/api/openapi', '[]', ?)
            """,
            (now,),
        )
        source_defaults = [
            ("open_web", "Open web", 1, "available", "Public job results through the configured search provider."),
            ("company_careers", "Company career pages", 0, "available", "Prioritize direct employer career pages."),
            ("karriere_alerts", "karriere.at Job Alarm", 0, "setup_required", "Official alert links; inbox connection is not configured yet."),
            ("ams_manual", "AMS eJob-Room", 0, "manual", "Manual review and URL intake only."),
            ("devjobs", "DEVjobs.at", 0, "disabled", "Automated collection is disabled pending a source-policy review."),
        ]
        db.executemany(
            """
            INSERT OR IGNORE INTO discovery_sources (id, label, enabled, status, detail, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(*source, now) for source in source_defaults],
        )


def _ensure_column(db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def rows_to_list(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
