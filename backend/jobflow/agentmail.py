from __future__ import annotations

import html
import json
import os
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any


AGENTMAIL_API_URL = "https://api.agentmail.to"
DEFAULT_INBOX = "ravenai@agentmail.to"
KARRIERE_JOB_URL = re.compile(
    r"https?://(?:www\.)?karriere\.at/jobs/(\d+)(?:[/?#][^\s<>\"']*)?",
    re.IGNORECASE,
)


class AgentMailConfigError(RuntimeError):
    pass


class AgentMailProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class AlertCandidate:
    url: str
    title: str
    message_id: str
    received_at: str | None


@dataclass(frozen=True)
class ProcessedAlertMessage:
    message_id: str
    subject: str
    received_at: str | None
    link_count: int


@dataclass(frozen=True)
class AlertIngestion:
    messages: list[ProcessedAlertMessage]
    candidates: list[AlertCandidate]


def configured() -> bool:
    return bool(os.environ.get("AGENTMAIL_API_KEY", "").strip())


def karriere_alerts_active() -> bool:
    return os.environ.get("KARRIERE_ALERTS_ACTIVE", "").strip().casefold() in {"1", "true", "yes", "on"}


def inbox_address() -> str:
    return os.environ.get("AGENTMAIL_INBOX", DEFAULT_INBOX).strip() or DEFAULT_INBOX


def fetch_karriere_alerts(seen_message_ids: set[str], *, limit: int = 25) -> AlertIngestion:
    api_key = os.environ.get("AGENTMAIL_API_KEY", "").strip()
    if not api_key:
        raise AgentMailConfigError("AgentMail API key is not configured")
    inbox = inbox_address()
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    encoded_inbox = urllib.parse.quote(inbox, safe="")
    listing = _get_json(
        f"{AGENTMAIL_API_URL}/v0/inboxes/{encoded_inbox}/messages?limit={max(1, min(limit, 50))}",
        headers,
    )
    rows = listing.get("messages", listing.get("data", []))
    if not isinstance(rows, list):
        raise AgentMailProviderError("AgentMail message list was not an array")

    processed: list[ProcessedAlertMessage] = []
    candidates: list[AlertCandidate] = []
    for summary in rows:
        if not isinstance(summary, dict):
            continue
        message_id = str(summary.get("message_id") or summary.get("id") or "").strip()
        if not message_id or message_id in seen_message_ids:
            continue
        encoded_message = urllib.parse.quote(message_id, safe="")
        detail = _get_json(
            f"{AGENTMAIL_API_URL}/v0/inboxes/{encoded_inbox}/messages/{encoded_message}",
            headers,
        )
        subject = str(detail.get("subject") or summary.get("subject") or "karriere.at Job Alarm").strip()
        received_at_value = detail.get("timestamp") or detail.get("received_at") or summary.get("timestamp") or summary.get("received_at")
        received_at = str(received_at_value) if received_at_value else None
        links = extract_karriere_job_urls(_message_text(summary, detail))
        processed.append(
            ProcessedAlertMessage(
                message_id=message_id,
                subject=subject,
                received_at=received_at,
                link_count=len(links),
            )
        )
        candidates.extend(
            AlertCandidate(url=url, title=subject, message_id=message_id, received_at=received_at)
            for url in links
        )
    return AlertIngestion(messages=processed, candidates=candidates)


def extract_karriere_job_urls(value: str) -> list[str]:
    decoded = html.unescape(value)
    urls: list[str] = []
    for match in KARRIERE_JOB_URL.finditer(decoded):
        canonical = f"https://www.karriere.at/jobs/{match.group(1)}"
        if canonical not in urls:
            urls.append(canonical)
    return urls


def _message_text(*containers: dict[str, Any]) -> str:
    values: list[str] = []
    for container in containers:
        for key in ("preview", "text", "html", "extracted_text", "extracted_html", "body"):
            value = container.get(key)
            if isinstance(value, str) and value.strip():
                values.append(value)
        payload = container.get("message")
        if isinstance(payload, dict):
            values.append(_message_text(payload))
    return "\n".join(values)


def _get_json(url: str, headers: dict[str, str]) -> dict[str, Any]:
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:  # nosec B310 - fixed HTTPS origin
            content_type = response.headers.get("content-type", "")
            raw = response.read(2_000_001)
    except Exception as exc:
        raise AgentMailProviderError("AgentMail request failed") from exc
    if len(raw) > 2_000_000 or "application/json" not in content_type.casefold():
        raise AgentMailProviderError("AgentMail returned an invalid response")
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AgentMailProviderError("AgentMail returned invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise AgentMailProviderError("AgentMail response was not an object")
    return decoded
