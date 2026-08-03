from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from jobflow.application_pipeline import analyze_karriere_job
from jobflow.karriere_camofox import KarriereJobDetail, parse_detail_snapshot, parse_search_snapshot
from jobflow.models import Preferences


SEARCH_SNAPSHOT = '''
  - listitem:
    - heading "Junior Software Entwickler:in" [level=2]:
      - link "Junior Software Entwickler:in":
        - /url: https://www.karriere.at/jobs/123456
    - link "Example GmbH":
      - /url: https://www.karriere.at/f/example
    - text: Wien
    - button "Auf Merkliste"
'''

DETAIL_SNAPSHOT = '''
- document:
  - heading "Junior Software Entwickler:in" [level=1]
  - link "Employer Page von Example GmbH"
  - paragraph: Dienstorte
  - definition:
    - paragraph: Wien
  - paragraph: Gehalt
  - definition:
    - paragraph: ab 4.200 € monatlich
  - paragraph: Arbeitsmodell
  - definition:
    - paragraph: Hybrid
  - heading "Deine erwünschten Qualifikationen" [level=3]
    - listitem: • Python und SQL
    - listitem: • 2 Jahre praktische Erfahrung
  - heading "Rolle und Aufgaben" [level=3]
    - paragraph: Interne Webanwendungen entwickeln.
  - heading "Kontakt" [level=3]
'''


def _detail(job_id: str = "123456") -> KarriereJobDetail:
    return KarriereJobDetail(
        url=f"https://www.karriere.at/jobs/{job_id}",
        source_id=job_id,
        title="Junior Software Entwickler:in",
        company="Example GmbH",
        location="Wien",
        description="Python SQL Hybrid",
        salary_display="ab 4.200 € monatlich",
        salary_min_annual=58_800,
        salary_max_annual=58_800,
        work_mode="Hybrid",
        requirements=["Python und SQL", "2 Jahre praktische Erfahrung"],
        responsibilities=["Interne Webanwendungen entwickeln."],
        technologies=["Python", "SQL"],
        matched_queries=["junior software developer Vienna"],
    )


def test_parses_karriere_search_and_detail() -> None:
    listings = parse_search_snapshot(SEARCH_SNAPSHOT)
    assert [(item.url, item.title, item.company) for item in listings] == [
        ("https://www.karriere.at/jobs/123456", "Junior Software Entwickler:in", "Example GmbH")
    ]
    detail = parse_detail_snapshot(DETAIL_SNAPSHOT, listings[0].url)
    assert detail.company == "Example GmbH"
    assert detail.salary_min_annual == 58_800
    assert detail.work_mode == "Hybrid"
    assert detail.requirements == ["Python und SQL", "2 Jahre praktische Erfahrung"]


def test_camofox_candidates_become_visible_jobs_and_declines_stay_suppressed(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    os.environ["JOBFLOW_DB"] = str(db_path)

    from jobflow.database import init_db
    from jobflow.main import app
    import jobflow.main as main

    init_db(db_path)
    client = TestClient(app)
    operations = client.get("/api/discovery/operations").json()
    configured = client.put(
        "/api/discovery/config",
        json={
            "schedule": operations["schedule"],
            "sources_enabled": {"open_web": False, "karriere_alerts": True},
        },
    )
    assert configured.status_code == 200

    details = [_detail("123456"), _detail("654321")]
    monkeypatch.setattr(main, "camofox_available", lambda: True)
    monkeypatch.setattr(main, "crawl_karriere", lambda *_args, **_kwargs: (3, details))
    matching_preferences = Preferences(
        target_locations=["Vienna"],
        work_modes=["Hybrid"],
        acceptable_salary_min=45_000,
        role_families=["software developer"],
        priority_role_families=["junior software developer"],
    )
    monkeypatch.setattr(
        main,
        "analyze_karriere_job",
        lambda detail, _preferences: analyze_karriere_job(detail, matching_preferences),
    )
    prepared: set[str] = set()

    def fake_prepare(job_id: str, *_args: Any) -> bool:
        if job_id in prepared:
            return False
        prepared.add(job_id)
        return True

    monkeypatch.setattr(main, "_prepare_application_pack", fake_prepare)

    first = client.post("/api/discovery/run")
    assert first.status_code == 200
    assert first.json()["jobs_added"] == 2
    assert first.json()["jobs_evaluated"] == 2
    assert first.json()["packs_prepared"] == 2
    jobs = client.get("/api/jobs").json()
    assert len(jobs) == 2
    assert all(job["score"] is not None for job in jobs)

    # Existing production data can contain a string instead of EvidenceItem objects.
    from jobflow.database import connect
    with connect() as db:
        db.execute(
            "UPDATE jobs SET fit_evidence_json = ? WHERE id = ?",
            ('{"role_fit":"Legacy evidence sentence"}', jobs[0]["id"]),
        )
    legacy_detail = client.get(f"/api/jobs/{jobs[0]['id']}")
    assert legacy_detail.status_code == 200
    assert legacy_detail.json()["fit_evidence"]["role_fit"][0]["text"] == "Legacy evidence sentence"

    declined_id = jobs[0]["id"]
    response = client.post(
        f"/api/jobs/{declined_id}/feedback",
        json={"rating": "bad", "reasons": ["Not for me"], "note": ""},
    )
    assert response.status_code == 200
    declined = client.get(f"/api/jobs/{declined_id}").json()
    assert declined["status"] == "bad"

    second = client.post("/api/discovery/run")
    assert second.status_code == 200
    assert second.json()["jobs_added"] == 0
    declined = client.get(f"/api/jobs/{declined_id}").json()
    assert declined["status"] == "bad"


def test_fit_analysis_scores_a_matching_vienna_role() -> None:
    analysis = analyze_karriere_job(
        _detail(),
        Preferences(
            target_locations=["Vienna"],
            work_modes=["Hybrid"],
            acceptable_salary_min=45_000,
            role_families=["software developer"],
            priority_role_families=["junior software developer"],
        ),
    )
    assert analysis.score >= 70
    assert analysis.verdict == "strong"
    assert analysis.salary_min_annual == 58_800
