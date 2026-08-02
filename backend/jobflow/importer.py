from __future__ import annotations

import argparse
import hashlib
import html
import json
import sqlite3
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

from .database import connect, encode_json, init_db, utc_now


TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "msclkid",
}


def import_old_database(old_db: Path, old_profile: Path, target_db: Path | None = None) -> dict[str, int]:
    init_db(target_db)
    imported = 0
    skipped = 0
    now = utc_now()
    with _readonly_connection(old_db) as old, connect(target_db) as new:
        rows = old.execute(
            """
            WITH ranked AS (
                SELECT
                    a.id AS source_id,
                    a.canonical_url,
                    a.state,
                    a.created_at,
                    a.updated_at,
                    n.title,
                    n.company,
                    n.location_text,
                    n.normalized_json,
                    s.total_score,
                    s.verdict,
                    s.confidence,
                    s.details_json,
                    s.scored_at,
                    ROW_NUMBER() OVER (
                        PARTITION BY a.id
                        ORDER BY COALESCE(s.scored_at, n.normalized_at, a.updated_at) DESC
                    ) AS row_number
                FROM applications a
                JOIN source_snapshots ss ON ss.application_id = a.id
                JOIN job_normalizations n ON n.snapshot_id = ss.id
                JOIN job_scores s ON s.normalization_id = n.id
            )
            SELECT * FROM ranked WHERE row_number = 1
            ORDER BY COALESCE(scored_at, updated_at) DESC
            """
        ).fetchall()
        for row in rows:
            try:
                job = _map_job(row, now)
            except (ValueError, TypeError, json.JSONDecodeError, sqlite3.Error):
                skipped += 1
                continue
            new.execute(
                """
                INSERT INTO jobs (
                    id, source_id, source_url, title, company, location, score, verdict,
                    confidence, status, summary, salary_display, salary_min_annual,
                    work_mode, home_office_days, language_environment, fit_evidence_json,
                    source_evidence_json, missing_info_json, hard_gate_reasons_json,
                    requirements_json, responsibilities_json, technologies_json,
                    imported_state, first_seen_at, updated_at
                )
                VALUES (
                    :id, :source_id, :source_url, :title, :company, :location, :score,
                    :verdict, :confidence, 'inbox', :summary, :salary_display,
                    :salary_min_annual, :work_mode, :home_office_days, :language_environment,
                    :fit_evidence_json, :source_evidence_json, :missing_info_json,
                    :hard_gate_reasons_json, :requirements_json, :responsibilities_json,
                    :technologies_json, :imported_state, :first_seen_at, :updated_at
                )
                ON CONFLICT(source_url) DO UPDATE SET
                    title = excluded.title,
                    company = excluded.company,
                    location = excluded.location,
                    score = excluded.score,
                    verdict = excluded.verdict,
                    confidence = excluded.confidence,
                    summary = excluded.summary,
                    salary_display = excluded.salary_display,
                    salary_min_annual = excluded.salary_min_annual,
                    work_mode = excluded.work_mode,
                    home_office_days = excluded.home_office_days,
                    language_environment = excluded.language_environment,
                    fit_evidence_json = excluded.fit_evidence_json,
                    source_evidence_json = excluded.source_evidence_json,
                    missing_info_json = excluded.missing_info_json,
                    hard_gate_reasons_json = excluded.hard_gate_reasons_json,
                    requirements_json = excluded.requirements_json,
                    responsibilities_json = excluded.responsibilities_json,
                    technologies_json = excluded.technologies_json,
                    imported_state = excluded.imported_state,
                    updated_at = excluded.updated_at
                """,
                job,
            )
            imported += 1
        if imported:
            new.execute(
                """
                INSERT INTO activity (id, kind, title, body, created_at)
                VALUES (?, 'import', 'Imported preserved jobs', ?, ?)
                """,
                (
                    _stable_id(f"activity:import:{now}"),
                    f"{imported} records copied read-only from the old job-search database.",
                    now,
                ),
            )
        _seed_preferences(new, old_profile, now)
    return {"imported": imported, "skipped": skipped}


def _map_job(row: sqlite3.Row, now: str) -> dict[str, Any]:
    normalized = json.loads(row["normalized_json"])
    details = json.loads(row["details_json"])
    source_url = canonicalize_url(row["canonical_url"])
    title = _clean_text(normalized.get("title") or row["title"])
    company = _clean_text(normalized.get("company") or row["company"])
    if not title or not company:
        raise ValueError("missing title or company")
    return {
        "id": _stable_id(source_url),
        "source_id": row["source_id"],
        "source_url": source_url,
        "title": title,
        "company": company,
        "location": _clean_text(normalized.get("location") or row["location_text"]),
        "score": row["total_score"],
        "verdict": row["verdict"],
        "confidence": row["confidence"],
        "summary": _clean_text(normalized.get("summary")),
        "salary_display": _clean_text(normalized.get("salary_display")),
        "salary_min_annual": normalized.get("salary_min_annual"),
        "work_mode": normalized.get("work_mode"),
        "home_office_days": normalized.get("home_office_days"),
        "language_environment": normalized.get("language_environment"),
        "fit_evidence_json": encode_json(details.get("evidence") or {}),
        "source_evidence_json": encode_json(normalized.get("evidence") or {}),
        "missing_info_json": encode_json(details.get("missing_info") or []),
        "hard_gate_reasons_json": encode_json(details.get("hard_gate_reasons") or []),
        "requirements_json": encode_json(normalized.get("requirements") or []),
        "responsibilities_json": encode_json(normalized.get("responsibilities") or []),
        "technologies_json": encode_json(normalized.get("technologies") or []),
        "imported_state": row["state"],
        "first_seen_at": row["created_at"] or now,
        "updated_at": row["scored_at"] or row["updated_at"] or now,
    }


def _seed_preferences(db: sqlite3.Connection, profile_path: Path, now: str) -> None:
    profile = yaml.safe_load(profile_path.read_text()) or {}
    target_locations = [
        *(profile.get("location", {}).get("cities") or []),
        *(profile.get("location", {}).get("countries") or []),
    ]
    roles = [
        *(profile.get("role_families", {}).get("primary") or []),
        *(profile.get("role_families", {}).get("adjacent") or []),
    ]
    hard_rules = []
    work_mode = profile.get("work_mode", {})
    compensation = profile.get("compensation", {})
    approval = profile.get("approval", {})
    if work_mode.get("reject_if_confirmed_below_minimum"):
        hard_rules.append("Reject confirmed home-office below minimum")
    if compensation.get("normally_reject_below"):
        hard_rules.append(f"Normally reject below {compensation['normally_reject_below']} {compensation.get('currency', 'EUR')}")
    if approval.get("submit_applications"):
        hard_rules.append("Applications require specific Toni approval")
    if approval.get("recruiter_contact"):
        hard_rules.append("Recruiter contact requires specific Toni approval")
    db.execute(
        """
        INSERT INTO preferences (
            id, target_locations_json, work_modes_json, min_home_office_days,
            salary_currency, salary_target_min, salary_target_max, acceptable_salary_min,
            role_families_json, priorities_json, hard_rules_json,
            language_preference, application_language, manual_submission_only, updated_at
        )
        VALUES ('default', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
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
            manual_submission_only = 1,
            updated_at = excluded.updated_at
        """,
        (
            encode_json(target_locations),
            encode_json(["hybrid", "remote"]),
            work_mode.get("minimum_home_office_days_per_week"),
            compensation.get("currency", "EUR"),
            compensation.get("target_min"),
            compensation.get("target_max"),
            compensation.get("acceptable_transition_min"),
            encode_json(roles),
            encode_json(profile.get("work_content", {}).get("must_prioritize") or []),
            encode_json(hard_rules),
            profile.get("language", {}).get("preferred_working_language"),
            profile.get("language", {}).get("default_application_language"),
            now,
        ),
    )


def canonicalize_url(raw_url: str) -> str:
    if not isinstance(raw_url, str) or not raw_url.strip():
        raise ValueError("URL must be non-empty")
    candidate = html.unescape(raw_url).strip()
    if "\\" in candidate or any(ord(ch) < 32 or ord(ch) == 127 for ch in candidate):
        raise ValueError("invalid URL")
    parsed = urlsplit(candidate)
    if parsed.scheme.casefold() != "https" or not parsed.hostname:
        raise ValueError("only absolute HTTPS URLs are accepted")
    hostname = parsed.hostname.encode("idna").decode("ascii").casefold()
    host = hostname if parsed.port in (None, 443) else f"{hostname}:{parsed.port}"
    path = parsed.path or "/"
    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not (key.casefold().startswith("utm_") or key.casefold() in TRACKING_QUERY_KEYS)
    ]
    query_pairs.sort()
    return urlunsplit(("https", host, path, urlencode(query_pairs, doseq=True), ""))


def _readonly_connection(database: Path) -> sqlite3.Connection:
    database_path = database.resolve()
    connection = sqlite3.connect(f"{database_path.as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def main() -> int:
    parser = argparse.ArgumentParser(description="Import preserved jobs from the old read-only SQLite database.")
    parser.add_argument("--old-db", type=Path, required=True, help="Path to the legacy jobs.sqlite3 file")
    parser.add_argument("--old-profile", type=Path, required=True, help="Path to the legacy search-profile.yaml file")
    parser.add_argument("--target-db", type=Path, default=None)
    args = parser.parse_args()
    result = import_old_database(args.old_db, args.old_profile, args.target_db)
    print(f"Imported {result['imported']} jobs; skipped {result['skipped']} malformed rows.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
