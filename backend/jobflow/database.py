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
                source_url TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                score INTEGER,
                verdict TEXT,
                confidence TEXT,
                status TEXT NOT NULL DEFAULT 'inbox'
                    CHECK (status IN ('inbox', 'good', 'maybe', 'bad')),
                summary TEXT,
                salary_display TEXT,
                salary_min_annual INTEGER,
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
                target_locations_json TEXT NOT NULL DEFAULT '[]',
                work_modes_json TEXT NOT NULL DEFAULT '[]',
                min_home_office_days INTEGER,
                salary_currency TEXT NOT NULL DEFAULT 'EUR',
                salary_target_min INTEGER,
                salary_target_max INTEGER,
                acceptable_salary_min INTEGER,
                role_families_json TEXT NOT NULL DEFAULT '[]',
                priorities_json TEXT NOT NULL DEFAULT '[]',
                hard_rules_json TEXT NOT NULL DEFAULT '[]',
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
            """
        )


def rows_to_list(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]
