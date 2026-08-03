from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any

DEFAULT_CAMOFOX_API_URL = "http://127.0.0.1:9377"
CAMOFOX_API_URL_ENV = "CAMOFOX_API_URL"
KARRIERE_SEARCH_URL = "https://www.karriere.at/jobs"
KARRIERE_JOB_RE = re.compile(r"^https://www\.karriere\.at/jobs/(\d+)$")


class CamofoxConfigError(RuntimeError):
    pass


class CamofoxProviderError(RuntimeError):
    pass


@dataclass(slots=True)
class KarriereListing:
    url: str
    title: str
    company: str = ""
    snippet: str = ""
    matched_queries: list[str] = field(default_factory=list)


@dataclass(slots=True)
class KarriereJobDetail:
    url: str
    source_id: str
    title: str
    company: str
    location: str | None
    description: str
    salary_display: str | None
    salary_min_annual: int | None
    salary_max_annual: int | None
    work_mode: str | None
    requirements: list[str]
    responsibilities: list[str]
    technologies: list[str]
    matched_queries: list[str] = field(default_factory=list)


class CamofoxClient:
    def __init__(self, api_url: str | None = None, *, user_id: str = "jobflow") -> None:
        raw_url = (api_url or os.environ.get(CAMOFOX_API_URL_ENV) or DEFAULT_CAMOFOX_API_URL).strip()
        parsed = urllib.parse.urlsplit(raw_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise CamofoxConfigError("CAMOFOX_API_URL must be an HTTP or HTTPS URL")
        self.api_url = raw_url.rstrip("/")
        self.user_id = user_id

    def health(self) -> bool:
        payload = self._request_json("GET", "/health", timeout=10)
        return bool(payload.get("ok") and payload.get("browserConnected"))

    def create_tab(self, url: str) -> str:
        payload = self._request_json(
            "POST",
            "/tabs",
            {"userId": self.user_id, "sessionKey": f"jobflow-{uuid.uuid4()}", "url": url},
        )
        tab_id = payload.get("tabId")
        if not isinstance(tab_id, str) or not tab_id:
            raise CamofoxProviderError("Camofox did not return a tab ID")
        return tab_id

    def navigate(self, tab_id: str, url: str) -> None:
        self._request_json(
            "POST",
            f"/tabs/{urllib.parse.quote(tab_id, safe='')}/navigate",
            {"userId": self.user_id, "url": url},
        )

    def snapshot(self, tab_id: str) -> str:
        query = urllib.parse.urlencode({"userId": self.user_id, "format": "aria"})
        payload = self._request_json(
            "GET",
            f"/tabs/{urllib.parse.quote(tab_id, safe='')}/snapshot?{query}",
            timeout=60,
        )
        snapshot = payload.get("snapshot")
        if not isinstance(snapshot, str) or not snapshot.strip():
            raise CamofoxProviderError("Camofox returned an empty accessibility snapshot")
        return snapshot

    def close_tab(self, tab_id: str) -> None:
        query = urllib.parse.urlencode({"userId": self.user_id})
        try:
            self._request_json(
                "DELETE",
                f"/tabs/{urllib.parse.quote(tab_id, safe='')}?{query}",
                timeout=15,
                allow_empty=True,
            )
        except CamofoxProviderError:
            pass

    def _request_json(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        timeout: int = 60,
        allow_empty: bool = False,
    ) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(
            self.api_url + path,
            data=body,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read(2_000_001)
        except urllib.error.HTTPError as exc:
            raise CamofoxProviderError(f"Camofox HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise CamofoxProviderError(f"Camofox connection failed: {exc.reason}") from exc
        if len(raw) > 2_000_000:
            raise CamofoxProviderError("Camofox response was too large")
        if not raw and allow_empty:
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CamofoxProviderError("Camofox returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise CamofoxProviderError("Camofox response was not an object")
        return parsed


def camofox_available() -> bool:
    try:
        return CamofoxClient().health()
    except (CamofoxConfigError, CamofoxProviderError):
        return False


def crawl_karriere(
    queries: list[str],
    *,
    limit_per_query: int = 5,
    max_details: int = 8,
) -> tuple[int, list[KarriereJobDetail]]:
    cleaned_queries = [" ".join(query.split()) for query in queries if query.strip()]
    if not cleaned_queries:
        return 0, []
    client = CamofoxClient()
    if not client.health():
        raise CamofoxProviderError("Camofox browser is not connected")

    first_url = _search_url(cleaned_queries[0])
    tab_id = client.create_tab(first_url)
    listings: dict[str, KarriereListing] = {}
    raw_count = 0
    try:
        for index, query in enumerate(cleaned_queries):
            if index:
                client.navigate(tab_id, _search_url(query))
            parsed = parse_search_snapshot(client.snapshot(tab_id))[:limit_per_query]
            raw_count += len(parsed)
            for listing in parsed:
                existing = listings.get(listing.url)
                if existing is None:
                    listing.matched_queries.append(query)
                    listings[listing.url] = listing
                elif query not in existing.matched_queries:
                    existing.matched_queries.append(query)

        details: list[KarriereJobDetail] = []
        for listing in list(listings.values())[:max_details]:
            client.navigate(tab_id, listing.url)
            detail = parse_detail_snapshot(client.snapshot(tab_id), listing.url)
            detail.matched_queries = list(listing.matched_queries)
            details.append(detail)
        return raw_count, details
    finally:
        client.close_tab(tab_id)


def parse_search_snapshot(snapshot: str) -> list[KarriereListing]:
    lines = snapshot.splitlines()
    listings: list[KarriereListing] = []
    seen: set[str] = set()
    for index, line in enumerate(lines):
        heading = re.search(r'- heading "(.+?)" \[level=2\]:$', line.strip())
        if heading is None:
            continue
        title = heading.group(1).strip()
        job_url = ""
        url_index = -1
        for cursor in range(index + 1, min(index + 7, len(lines))):
            url_match = re.search(r'- /url: (https://www\.karriere\.at/jobs/\d+)\s*$', lines[cursor].strip())
            if url_match:
                job_url = url_match.group(1)
                url_index = cursor
                break
        if not job_url or job_url in seen:
            continue
        block_end = min(index + 28, len(lines))
        for cursor in range(index + 1, min(index + 28, len(lines))):
            if cursor > url_index and lines[cursor].startswith("  - listitem"):
                block_end = cursor
                break
        block = lines[url_index + 1:block_end]
        company = ""
        for cursor, value in enumerate(block[:-1]):
            company_match = re.search(r'- link "(.+?)"', value.strip())
            if company_match and "/f/" in block[cursor + 1]:
                company = company_match.group(1).strip()
                break
        snippet_parts = [_line_text(value) for value in block]
        snippet = " ".join(part for part in snippet_parts if part)
        seen.add(job_url)
        listings.append(KarriereListing(url=job_url, title=title, company=company, snippet=snippet[:800]))
    return listings


def parse_detail_snapshot(snapshot: str, requested_url: str) -> KarriereJobDetail:
    canonical = _canonical_job_url(requested_url)
    source_id = canonical.rsplit("/", 1)[-1]
    lines = snapshot.splitlines()
    title = _first_heading(lines, level=1)
    company = _employer_name(lines)
    location = _term_value(lines, "Dienstorte")
    salary_display = _term_value(lines, "Gehalt")
    work_mode = _term_value(lines, "Arbeitsmodell")
    requirements = _section_items(lines, ("qualifikation", "anforderung", "dein profil", "das bringst du"))
    responsibilities = _section_items(lines, ("rolle und aufgaben", "deine aufgaben", "tätigkeiten", "aufgabengebiet"))
    meaningful = []
    for line in lines:
        text = _line_text(line)
        if text and text not in meaningful:
            meaningful.append(text)
    description = "\n".join(meaningful)[:30_000]
    technologies = _technology_hits(" ".join([title, description]))
    salary_min, salary_max = _annual_salary(salary_display)
    if not title or not company:
        raise CamofoxProviderError("Karriere.at detail page lacked a title or employer")
    return KarriereJobDetail(
        url=canonical,
        source_id=source_id,
        title=title,
        company=company,
        location=location,
        description=description,
        salary_display=salary_display,
        salary_min_annual=salary_min,
        salary_max_annual=salary_max,
        work_mode=work_mode,
        requirements=requirements,
        responsibilities=responsibilities,
        technologies=technologies,
    )


def _search_url(query: str) -> str:
    return f"{KARRIERE_SEARCH_URL}?{urllib.parse.urlencode({'keywords': query})}"


def _canonical_job_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    candidate = urllib.parse.urlunsplit(("https", "www.karriere.at", parsed.path.rstrip("/"), "", ""))
    if KARRIERE_JOB_RE.fullmatch(candidate) is None:
        raise CamofoxProviderError("Karriere.at returned a non-canonical job URL")
    return candidate


def _first_heading(lines: list[str], *, level: int) -> str:
    pattern = re.compile(rf'- heading "(.+?)" \[level={level}\]')
    for line in lines:
        match = pattern.search(line.strip())
        if match:
            return match.group(1).strip()
    return ""


def _employer_name(lines: list[str]) -> str:
    for line in lines:
        match = re.search(r'- link "Employer Page von (.+?)"', line.strip())
        if match:
            return match.group(1).strip()
    return _term_value(lines, "Arbeitgeber") or ""


def _term_value(lines: list[str], label: str) -> str | None:
    for index, line in enumerate(lines):
        if _line_text(line).casefold() != label.casefold():
            continue
        for cursor in range(index + 1, min(index + 9, len(lines))):
            text = _line_text(lines[cursor])
            if text and text.casefold() != label.casefold() and text not in {"definition", "paragraph"}:
                if text.startswith("Employer Page von "):
                    return text.removeprefix("Employer Page von ")
                return text
    return None


def _section_items(lines: list[str], heading_terms: tuple[str, ...]) -> list[str]:
    start = -1
    start_level = 3
    for index, line in enumerate(lines):
        match = re.search(r'- heading "(.+?)" \[level=(\d)\]', line.strip())
        if match and any(term in match.group(1).casefold() for term in heading_terms):
            start = index + 1
            start_level = int(match.group(2))
            break
    if start < 0:
        return []
    items: list[str] = []
    for line in lines[start:]:
        heading = re.search(r'- heading "(.+?)" \[level=(\d)\]', line.strip())
        if heading and int(heading.group(2)) <= start_level:
            break
        if "- listitem:" not in line and "- paragraph:" not in line:
            continue
        text = _line_text(line).lstrip("•·- ").strip()
        if text and len(text) > 2 and text not in items:
            items.append(text)
        if len(items) >= 12:
            break
    return items


def _line_text(line: str) -> str:
    stripped = line.strip()
    for pattern in (
        r'- (?:paragraph|text|listitem):\s*(.+)$',
        r'- (?:heading|link|img|button) "(.+?)"(?:\s|$)',
    ):
        match = re.search(pattern, stripped)
        if match:
            return " ".join(match.group(1).split())
    return ""


def _annual_salary(display: str | None) -> tuple[int | None, int | None]:
    if not display:
        return None, None
    values: list[int] = []
    for raw in re.findall(r"\d[\d.]*?(?:,\d{1,2})?(?=\s*€)", display):
        normalized = raw.replace(".", "").replace(",", ".")
        try:
            values.append(round(float(normalized)))
        except ValueError:
            continue
    if not values:
        return None, None
    multiplier = 14 if "monat" in display.casefold() else 1
    annual = [value * multiplier for value in values]
    return min(annual), max(annual)


def _technology_hits(text: str) -> list[str]:
    technologies = [
        "Python", "JavaScript", "TypeScript", "Node.js", "React", "Vue", "Angular", "Java",
        "C#", ".NET", "C++", "AWS", "Azure", "Docker", "Kubernetes", "Linux", "SQL", "NoSQL",
        "SAP", "UiPath", "Git",
    ]
    folded = text.casefold()
    return [technology for technology in technologies if technology.casefold() in folded]
