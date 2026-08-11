from __future__ import annotations

from jobflow.application_pipeline import (
    analyze_karriere_job,
    application_draft_quality_issues,
    build_application_draft,
)
from jobflow.karriere_camofox import KarriereJobDetail
from jobflow.models import Preferences


def detail(title: str, company: str, requirement: str, responsibility: str) -> KarriereJobDetail:
    return KarriereJobDetail(
        url="https://www.karriere.at/jobs/123456",
        source_id="123456",
        title=title,
        company=company,
        location="Wien",
        description=(f"{requirement}. {responsibility}. " * 12),
        salary_display="EUR 55,000 gross/year",
        salary_min_annual=55_000,
        salary_max_annual=None,
        work_mode="Hybrid",
        requirements=[requirement],
        responsibilities=[responsibility],
        technologies=["Python"],
        home_office_days=None,
    )


def draft_for(job: KarriereJobDetail):
    analysis = analyze_karriere_job(job, Preferences(target_locations=["Wien"]))
    return build_application_draft(job, analysis)


def test_finance_draft_uses_real_finance_automation_evidence_without_copying_source() -> None:
    job = detail(
        "Finance AI & Process Automation Engineer (f/m/d)",
        "Greentube GmbH",
        "Strong understanding of AI tools and applications including LLMs prompt-based workflows and AI agents",
        "Design develop and maintain AI-powered and data-driven solutions for Finance Accounting and Controlling processes",
    )
    draft = draft_for(job)

    assert application_draft_quality_issues(job, draft) == []
    assert "UiPath-Automatisierungen" in draft.body
    assert "für den Finanzbereich" in draft.body
    assert "spürbare Entlastung" in draft.body
    assert "design develop and maintain" not in draft.body.casefold()
    assert "Die Ausschreibung nennt" not in draft.body


def test_role_title_controls_the_angle_instead_of_employer_domain_keywords() -> None:
    job = detail(
        "Test Automation Engineer (m/w/d)",
        "Qnit Austria GmbH",
        "Experience testing Finance and Accounting applications in an agile team",
        "Build reliable automated regression tests for financial software",
    )
    draft = draft_for(job)

    assert application_draft_quality_issues(job, draft) == []
    assert "Testautomatisierung" in draft.body
    assert "Finanzbereich" not in draft.body


def test_company_source_metadata_is_not_required_in_letter_prose() -> None:
    job = detail(
        "Artificial Intelligence Specialist",
        "Manpower Österreich (Kunde nicht genannt)",
        "Practical experience with artificial intelligence",
        "Build useful internal automation",
    )
    draft = draft_for(job)
    draft.body = draft.body.replace(
        "Manpower Österreich (Kunde nicht genannt)",
        "Manpower Österreich",
    )

    assert application_draft_quality_issues(job, draft) == []

    draft.body = draft.body.replace("Manpower Österreich", "der Personalberatung")
    assert "Company is missing from the letter" in application_draft_quality_issues(job, draft)


def test_application_draft_rejects_ai_terminology_inventory() -> None:
    job = detail(
        "Artificial Intelligence Specialist",
        "Manpower Österreich",
        "Practical experience with artificial intelligence",
        "Build useful internal automation",
    )
    draft = draft_for(job)
    draft.body += "\n\nIch nutze LLMs, generative AI, Agenten und Tool Calling."

    assert (
        "Application letter inventories AI terminology instead of making one recruiter argument"
        in application_draft_quality_issues(job, draft)
    )


def test_materially_different_roles_do_not_receive_the_same_application() -> None:
    finance = draft_for(detail(
        "Finance AI & Process Automation Engineer (f/m/d)",
        "Greentube GmbH",
        "Practical finance automation experience",
        "Automate recurring Finance workflows",
    ))
    quality = draft_for(detail(
        "Software Tester / QA Automation Engineer",
        "Annny GmbH",
        "Experience with automated testing",
        "Create reliable regression tests",
    ))
    web = draft_for(detail(
        "Junior Java Entwickler (w/m/x)",
        "BEKO GmbH",
        "Interest in Java application development",
        "Develop useful web applications",
    ))

    assert len({finance.body, quality.body, web.body}) == 3
    assert len({finance.resume_summary_html, quality.resume_summary_html, web.resume_summary_html}) == 3
    assert all(application_draft_quality_issues(job, draft) == [] for job, draft in (
        (detail("Finance AI & Process Automation Engineer (f/m/d)", "Greentube GmbH", "Practical finance automation experience", "Automate recurring Finance workflows"), finance),
        (detail("Software Tester / QA Automation Engineer", "Annny GmbH", "Experience with automated testing", "Create reliable regression tests"), quality),
        (detail("Junior Java Entwickler (w/m/x)", "BEKO GmbH", "Interest in Java application development", "Develop useful web applications"), web),
    ))
