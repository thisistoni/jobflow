from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from html.parser import HTMLParser
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
    home_office_days: int | None = None
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
    listing_urls_by_query: dict[str, list[str]] = {}
    raw_count = 0
    try:
        for index, query in enumerate(cleaned_queries):
            if index:
                client.navigate(tab_id, _search_url(query))
            parsed = parse_search_snapshot(client.snapshot(tab_id))[:limit_per_query]
            listing_urls_by_query[query] = [listing.url for listing in parsed]
            raw_count += len(parsed)
            for listing in parsed:
                existing = listings.get(listing.url)
                if existing is None:
                    listing.matched_queries.append(query)
                    listings[listing.url] = listing
                elif query not in existing.matched_queries:
                    existing.matched_queries.append(query)

        details: list[KarriereJobDetail] = []
        ordered_listings = _fair_listing_order(cleaned_queries, listing_urls_by_query, listings)
        for listing in ordered_listings[:max_details]:
            detail_tab_id = client.create_tab(listing.url)
            try:
                try:
                    detail = parse_detail_snapshot(client.snapshot(detail_tab_id), listing.url)
                except CamofoxProviderError:
                    # Search results can contain listings that expire or redirect between
                    # the result-page snapshot and the detail navigation. Skip that one
                    # candidate; never abort the rest of a multi-job run.
                    continue
                try:
                    refresh_karriere_detail(detail)
                except CamofoxProviderError:
                    # The browser snapshot remains a bounded fallback. A temporary
                    # structured-data fetch failure must not abort the full run.
                    pass
                _enrich_detail_from_listing(detail, listing)
                detail.matched_queries = list(listing.matched_queries)
                details.append(detail)
            finally:
                client.close_tab(detail_tab_id)
        if listings and not details:
            raise CamofoxProviderError("Karriere.at search returned listings, but no detail page could be normalized")
        return raw_count, details
    finally:
        client.close_tab(tab_id)


def refresh_karriere_detail(detail: KarriereJobDetail) -> KarriereJobDetail:
    """Refresh one canonical Karriere record from its public JobPosting JSON-LD."""
    _enrich_detail_from_job_posting(detail, _fetch_job_posting(detail.url))
    return detail


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
    company = _employer_name(lines) or _header_company(lines, title)
    location = _term_value(lines, "Dienstorte") or _term_value(lines, "Dienstort") or _term_value(lines, "Arbeitsort")
    salary_display = _term_value(lines, "Gehalt")
    work_mode = _term_value(lines, "Arbeitsmodell")
    home_office_days = _home_office_days(work_mode)
    requirements = _section_items(lines, ("qualifikation", "anforderung", "dein profil", "das bringst du"))
    responsibilities = _section_items(lines, ("rolle und aufgaben", "deine aufgaben", "tätigkeiten", "aufgabengebiet"))
    has_embedded_detail = any(_line_text(line).casefold() == "über den job" for line in lines)
    meaningful = []
    if has_embedded_detail:
        for line in lines:
            text = _line_text(line)
            if text and text not in meaningful:
                meaningful.append(text)
    else:
        meaningful = [part for part in (title, company) if part]
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
        home_office_days=home_office_days,
    )


def _search_url(query: str) -> str:
    structured = re.fullmatch(r"(.+?)\s+(?:jobs|company careers)\s+([^,]+)", " ".join(query.split()), re.IGNORECASE)
    if structured:
        role_slug = _search_slug(structured.group(1))
        location_slug = _search_slug(structured.group(2))
        return f"{KARRIERE_SEARCH_URL}/{role_slug}/{location_slug}"
    return f"{KARRIERE_SEARCH_URL}?{urllib.parse.urlencode({'keywords': query})}"


def _search_slug(value: str) -> str:
    slug = re.sub(r"[^\w]+", "-", value.casefold(), flags=re.UNICODE).strip("-")
    return urllib.parse.quote(slug, safe="-")


def _fair_listing_order(
    queries: list[str],
    listing_urls_by_query: dict[str, list[str]],
    listings: dict[str, KarriereListing],
) -> list[KarriereListing]:
    """Round-robin result pages so the first role query cannot consume the detail budget."""
    ordered: list[KarriereListing] = []
    seen: set[str] = set()
    width = max((len(listing_urls_by_query.get(query, [])) for query in queries), default=0)
    for offset in range(width):
        for query in queries:
            urls = listing_urls_by_query.get(query, [])
            if offset >= len(urls):
                continue
            url = urls[offset]
            if url in seen or url not in listings:
                continue
            seen.add(url)
            ordered.append(listings[url])
    return ordered


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


def _header_company(lines: list[str], title: str) -> str:
    if not title:
        return ""
    for index, line in enumerate(lines):
        if f'- heading "{title}" [level=1]' not in line:
            continue
        for previous in reversed(lines[max(0, index - 4):index]):
            match = re.search(r'- img "(.+?)"', previous.strip())
            if match and match.group(1).strip().casefold() != "logo karriere.at":
                return match.group(1).strip()
        break
    return ""


def _enrich_detail_from_listing(detail: KarriereJobDetail, listing: KarriereListing) -> None:
    card = listing.snippet
    folded = card.casefold()
    if not detail.location:
        if re.search(r"\b(?:dienstort|dienstorte|arbeitsort)\b[^.:\n]*\bwien\b", folded):
            detail.location = "Wien"
    if not detail.salary_display and "€" in card:
        detail.salary_display = card
        detail.salary_min_annual, detail.salary_max_annual = _annual_salary(card)
    if not detail.work_mode:
        if "homeoffice" in folded or "hybrid" in folded:
            detail.work_mode = "Hybrid"
            detail.home_office_days = _home_office_days(detail.work_mode)
        elif re.search(r"\b(?:on-site|onsite|vor ort)\b", folded):
            detail.work_mode = "On-site"
            detail.home_office_days = 0
    if len(detail.description.splitlines()) <= 2 and card:
        detail.description = "\n".join(part for part in (detail.title, detail.company, card) if part)[:30_000]
        detail.technologies = _technology_hits(detail.description)


class _PostingDescriptionParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.events: list[tuple[str, str]] = []
        self._capture_tag: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.casefold()
        if self._capture_tag is None and (normalized in {"p", "li"} or re.fullmatch(r"h[1-6]", normalized)):
            self._capture_tag = normalized
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._capture_tag is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture_tag != tag.casefold():
            return
        capture_tag = self._capture_tag
        if capture_tag is None:
            return
        text = " ".join("".join(self._parts).split())
        if text:
            self.events.append((capture_tag, text))
        self._capture_tag = None
        self._parts = []


def _fetch_job_posting(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        _canonical_job_url(url),
        headers={"Accept": "text/html,application/xhtml+xml", "User-Agent": "JobFlow/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            raw = response.read(2_000_001)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
        raise CamofoxProviderError("Karriere.at structured job fetch failed") from exc
    if len(raw) > 2_000_000:
        raise CamofoxProviderError("Karriere.at job page was too large")
    return _parse_job_posting_html(raw.decode("utf-8", "replace"))


def _parse_job_posting_html(page_html: str) -> dict[str, Any]:
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for script in scripts:
        try:
            payload = json.loads(script)
        except json.JSONDecodeError:
            continue
        queue: list[Any] = list(payload) if isinstance(payload, list) else [payload]
        while queue:
            item = queue.pop(0)
            if not isinstance(item, dict):
                continue
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if "JobPosting" in types:
                return item
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)
    raise CamofoxProviderError("Karriere.at page did not contain JobPosting structured data")


def _enrich_detail_from_job_posting(detail: KarriereJobDetail, posting: dict[str, Any]) -> None:
    title = posting.get("title")
    if isinstance(title, str) and title.strip():
        detail.title = " ".join(title.split())
    organization = posting.get("hiringOrganization")
    if isinstance(organization, dict) and isinstance(organization.get("name"), str):
        detail.company = " ".join(str(organization["name"]).split())

    locality = _structured_location(posting.get("jobLocation"))
    if locality:
        detail.location = locality

    description_html = posting.get("description")
    if isinstance(description_html, str) and description_html.strip():
        parser = _PostingDescriptionParser()
        parser.feed(description_html)
        parser.close()
        plain_parts: list[str] = []
        requirements: list[str] = []
        responsibilities: list[str] = []
        section: str | None = None
        for tag, text in parser.events:
            if text not in plain_parts:
                plain_parts.append(text)
            if tag.startswith("h"):
                folded = text.casefold()
                if any(term in folded for term in (
                    "anforder", "dein profil", "profil", "qualifikation", "das bringst du", "du bietest",
                    "requirements", "your skills", "skills that inspire", "what you bring",
                    "your profile", "must-have skills", "required skills", "qualifications",
                )):
                    section = "requirements"
                elif any(term in folded for term in (
                    "aufgaben", "deine rolle", "deine zukünftige rolle", "tätigkeiten", "aufgabengebiet",
                    "responsibilities", "tasks", "your role", "what you'll do", "what you will do",
                )):
                    section = "responsibilities"
                else:
                    section = None
            elif tag == "li" and section == "requirements" and text not in requirements:
                requirements.append(text)
            elif tag == "li" and section == "responsibilities" and text not in responsibilities:
                responsibilities.append(text)
        if plain_parts:
            detail.description = "\n".join(plain_parts)[:30_000]
        if requirements:
            detail.requirements = requirements
        if responsibilities:
            detail.responsibilities = responsibilities

    salary_display, salary_min, salary_max = _structured_salary(posting.get("baseSalary"))
    if salary_display:
        detail.salary_display = salary_display
        detail.salary_min_annual = salary_min
        detail.salary_max_annual = salary_max
    detail.technologies = _technology_hits(
        " ".join([detail.title, detail.description, *detail.requirements, *detail.responsibilities])
    )
    parsed_home_office_days = _home_office_days(detail.description, allow_onsite_zero=False)
    if parsed_home_office_days is not None:
        detail.home_office_days = parsed_home_office_days
    elif detail.home_office_days == 0 and detail.work_mode and "hybrid" in detail.work_mode.casefold():
        # A generic "vor Ort" phrase in the advert body is not proof of a
        # zero-day policy for an otherwise hybrid role.
        detail.home_office_days = None


def _structured_location(value: Any) -> str | None:
    places = value if isinstance(value, list) else [value]
    for place in places:
        if not isinstance(place, dict):
            continue
        address = place.get("address")
        if isinstance(address, dict):
            locality = address.get("addressLocality")
            if isinstance(locality, str) and locality.strip():
                return " ".join(locality.split())
    return None


def _structured_salary(value: Any) -> tuple[str | None, int | None, int | None]:
    if not isinstance(value, dict):
        return None, None, None
    amount = value.get("value")
    if not isinstance(amount, dict):
        return None, None, None
    unit = str(amount.get("unitText") or "").upper()
    raw_min = amount.get("minValue", amount.get("value"))
    raw_max = amount.get("maxValue", amount.get("value"))
    if not isinstance(raw_min, (int, float)) or not isinstance(raw_max, (int, float)):
        return None, None, None
    multiplier = 14 if unit == "MONTH" else 1 if unit == "YEAR" else 0
    if not multiplier:
        return None, None, None
    annual_min = round(float(raw_min) * multiplier)
    annual_max = round(float(raw_max) * multiplier)
    currency = str(value.get("currency") or "EUR")
    if unit == "MONTH":
        monthly = f"{float(raw_min):,.2f}" if raw_min != raw_max else f"{float(raw_min):,.2f}"
        if raw_min != raw_max:
            monthly = f"{float(raw_min):,.2f}–{float(raw_max):,.2f}"
        display = f"{currency} {monthly} gross/month · {annual_min:,}–{annual_max:,} gross/year" if annual_min != annual_max else f"{currency} {monthly} gross/month · {annual_min:,} gross/year"
    else:
        display = f"{currency} {annual_min:,}–{annual_max:,} gross/year" if annual_min != annual_max else f"{currency} {annual_min:,} gross/year"
    return display, annual_min, annual_max


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


def _home_office_days(display: str | None, *, allow_onsite_zero: bool = True) -> int | None:
    if not display:
        return None
    folded = display.casefold()
    match = re.search(r"(\d+)\s*(?:tage|days).{0,20}(?:home|remote)", folded)
    if match:
        return int(match.group(1))
    if "remote" in folded or "homeoffice" in folded:
        return 5 if "voll" in folded or "full" in folded else None
    if "hybrid" in folded:
        return None
    if allow_onsite_zero and ("vor ort" in folded or "on-site" in folded or "onsite" in folded):
        return 0
    return None


def _technology_hits(text: str) -> list[str]:
    technologies = [
        "Python", "JavaScript", "TypeScript", "Node.js", "React", "Vue", "Angular", "Java",
        "C#", ".NET", "C++", "AWS", "Azure", "Docker", "Kubernetes", "Linux", "SQL", "NoSQL",
        "SAP", "UiPath", "Git",
    ]
    folded = text.casefold()
    return [technology for technology in technologies if technology.casefold() in folded]
