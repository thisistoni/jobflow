from __future__ import annotations

import html
import re
from dataclasses import dataclass

from .karriere_camofox import KarriereJobDetail
from .models import EvidenceItem, JobAnalysisIn, Preferences


@dataclass(slots=True)
class ApplicationDraft:
    subject: str
    body: str
    resume_headline: str
    resume_summary_html: str


def analyze_karriere_job(job: KarriereJobDetail, preferences: Preferences) -> JobAnalysisIn:
    searchable = " ".join([job.title, job.description, *job.requirements, *job.responsibilities])
    folded = searchable.casefold()
    title_folded = job.title.casefold()
    score = 42
    evidence: dict[str, list[EvidenceItem]] = {}
    hard_gates: list[str] = []
    missing: list[str] = []

    priority_match = _role_match(preferences.priority_role_families, job.title)
    broad_match = _role_match(preferences.role_families, job.title)
    if priority_match:
        score += 23
        evidence.setdefault("role_fit", []).append(
            EvidenceItem(origin="job title", text=job.title, profile_fact_ref=f"priority role: {priority_match}")
        )
    elif broad_match:
        score += 14
        evidence.setdefault("role_fit", []).append(
            EvidenceItem(origin="job title", text=job.title, profile_fact_ref=f"target role: {broad_match}")
        )
    else:
        score -= 8

    senior_signal = next((term for term in ("senior", "lead", "leiter", "manager", "principal") if term in title_folded), None)
    if senior_signal:
        score -= 24
        hard_gates.append(f"Title contains a seniority signal: {senior_signal}")
        evidence.setdefault("seniority", []).append(EvidenceItem(origin="job title", text=job.title))

    years = _required_years(job.requirements)
    if years is not None:
        if years >= 5:
            score -= 22
            hard_gates.append(f"The posting asks for at least {years} years of experience.")
        elif years >= 3:
            score -= 12
            hard_gates.append(f"The posting asks for at least {years} years of experience.")
        evidence.setdefault("seniority", []).append(
            EvidenceItem(origin="requirement", text=next(item for item in job.requirements if str(years) in item))
        )

    if _location_matches(job.location, preferences.target_locations):
        score += 10
        evidence.setdefault("location", []).append(EvidenceItem(origin="job detail", text=job.location or ""))
    elif job.location:
        score -= 10
        hard_gates.append(f"Location does not clearly match saved targets: {job.location}")
    else:
        missing.append("Exact work location")

    acceptable_salary = preferences.acceptable_salary_min
    if job.salary_min_annual is not None:
        evidence.setdefault("salary", []).append(EvidenceItem(origin="job detail", text=job.salary_display or ""))
        if acceptable_salary is not None and job.salary_min_annual < acceptable_salary:
            score -= 12
            hard_gates.append("Advertised minimum salary is below the saved acceptable minimum.")
        elif acceptable_salary is not None:
            score += 10
    else:
        missing.append("Annual salary")

    if job.work_mode:
        mode = job.work_mode.casefold()
        wanted = {item.casefold() for item in preferences.work_modes}
        if ("hybrid" in mode and "hybrid" in wanted) or ("home" in mode and wanted & {"hybrid", "remote", "homeoffice"}):
            score += 5
            evidence.setdefault("work_mode", []).append(EvidenceItem(origin="job detail", text=job.work_mode))
    else:
        missing.append("Work model")

    adjacent = [tech for tech in job.technologies if tech in {"Python", "JavaScript", "TypeScript", "React", "Linux", "SQL", "SAP", "UiPath", "Git"}]
    if adjacent:
        score += min(8, 2 * len(adjacent))
        evidence.setdefault("skill_adjacency", []).append(
            EvidenceItem(origin="job detail", text=", ".join(adjacent), profile_fact_ref="confirmed technical background")
        )

    if "deutsch" in folded or "german" in folded:
        evidence.setdefault("language", []).append(EvidenceItem(origin="job detail", text="German is mentioned in the posting."))

    score = max(0, min(100, score))
    verdict = "strong" if score >= 70 else "maybe" if score >= 55 else "reject"
    confidence = "high" if job.requirements and job.salary_min_annual is not None else "medium"
    summary = _fit_summary(job, verdict, priority_match or broad_match, years)
    source_evidence = {
        "title": [job.title],
        "company": [job.company],
        "location": [job.location] if job.location else [],
        "salary": [job.salary_display] if job.salary_display else [],
    }
    return JobAnalysisIn(
        score=score,
        verdict=verdict,
        confidence=confidence,
        summary=summary,
        fit_evidence=evidence,
        missing_info=missing,
        hard_gate_reasons=hard_gates,
        requirements=job.requirements,
        responsibilities=job.responsibilities,
        technologies=job.technologies,
        salary_display=job.salary_display,
        salary_min_annual=job.salary_min_annual,
        salary_max_annual=job.salary_max_annual,
        salary_currency="EUR" if job.salary_display else None,
        work_mode=job.work_mode,
        language_environment="German / English" if ("deutsch" in folded and "englisch" in folded) else None,
        source_evidence=source_evidence,
    )


def build_application_draft(job: KarriereJobDetail, analysis: JobAnalysisIn) -> ApplicationDraft:
    role = job.title.strip()
    company = job.company.strip()
    angle = _job_angle(job)
    subject = f"Bewerbung als {role}"
    paragraphs = [
        "Sehr geehrte Damen und Herren,",
        (
            f"die Position als {role} bei {company} interessiert mich, weil sie praktische Softwareentwicklung "
            f"mit {angle} verbindet."
        ),
        (
            "In meiner aktuellen Tätigkeit im IT-Support bei SEW-EURODRIVE entwickle ich neben dem operativen "
            "Support Automatisierungen und interne Anwendungen. Dabei arbeite ich unter anderem mit Python sowie "
            "mit Prozess- und Systemintegrationen und reduziere manuellen Aufwand in wiederkehrenden Abläufen."
        ),
        (
            "Meine Informatikausbildung an der HTL Spengergasse gibt mir ein breites technisches Fundament. "
            "Ich lerne neue Technologien schnell, arbeite strukturiert und möchte meine praktische Erfahrung "
            "in Software, internen Webanwendungen und Automatisierung gezielt weiter ausbauen."
        ),
        (
            f"Gerne erläutere ich persönlich, wie ich diese Erfahrung in die ausgeschriebene Position bei {company} einbringen kann."
        ),
        "Mit freundlichen Grüßen\nAntonio Beslic",
    ]
    resume_headline = "Software · interne Anwendungen · Automatisierung"
    resume_summary = (
        f"Informatik-Absolvent der HTL Spengergasse mit Praxis in IT-Support, Python-Anwendungen, internen Tools "
        f"und Prozessautomatisierung. Für {html.escape(role)} bei {html.escape(company)} bringe ich technisches "
        "Verständnis, strukturierte Umsetzung und schnelle Einarbeitung mit."
    )
    return ApplicationDraft(
        subject=subject,
        body="\n\n".join(paragraphs),
        resume_headline=resume_headline,
        resume_summary_html=f"<p>{resume_summary}</p>",
    )


def _role_match(values: list[str], title: str) -> str | None:
    normalized_title = _normalize_role_text(title)
    title_tokens = set(normalized_title.split())
    for value in values:
        normalized = _normalize_role_text(value)
        tokens = {token for token in normalized.split() if len(token) >= 3 and token not in {"junior", "jobs", "job"}}
        if not tokens:
            continue
        overlap = len(tokens & title_tokens)
        if overlap >= min(2, len(tokens)) or any(token in normalized_title for token in tokens if len(token) >= 6):
            return " ".join(value.replace("_", " ").split())
    return None


def _normalize_role_text(value: str) -> str:
    folded = " ".join(value.replace("_", " ").casefold().split())
    replacements = {
        "entwickler": "developer", "entwicklerin": "developer", "entwicklung": "developer",
        "softwareentwickler": "software developer", "webentwickler": "web developer",
        "anwendungsentwickler": "application developer", "programmierung": "developer",
    }
    for source, target in replacements.items():
        folded = folded.replace(source, target)
    return re.sub(r"[^a-z0-9+#.]+", " ", folded).strip()


def _required_years(requirements: list[str]) -> int | None:
    for requirement in requirements:
        match = re.search(r"(?:mindestens|min\.?|at least)?\s*(\d+)\s*(?:jahre|years)", requirement, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _location_matches(location: str | None, targets: list[str]) -> bool:
    if not location:
        return False
    folded = location.casefold()
    for target in targets or ["Vienna"]:
        candidate = target.casefold()
        aliases = {candidate}
        if candidate in {"vienna", "wien"}:
            aliases.update({"vienna", "wien"})
        if any(alias in folded for alias in aliases):
            return True
    return False


def _fit_summary(job: KarriereJobDetail, verdict: str, role: str | None, years: int | None) -> str:
    base = f"{job.company} is hiring for {job.title}."
    if verdict == "strong":
        return f"{base} The role and Vienna setup align well with your saved builder profile."
    if verdict == "maybe":
        concern = f" The {years}-year experience request needs a closer look." if years else " A few fit details need review."
        return f"{base} It is adjacent to {role or 'your target roles'}.{concern}"
    return f"{base} The current seniority or preference signals make this a weaker fit."


def _job_angle(job: KarriereJobDetail) -> str:
    if job.responsibilities:
        text = job.responsibilities[0].rstrip(". ")
        if len(text) <= 140:
            return text[0].lower() + text[1:]
    if job.technologies:
        return "modernen Technologien wie " + ", ".join(job.technologies[:3])
    return "der Weiterentwicklung digitaler Produkte"
