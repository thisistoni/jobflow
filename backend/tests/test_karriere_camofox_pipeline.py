from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from jobflow.application_pipeline import analyze_karriere_job
from jobflow.karriere_camofox import (
    KarriereJobDetail,
    KarriereListing,
    _enrich_detail_from_job_posting,
    _fair_listing_order,
    _parse_job_posting_html,
    _search_url,
    parse_detail_snapshot,
    parse_search_snapshot,
)
from jobflow.models import JobIngestIn, Preferences


SEARCH_SNAPSHOT = '''
  - listitem:
    - heading "Junior Software Entwickler:in" [level=2]:
      - link "Junior Software Entwickler:in":
        - /url: https://www.karriere.at/jobs/123456
    - link "Example GmbH":
      - /url: https://www.karriere.at/f/example
    - text: Wien
    - button "Auf Merkliste"
  - listitem:
    - heading "Web Developer:in" [level=2]:
      - link "Web Developer:in":
        - /url: https://www.karriere.at/jobs/654321
    - link "Second GmbH":
      - /url: https://www.karriere.at/f/second
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

SHELL_DETAIL_SNAPSHOT = '''
- banner:
  - link "Logo karriere.at"
- img "PMC International GmbH"
- heading "Junior Software Developer (all genders)" [level=1]
- button "Drucken"
- link "Jetzt bewerben"
- heading "Weitere Jobs in Wien" [level=3]
'''


def _detail(job_id: str = "123456") -> KarriereJobDetail:
    return KarriereJobDetail(
        url=f"https://www.karriere.at/jobs/{job_id}",
        source_id=job_id,
        title="Junior Software Entwickler:in",
        company="Example GmbH",
        location="Wien",
        description=(
            "Über den Job\n"
            "Wir entwickeln interne Webanwendungen für operative Teams und suchen Unterstützung "
            "bei Python, SQL, Schnittstellen und strukturierten Automatisierungen. "
            "Die Rolle verbindet Softwareentwicklung, technische Analyse und laufende Verbesserung."
        ),
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
        ("https://www.karriere.at/jobs/123456", "Junior Software Entwickler:in", "Example GmbH"),
        ("https://www.karriere.at/jobs/654321", "Web Developer:in", "Second GmbH"),
    ]
    detail = parse_detail_snapshot(DETAIL_SNAPSHOT, listings[0].url)
    assert detail.company == "Example GmbH"
    assert detail.salary_min_annual == 58_800
    assert detail.work_mode == "Hybrid"
    assert detail.requirements == ["Python und SQL", "2 Jahre praktische Erfahrung"]

    shell = parse_detail_snapshot(SHELL_DETAIL_SNAPSHOT, "https://www.karriere.at/jobs/7847111")
    assert shell.title == "Junior Software Developer (all genders)"
    assert shell.company == "PMC International GmbH"
    assert shell.location is None
    assert shell.requirements == []
    assert "Weitere Jobs" not in shell.description


def test_jobposting_structured_data_supplies_source_truth() -> None:
    shell = parse_detail_snapshot(SHELL_DETAIL_SNAPSHOT, "https://www.karriere.at/jobs/7847111")
    posting = {
        "@type": "JobPosting",
        "title": "Junior Software Developer (all genders)",
        "hiringOrganization": {"name": "WITTMANN Gruppe"},
        "jobLocation": [
            {"address": {"addressLocality": "Kottingbrunn", "addressRegion": "Niederösterreich"}}
        ],
        "baseSalary": {
            "currency": "EUR",
            "value": {"unitText": "MONTH", "value": 3396.21},
        },
        "description": (
            "<h4>Aufgaben</h4><ul>"
            "<li>Entwicklung von Softwarelösungen für Spritzgießmaschinen</li>"
            "<li>Analyse und Implementierung im Team</li></ul>"
            "<h4>Anforderungsprofil</h4><ul>"
            "<li>Gute Programmierkenntnisse in C#</li>"
            "<li>Erfahrung mit IEC 61131-3</li></ul>"
            "<p>Die Rolle verbindet Maschinenbau und Softwareentwicklung. Teamtage finden vor Ort statt.</p>"
        ),
    }
    page = f'<script type="application/ld+json">{json.dumps({"@graph": [{**posting, "@type": ["Thing", "JobPosting"]}]})}</script>'
    _enrich_detail_from_job_posting(shell, _parse_job_posting_html(page))

    assert shell.company == "WITTMANN Gruppe"
    assert shell.location == "Kottingbrunn"
    assert shell.salary_min_annual == 47_547
    assert shell.home_office_days is None
    assert shell.requirements == ["Gute Programmierkenntnisse in C#", "Erfahrung mit IEC 61131-3"]
    assert shell.responsibilities == [
        "Entwicklung von Softwarelösungen für Spritzgießmaschinen",
        "Analyse und Implementierung im Team",
    ]
    assert "Maschinenbau und Softwareentwicklung" in shell.description

    rejected = analyze_karriere_job(
        shell,
        Preferences(
            target_locations=["Wien", "AT"],
            salary_target_min=45_000,
            acceptable_salary_min=47_500,
            role_families=["software developer"],
        ),
    )
    assert any("Location does not clearly match" in reason for reason in rejected.hard_gate_reasons)
    assert not any("salary" in reason.casefold() for reason in rejected.hard_gate_reasons)


def test_english_sections_and_three_year_stretch_are_reviewable() -> None:
    detail = _detail("10027070")
    detail.requirements = []
    detail.responsibilities = []
    posting = {
        "@type": "JobPosting",
        "description": (
            "<h3>Your responsibilities</h3><ul><li>Build Python and React products</li></ul>"
            "<h3>Your skills that inspire us</h3><ul>"
            "<li>A minimum of 3 years of experience as a Fullstack Developer</li>"
            "<li>Good English; German is a plus</li></ul>"
            "<h3>Profil</h3><ul><li>Structured and collaborative working style</li></ul>"
        ),
    }
    _enrich_detail_from_job_posting(detail, posting)
    assert detail.responsibilities == ["Build Python and React products"]
    assert len(detail.requirements) == 3

    analysis = analyze_karriere_job(
        detail,
        Preferences(
            target_locations=["Wien"],
            work_modes=["hybrid"],
            salary_target_min=45_000,
            role_families=["Fullstack Developer"],
            language_preference="de",
        ),
    )
    assert not any("3 years" in reason for reason in analysis.hard_gate_reasons)
    assert analysis.summary and "stretch application" in analysis.summary

    detail.requirements[0] = "A minimum of 5 years of experience as a Fullstack Developer"
    senior_analysis = analyze_karriere_job(detail, Preferences(target_locations=["Wien"]))
    assert any("5 years" in reason for reason in senior_analysis.hard_gate_reasons)


def test_unknown_work_policy_and_near_target_salary_are_warnings_not_rejections() -> None:
    detail = _detail("7836773")
    detail.salary_min_annual = 44_800
    detail.salary_max_annual = 44_800
    detail.salary_display = "EUR 3,200 gross/month · 44,800 gross/year"
    detail.work_mode = None
    detail.home_office_days = None
    analysis = analyze_karriere_job(
        detail,
        Preferences(
            target_locations=["Wien"],
            work_modes=["hybrid", "remote"],
            min_home_office_days=2,
            salary_target_min=45_000,
            role_families=["Junior software developer"],
        ),
    )
    assert not analysis.hard_gate_reasons
    assert "Work model" in analysis.missing_info
    assert "Exact home-office days" in analysis.missing_info

    detail.salary_min_annual = 35_000
    low_salary = analyze_karriere_job(detail, Preferences(target_locations=["Wien"], salary_target_min=45_000))
    assert any("materially below" in reason for reason in low_salary.hard_gate_reasons)


def test_karriere_search_uses_location_slug_and_fair_query_sampling() -> None:
    assert _search_url("Junior software developer jobs Wien") == (
        "https://www.karriere.at/jobs/junior-software-developer/wien"
    )
    listings = {
        str(index): KarriereListing(url=str(index), title=str(index), company="Example")
        for index in range(1, 7)
    }
    ordered = _fair_listing_order(
        ["query-a", "query-b", "query-c"],
        {
            "query-a": ["1", "2"],
            "query-b": ["3", "4"],
            "query-c": ["5", "6"],
        },
        listings,
    )
    assert [item.url for item in ordered] == ["1", "3", "5", "2", "4", "6"]


def test_crawl_skips_one_expired_detail_instead_of_aborting(monkeypatch: Any) -> None:
    import jobflow.karriere_camofox as karriere

    class FakeClient:
        def __init__(self) -> None:
            self.current = ""

        def health(self) -> bool:
            return True

        def create_tab(self, url: str) -> str:
            self.current = url
            return "tab"

        def navigate(self, _tab_id: str, url: str) -> None:
            self.current = url

        def snapshot(self, _tab_id: str) -> str:
            if "keywords=" in self.current:
                return SEARCH_SNAPSHOT
            if self.current.endswith("123456"):
                return '- heading "Expired" [level=1]'
            return DETAIL_SNAPSHOT.replace("Junior Software Entwickler:in", "Web Developer:in").replace("Example GmbH", "Second GmbH")

        def close_tab(self, _tab_id: str) -> None:
            return None

    monkeypatch.setattr(karriere, "CamofoxClient", FakeClient)
    monkeypatch.setattr(karriere, "_fetch_job_posting", lambda _url: (_ for _ in ()).throw(karriere.CamofoxProviderError("offline")))
    raw, details = karriere.crawl_karriere(["software Wien"], limit_per_query=2, max_details=2)
    assert raw == 2
    assert [item.source_id for item in details] == ["654321"]


def test_camofox_candidates_become_visible_jobs_and_declines_stay_suppressed(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    os.environ["JOBFLOW_DB"] = str(db_path)

    from jobflow.database import init_db, utc_now
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

    def fake_prepare(job_id: str, *_args: Any, **_kwargs: Any) -> bool:
        if job_id in prepared:
            return False
        prepared.add(job_id)
        main._store_application_pack(
            job_id,
            status="ready",
            resume_id=f"resume-{job_id}",
            resume_name="Prepared pack",
            resume_pdf_pages=1,
            letter_subject="Bewerbung",
            letter_body="Letter",
            now=utc_now(),
        )
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
    remaining = jobs[1]
    remaining_detail = next(detail for detail in details if detail.url == remaining["source_url"])
    remaining_detail.salary_min_annual = 35_000
    remaining_detail.salary_max_annual = 35_000
    remaining_detail.salary_display = "ab 35.000 € jährlich"
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
    invalidated = client.get(f"/api/jobs/{remaining['id']}").json()
    assert invalidated["application_pack"]["status"] == "failed"
    assert invalidated["application_pack"]["versions"][0]["version"] == 1


def test_fit_analysis_scores_a_matching_vienna_role() -> None:
    detail = _detail()
    detail.description += " Deutsch und Englisch werden im Team verwendet."
    analysis = analyze_karriere_job(
        detail,
        Preferences(
            target_locations=["Vienna"],
            work_modes=["Hybrid"],
            acceptable_salary_min=45_000,
            role_families=["software developer"],
            priority_role_families=["junior software developer"],
            language_preference="de",
        ),
    )
    assert analysis.score >= 70
    assert analysis.verdict == "strong"
    assert analysis.salary_min_annual == 58_800
    assert not any("Language environment" in reason for reason in analysis.hard_gate_reasons)


def test_work_mode_variants_and_home_office_days_are_preserved() -> None:
    for mode, wanted in (("Remote", ["remote"]), ("On-site", ["onsite"])):
        detail = _detail()
        detail.work_mode = mode
        detail.home_office_days = 3 if mode == "Remote" else 0
        analysis = analyze_karriere_job(
            detail,
            Preferences(
                target_locations=["Wien"],
                work_modes=wanted,
                salary_target_min=45_000,
                role_families=["software developer"],
            ),
        )
        assert not any("Work mode does not match" in reason for reason in analysis.hard_gate_reasons)
        assert analysis.home_office_days == detail.home_office_days


def test_incomplete_and_unversioned_historical_jobs_are_backfilled_from_canonical_source(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    db_path = tmp_path / "backfill.sqlite3"
    os.environ["JOBFLOW_DB"] = str(db_path)
    from jobflow.database import connect, init_db, utc_now
    import jobflow.main as main

    init_db(db_path)
    main.ingest_job(
        JobIngestIn(
            source_id="987654",
            source_name="karriere.at",
            source_url="https://www.karriere.at/jobs/987654",
            title="Junior Developer",
            company="Example GmbH",
            location="Wien",
            raw_description="Incomplete shell",
            extracted_description="Incomplete shell",
        )
    )
    legacy = main.ingest_job(
        JobIngestIn(
            source_id="111222",
            source_name="karriere.at",
            source_url="https://www.karriere.at/jobs/111222",
            title="Legacy Ready Developer",
            company="Example GmbH",
            location="Wien",
            raw_description="Complete verified source description. " * 8,
            extracted_description="Complete verified source description. " * 8,
        )
    )
    with connect() as db:
        db.execute(
            "UPDATE jobs SET requirements_json = ?, responsibilities_json = ? WHERE id = ?",
            ('["Python"]', '["Build internal tools"]', legacy.id),
        )
    main._store_application_pack(
        legacy.id,
        status="ready",
        resume_id="legacy-resume",
        resume_name="Legacy pack",
        resume_pdf_pages=1,
        letter_subject="Bewerbung",
        letter_body="Letter",
        now=utc_now(),
    )

    def fake_refresh(detail: KarriereJobDetail) -> KarriereJobDetail:
        detail.description = "Complete verified source description. " * 8
        detail.requirements = ["Python"]
        detail.responsibilities = ["Build internal tools"]
        return detail

    monkeypatch.setattr(main, "refresh_karriere_detail", fake_refresh)
    details: list[KarriereJobDetail] = []
    main._append_untrusted_karriere_details(details)
    assert {detail.source_id for detail in details} == {"987654", "111222"}
    assert all(detail.requirements == ["Python"] for detail in details)
