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
    # The visible target minimum is the source of truth. Older imported
    # profiles carried a higher hidden fallback that contradicted the UI.
    acceptable_salary = preferences.salary_target_min or preferences.acceptable_salary_min

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
        evidence.setdefault("seniority", []).append(
            EvidenceItem(origin="requirement", text=next(item for item in job.requirements if str(years) in item))
        )

    target_locations = _specific_target_locations(preferences.target_locations)
    if _location_matches(job.location, target_locations):
        score += 10
        evidence.setdefault("location", []).append(EvidenceItem(origin="job detail", text=job.location or ""))
    elif job.location:
        score -= 18
        hard_gates.append(f"Location does not clearly match saved targets: {job.location}")
    else:
        missing.append("Exact work location")
        hard_gates.append("Exact work location is missing.")

    if job.salary_min_annual is not None:
        evidence.setdefault("salary", []).append(EvidenceItem(origin="job detail", text=job.salary_display or ""))
        if acceptable_salary is not None and job.salary_min_annual < acceptable_salary:
            shortfall = (acceptable_salary - job.salary_min_annual) / acceptable_salary
            if shortfall > 0.05:
                score -= 24
                hard_gates.append("Advertised minimum salary is materially below the saved target minimum.")
            else:
                score -= 8
        elif acceptable_salary is not None:
            score += 10
    else:
        missing.append("Annual salary")

    if job.work_mode:
        mode = job.work_mode.casefold()
        normalized_mode = re.sub(r"[^a-z]", "", mode)
        wanted = {re.sub(r"[^a-z]", "", item.casefold()) for item in preferences.work_modes}
        mode_matches = (
            ("hybrid" in normalized_mode and "hybrid" in wanted)
            or (("remote" in normalized_mode or "home" in normalized_mode) and wanted & {"hybrid", "remote", "homeoffice"})
            or ("onsite" in normalized_mode and "onsite" in wanted)
        )
        if mode_matches:
            score += 5
            evidence.setdefault("work_mode", []).append(EvidenceItem(origin="job detail", text=job.work_mode))
        elif wanted:
            score -= 14
            hard_gates.append(f"Work mode does not match saved commute intent: {job.work_mode}.")
    else:
        missing.append("Work model")

    if preferences.min_home_office_days is not None:
        if job.home_office_days is None:
            if job.work_mode and "home" in job.work_mode.casefold():
                evidence.setdefault("work_mode", []).append(EvidenceItem(origin="job detail", text=job.work_mode))
            elif job.work_mode and "hybrid" in job.work_mode.casefold():
                missing.append("Exact home-office days")
            elif not job.work_mode:
                missing.append("Exact home-office days")
            else:
                hard_gates.append("Home-office days do not satisfy the saved minimum.")
                score -= 14
        elif job.home_office_days < preferences.min_home_office_days:
            hard_gates.append("Home-office days are below the saved minimum.")
            score -= 14

    adjacent = [tech for tech in job.technologies if tech in {"Python", "JavaScript", "TypeScript", "React", "Linux", "SQL", "SAP", "UiPath", "Git"}]
    if adjacent:
        score += min(8, 2 * len(adjacent))
        evidence.setdefault("skill_adjacency", []).append(
            EvidenceItem(origin="job detail", text=", ".join(adjacent), profile_fact_ref="confirmed technical background")
        )

    if "deutsch" in folded or "german" in folded:
        evidence.setdefault("language", []).append(EvidenceItem(origin="job detail", text="German is mentioned in the posting."))
    language_preference = (preferences.language_preference or "").casefold()
    if language_preference:
        german_ok = language_preference in {"de", "de-at", "de-de"} or "german" in language_preference or "deutsch" in language_preference
        english_ok = language_preference in {"en", "en-gb", "en-us"} or "english" in language_preference or "englisch" in language_preference
        posting_german = "deutsch" in folded or "german" in folded
        posting_english = "englisch" in folded or "english" in folded
        if (posting_german or posting_english) and not ((posting_german and german_ok) or (posting_english and english_ok)):
            score -= 14
            hard_gates.append("Language environment does not match the saved preference.")
        elif not posting_german and not posting_english:
            missing.append("Language environment")

    if not _source_extract_complete(job):
        for item in _source_missing_items(job):
            if item not in missing:
                missing.append(item)

    score = max(0, min(100, score))
    if hard_gates:
        verdict = "reject"
    else:
        verdict = "strong" if score >= 70 else "maybe" if score >= 55 else "reject"
    confidence = "high" if _source_extract_complete(job) else "medium"
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
        home_office_days=job.home_office_days,
        language_environment="German / English" if ("deutsch" in folded and "englisch" in folded) else None,
        source_evidence=source_evidence,
    )


def build_application_draft(
    job: KarriereJobDetail,
    analysis: JobAnalysisIn,
    *,
    revision_reasons: list[str] | None = None,
    revision_note: str = "",
) -> ApplicationDraft:
    """Write from verified profile evidence instead of echoing advertisement language."""
    del analysis, revision_reasons, revision_note
    role = job.title.strip()
    company = job.company.strip()
    profile = _application_profile(job)
    paragraphs = [
        "Sehr geehrte Damen und Herren,",
        f"ich bewerbe mich als {role} bei {company}. {profile['opening']}",
        profile["evidence"],
        (
            "Meine Ausbildung an der HTL Spengergasse hat mir ein breites Informatik-Fundament gegeben. "
            f"{profile['growth']}"
        ),
        f"{profile['contribution']} Über ein persönliches Gespräch freue ich mich.",
        "Mit freundlichen Grüßen\nAntonio Beslic",
    ]
    resume_summary = (
        f"HTL-Informatik-Absolvent und Junior Software Developer mit Praxis in IT-Support, Python-Anwendungen, "
        f"internen Webanwendungen und Prozessautomatisierung. {profile['resume_focus']}"
    )
    return ApplicationDraft(
        subject=f"Bewerbung als {role}",
        body="\n\n".join(paragraphs),
        resume_headline=profile["headline"],
        resume_summary_html=f"<p>{html.escape(resume_summary)}</p>",
    )


def application_draft_quality_issues(job: KarriereJobDetail, draft: ApplicationDraft) -> list[str]:
    """Reject generic, copied, malformed, or evidence-free application drafts."""
    body = " ".join(draft.body.split())
    normalized_body = _normalize_prose(body)
    issues: list[str] = []
    if job.title not in draft.body or job.company not in draft.body:
        issues.append("Role or company is missing from the letter")
    if "SEW-EURODRIVE" not in draft.body:
        issues.append("No concrete current-work evidence")
    banned = (
        "Die Ausschreibung nennt",
        "Für diese Rolle greife ich besonders",
        "Auf Basis der Review-Notiz",
        "design, develop, and maintain",
    )
    if any(phrase.casefold() in draft.body.casefold() for phrase in banned):
        issues.append("Template or mixed-language source fragment detected")
    for source_item in [*job.requirements, *job.responsibilities]:
        normalized_source = _normalize_prose(source_item)
        if len(normalized_source.split()) >= 8 and normalized_source in normalized_body:
            issues.append("Advertisement sentence copied into application prose")
            break
    words = re.findall(r"\b[\wÄÖÜäöüß-]+\b", draft.body)
    if not 120 <= len(words) <= 260:
        issues.append("Letter length is outside the concise review range")
    if "UiPath" not in draft.body and "Python" not in draft.body and "Webanwendungen" not in draft.body:
        issues.append("No specific candidate evidence appears in the letter")
    summary_text = re.sub(r"<[^>]+>", " ", html.unescape(draft.resume_summary_html))
    if job.title in summary_text or any(
        _normalize_prose(item) in _normalize_prose(summary_text)
        for item in [*job.requirements, *job.responsibilities]
        if len(_normalize_prose(item).split()) >= 8
    ):
        issues.append("CV summary echoes the advertisement instead of profile evidence")
    return issues


def _application_profile(job: KarriereJobDetail) -> dict[str, str]:
    title = job.title.casefold()
    if any(term in title for term in ("test automation", "software tester", "quality assurance", "qa automation", "testautomatis")):
        return {
            "opening": "Automatisierung ist für mich dann gut, wenn sie nicht nur einmal funktioniert, sondern wiederholbar, nachvollziehbar und zuverlässig bleibt.",
            "evidence": (
                "Bei SEW-EURODRIVE verbinde ich operativen IT-Support mit eigener Entwicklungsarbeit. Ich erstelle "
                "UiPath- und Python-Automatisierungen, prüfe Abläufe mit realistischen Fällen und verbessere sie dort, "
                "wo im Alltag Fehler oder unnötige manuelle Schritte auftreten. Die Nähe zu den Anwendern hilft mir, "
                "Probleme konkret zu reproduzieren statt nur technisch zu betrachten."
            ),
            "growth": "Ich möchte diese Praxis gezielt in Richtung Testautomatisierung und verlässlicher Softwarequalität ausbauen.",
            "contribution": f"In der Position bei {job.company} kann ich meine Automatisierungspraxis, meine sorgfältige Fehlersuche und meinen Blick für nutzbare interne Systeme verbinden.",
            "headline": "Junior Test Automation Developer · Python · UiPath",
            "resume_focus": "Praxis in wiederholbaren Automatisierungsabläufen, technischer Fehlersuche und nutzernahem IT-Support.",
        }
    if any(term in title for term in ("finance", "accounting", "controlling", "finanz")):
        return {
            "opening": "Mich motiviert es, wiederkehrende Finanzprozesse so zu automatisieren, dass daraus im Arbeitsalltag eine spürbare Entlastung entsteht.",
            "evidence": (
                "In meiner aktuellen Tätigkeit im IT-Support bei SEW-EURODRIVE habe ich für den Finanzbereich "
                "UiPath-Automatisierungen umgesetzt. Dabei habe ich manuelle Abläufe verstanden, in technische Schritte "
                "übersetzt und mit den beteiligten Fachanwendern abgestimmt. Zusätzlich entwickle ich Python-Anwendungen "
                "und interne Tools, wenn ein schlanker eigener Lösungsweg besser passt."
            ),
            "growth": "Gerade die Verbindung aus Fachprozess, Automatisierung und Softwareentwicklung ist die Richtung, in der ich mich weiterentwickeln möchte.",
            "contribution": f"Bei {job.company} möchte ich diese praktische Automatisierungserfahrung einbringen und Finance-Prozesse Schritt für Schritt zuverlässiger und einfacher machen.",
            "headline": "Junior Automation Developer · Python · UiPath · interne Tools",
            "resume_focus": "Erfahrung mit UiPath-Automatisierungen für den Finanzbereich sowie mit Python-basierten internen Tools.",
        }
    normalized_title = _normalize_role_text(job.title)
    if any(term in normalized_title for term in ("fullstack", "full stack", "frontend", "backend", "web application", "java developer", "software developer")):
        return {
            "opening": "Mich reizt an Softwareentwicklung besonders, aus einem konkreten Problem ein Werkzeug zu bauen, das Menschen im Alltag wirklich verwenden können.",
            "evidence": (
                "Neben meiner Arbeit im IT-Support bei SEW-EURODRIVE entwickle ich Python-Anwendungen, interne "
                "Webanwendungen und Automatisierungen. Dadurch kenne ich sowohl die technische Umsetzung als auch die "
                "Fragen, die im Betrieb wichtig werden: verständliche Abläufe, saubere Übergaben und Lösungen, die für "
                "Anwender nicht unnötig kompliziert sind."
            ),
            "growth": "Neue Frameworks und Sprachen erschließe ich mir über konkrete Projekte; mein Schwerpunkt liegt auf schnellem Lernen und soliden Grundlagen statt auf vorgetäuschter Seniorität.",
            "contribution": f"Bei {job.company} möchte ich als Junior Entwickler Verantwortung übernehmen, verlässlich dazulernen und an Anwendungen mitarbeiten, die einen klaren Zweck erfüllen.",
            "headline": "Junior Software Developer · Python · interne Webanwendungen",
            "resume_focus": "Praxis im Bau interner Anwendungen und Automatisierungen mit engem Bezug zu echten Anwenderproblemen.",
        }
    return {
        "opening": "Ich möchte Software und Automatisierung dort einsetzen, wo sie wiederkehrende Arbeit einfacher und verlässlicher machen.",
        "evidence": (
            "In meiner aktuellen Tätigkeit im IT-Support bei SEW-EURODRIVE entwickle ich zusätzlich Python-Anwendungen, "
            "interne Webanwendungen sowie UiPath- und SAP-nahe Automatisierungen. Dabei übersetze ich Anforderungen aus "
            "dem Arbeitsalltag in kleine, wartbare Lösungen und stimme sie direkt mit den betroffenen Anwendern ab."
        ),
        "growth": "Diese Verbindung aus Technik, Prozessverständnis und schneller Einarbeitung möchte ich in einer Junior-Entwicklerrolle weiter ausbauen.",
        "contribution": f"Bei {job.company} kann ich praktische Automatisierungserfahrung, Supportnähe und Freude am Bauen sinnvoll zusammenbringen.",
        "headline": "Junior Software & Automation Developer · Python · interne Tools",
        "resume_focus": "Praxis in Python-Anwendungen, internen Webanwendungen, UiPath und prozessnaher Automatisierung.",
    }


def _normalize_prose(value: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9äöüß+#.]+", " ", value.casefold()).split())


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
        match = re.search(r"(?:mindestens|min\.?|at least)?\s*(\d+)\s*\+?\s*(?:jahre|years)", requirement, re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _location_matches(location: str | None, targets: list[str]) -> bool:
    if not location:
        return False
    folded = location.casefold()
    for target in targets or ["Wien"]:
        candidate = target.casefold()
        aliases = {candidate}
        if candidate in {"vienna", "wien"}:
            aliases.update({"vienna", "wien"})
        if any(alias in folded for alias in aliases):
            return True
    return False


def _specific_target_locations(targets: list[str]) -> list[str]:
    cleaned = [target for target in targets if target.strip()]
    if len(cleaned) <= 1:
        return cleaned
    broad = {"at", "austria", "österreich", "osterreich"}
    specific = [target for target in cleaned if target.strip().casefold() not in broad]
    return specific or cleaned


def _source_missing_items(job: KarriereJobDetail) -> list[str]:
    missing: list[str] = []
    if len(job.description.strip()) < 180:
        missing.append("Source description")
    if not job.requirements:
        missing.append("Requirements")
    if not job.responsibilities:
        missing.append("Responsibilities")
    return missing


def _source_extract_complete(job: KarriereJobDetail) -> bool:
    return not _source_missing_items(job)


def _tailored_skill_phrase(job: KarriereJobDetail) -> str:
    candidates = [*job.technologies, *job.requirements[:3]]
    cleaned: list[str] = []
    for item in candidates:
        text = " ".join(item.split()).strip(". ")
        if text and text not in cleaned:
            cleaned.append(text)
    if not cleaned:
        return "die im Profil geforderten technischen Grundlagen"
    return ", ".join(cleaned[:4])


def _source_focus(job: KarriereJobDetail) -> str:
    for collection in (job.responsibilities, job.requirements):
        if collection:
            text = collection[0].rstrip(". ")
            return text[:1].lower() + text[1:]
    return "eine schnelle Einarbeitung in die konkreten Aufgaben"


def _revision_sentence(reasons: list[str], note: str) -> str:
    cleaned_reasons = [reason.strip() for reason in reasons if reason.strip()]
    cleaned_note = " ".join(note.split())
    if not cleaned_reasons and not cleaned_note:
        return ""
    reason_text = ", ".join(cleaned_reasons[:3])
    if reason_text and cleaned_note:
        return f"Auf Basis der Review-Notiz wurde diese Fassung stärker auf {reason_text} ausgerichtet: {cleaned_note[:220]}"
    if reason_text:
        return f"Auf Basis der Review-Notiz wurde diese Fassung stärker auf {reason_text} ausgerichtet."
    return f"Auf Basis der Review-Notiz wurde diese Fassung angepasst: {cleaned_note[:260]}"


def _fit_summary(job: KarriereJobDetail, verdict: str, role: str | None, years: int | None) -> str:
    base = f"{job.company} is hiring for {job.title}."
    if verdict == "strong":
        if years is not None and years >= 3:
            return f"{base} The role is strategically relevant, but the {years}-year experience request makes it a stretch application."
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
