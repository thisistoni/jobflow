from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError


def test_dashboard_pulse_zero_fills_days_and_counts_vienna_dates(tmp_path: Path) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    os.environ["JOBFLOW_DB"] = str(db_path)

    from jobflow.database import connect, init_db
    from jobflow.main import app

    init_db(db_path)
    vienna = ZoneInfo("Europe/Vienna")
    local_now = datetime.now(timezone.utc).astimezone(vienna)
    yesterday = local_now - timedelta(days=1)

    with connect(db_path) as db:
        for index, seen in enumerate((local_now, local_now, yesterday)):
            db.execute(
                """
                INSERT INTO jobs (id, source_url, title, company, first_seen_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    str(uuid.uuid4()),
                    f"https://example.com/jobs/{index}",
                    f"Role {index}",
                    "Example",
                    seen.astimezone(timezone.utc).isoformat(),
                    seen.astimezone(timezone.utc).isoformat(),
                ),
            )

    response = TestClient(app).get("/api/dashboard/pulse?days=7")
    assert response.status_code == 200
    payload = response.json()
    assert len(payload["days"]) == 7
    assert payload["days"][-1] == {"date": local_now.date().isoformat(), "count": 2}
    assert payload["days"][-2] == {"date": yesterday.date().isoformat(), "count": 1}
    assert payload["today_count"] == 2


def test_preferences_reject_disabling_application_approval() -> None:
    from jobflow.models import Preferences

    with pytest.raises(ValidationError, match="requires explicit approval"):
        Preferences(manual_submission_only=False)
