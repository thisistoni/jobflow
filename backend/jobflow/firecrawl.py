from __future__ import annotations

import json
import os
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


DEFAULT_API_URL = "https://api.firecrawl.dev"
API_URL_ENV = "FIRECRAWL_API_URL"
API_KEY_ENV = "FIRECRAWL_API_KEY"


class FirecrawlError(Exception):
    """Base error for deterministic Firecrawl calls."""


class FirecrawlConfigError(FirecrawlError):
    pass


class FirecrawlProviderError(FirecrawlError):
    pass


def search_web(query: str, limit: int) -> list[dict[str, str]]:
    # The self-hosted v2 endpoint returns an empty data object when the
    # cloud-only `sources` option is present. Omitting it defaults to web.
    payload = {"query": query, "limit": limit}
    response = _post_json("/v2/search", payload)
    data = _require_data(response, "search")
    # Self-hosted Firecrawl returns an empty object when a query has no hits.
    raw_results = data.get("web", []) if isinstance(data, dict) else data
    if not isinstance(raw_results, list):
        raise FirecrawlProviderError("Firecrawl search response did not include web results")
    results: list[dict[str, str]] = []
    for item in raw_results:
        result = _normalize_search_result(item)
        if result is not None:
            results.append(result)
    return results


def scrape_url(url: str) -> dict[str, Any]:
    response = _post_json("/v1/scrape", {"url": url, "formats": ["markdown"]})
    data = _require_data(response, "scrape")
    if not isinstance(data, dict):
        raise FirecrawlProviderError("Firecrawl scrape response data was not an object")
    markdown = data.get("markdown")
    metadata = data.get("metadata") or {}
    if not isinstance(markdown, str):
        raise FirecrawlProviderError("Firecrawl scrape response did not include markdown")
    if not isinstance(metadata, dict):
        raise FirecrawlProviderError("Firecrawl scrape response metadata was not an object")
    result_url = data.get("url") or metadata.get("sourceURL") or metadata.get("url") or url
    if not isinstance(result_url, str) or not result_url.strip():
        result_url = url
    return {"url": result_url, "markdown": markdown, "metadata": metadata}


def _post_json(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise FirecrawlConfigError(f"{API_KEY_ENV} is not configured")
    api_url = os.environ.get(API_URL_ENV, DEFAULT_API_URL).strip() or DEFAULT_API_URL
    url = urljoin(f"{api_url.rstrip('/')}/", path.lstrip("/"))
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=60) as response:
            raw_body = response.read().decode("utf-8")
    except HTTPError as exc:
        raw_error = exc.read().decode("utf-8", errors="replace")
        raise FirecrawlProviderError(f"Firecrawl HTTP {exc.code}: {_safe_error(raw_error, api_key)}") from exc
    except URLError as exc:
        raise FirecrawlProviderError(f"Firecrawl request failed: {exc.reason}") from exc
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise FirecrawlProviderError("Firecrawl response was not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise FirecrawlProviderError("Firecrawl response was not a JSON object")
    return parsed


def _require_data(response: dict[str, Any], operation: str) -> Any:
    if response.get("success") is not True:
        error = response.get("error") or response.get("message") or f"Firecrawl {operation} failed"
        raise FirecrawlProviderError(_redact_api_key(str(error)))
    if "data" not in response:
        raise FirecrawlProviderError(f"Firecrawl {operation} response did not include data")
    return response["data"]


def _normalize_search_result(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    url = _clean_text(item.get("url"))
    if not url:
        return None
    title = _clean_text(item.get("title")) or url
    description = _clean_text(item.get("description")) or _clean_text(item.get("snippet")) or ""
    return {"url": url, "title": title, "description": description}


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = " ".join(value.split())
    return text or None


def _safe_error(body: str, api_key: str) -> str:
    redacted = _redact_api_key(body, api_key)
    try:
        parsed = json.loads(redacted)
    except json.JSONDecodeError:
        return redacted[:500]
    if isinstance(parsed, dict):
        message = parsed.get("error") or parsed.get("message") or parsed.get("code")
    else:
        message = None
    return str(message or parsed)[:500]


def _redact_api_key(text: str, api_key: str | None = None) -> str:
    key = api_key if api_key is not None else os.environ.get(API_KEY_ENV, "")
    return text.replace(key, "[redacted]") if key else text
