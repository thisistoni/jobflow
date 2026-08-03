from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

SECRET_ENV = "JOBFLOW_SECRET_KEY"
DEFAULT_BASE_URL = "https://rxresu.me/api/openapi"
MAX_JSON_BYTES = 2_000_000
MAX_PDF_BYTES = 20_000_000


class ReactiveResumeError(RuntimeError):
    pass


class SecretStoreError(RuntimeError):
    pass


def encryption_ready() -> bool:
    try:
        _fernet()
    except SecretStoreError:
        return False
    return True


def encrypt_api_key(api_key: str) -> str:
    value = api_key.strip()
    if not value:
        raise ValueError("Reactive Resume API key is required")
    return _fernet().encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_api_key(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode("ascii")).decode("utf-8")
    except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
        raise SecretStoreError("Stored Reactive Resume credential cannot be decrypted") from exc


def validate_base_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Reactive Resume base URL must be HTTP or HTTPS")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Reactive Resume base URL cannot contain credentials, query, or fragment")
    return value.rstrip("/")


class ReactiveResumeClient:
    def __init__(self, api_key: str, base_url: str = DEFAULT_BASE_URL) -> None:
        if not api_key.strip():
            raise ValueError("Reactive Resume API key is required")
        self._api_key = api_key
        self.base_url = validate_base_url(base_url)
        self._opener = urllib.request.build_opener(_SameOriginRedirectHandler())

    def list_resumes(self) -> list[dict[str, Any]]:
        payload = self._request_json("GET", "/resumes")
        if not isinstance(payload, list):
            raise ReactiveResumeError("Reactive Resume list response was not an array")
        return [row for row in payload if isinstance(row, dict)]

    def get_resume(self, resume_id: str) -> dict[str, Any]:
        payload = self._request_json("GET", f"/resumes/{urllib.parse.quote(resume_id, safe='')}")
        if not isinstance(payload, dict):
            raise ReactiveResumeError("Reactive Resume detail response was not an object")
        return payload

    def duplicate_resume(self, resume_id: str, *, name: str, slug: str, tags: list[str]) -> str:
        payload = self._request_json(
            "POST",
            f"/resumes/{urllib.parse.quote(resume_id, safe='')}/duplicate",
            {"name": name, "slug": slug, "tags": tags},
        )
        if not isinstance(payload, str) or not payload:
            raise ReactiveResumeError("Reactive Resume duplicate response was not an ID")
        return payload

    def patch_resume(
        self,
        resume_id: str,
        *,
        operations: list[dict[str, Any]],
        expected_updated_at: str | None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"operations": operations}
        if expected_updated_at:
            payload["expectedUpdatedAt"] = expected_updated_at
        result = self._request_json(
            "PATCH",
            f"/resumes/{urllib.parse.quote(resume_id, safe='')}",
            payload,
        )
        if not isinstance(result, dict):
            raise ReactiveResumeError("Reactive Resume patch response was not an object")
        return result

    def export_pdf(self, resume_id: str) -> bytes:
        raw, content_type = self._request(
            "GET",
            f"/resumes/{urllib.parse.quote(resume_id, safe='')}/pdf",
            accept="application/pdf",
            max_bytes=MAX_PDF_BYTES,
        )
        if "application/pdf" not in content_type.lower() or not raw.startswith(b"%PDF"):
            raise ReactiveResumeError("Reactive Resume did not return a PDF")
        return raw

    def _request_json(self, method: str, path: str, payload: Any | None = None) -> Any:
        raw, content_type = self._request(
            method,
            path,
            accept="application/json",
            max_bytes=MAX_JSON_BYTES,
            payload=payload,
        )
        if "application/json" not in content_type.lower():
            raise ReactiveResumeError("Reactive Resume returned an unexpected content type")
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ReactiveResumeError("Reactive Resume returned invalid JSON") from exc

    def _request(
        self,
        method: str,
        path: str,
        *,
        accept: str,
        max_bytes: int,
        payload: Any | None = None,
    ) -> tuple[bytes, str]:
        body = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"x-api-key": self._api_key, "Accept": accept}
        if body is not None:
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers=headers,
        )
        try:
            with self._opener.open(request, timeout=30) as response:
                raw = response.read(max_bytes + 1)
                if len(raw) > max_bytes:
                    raise ReactiveResumeError("Reactive Resume response was too large")
                return raw, response.headers.get("content-type", "")
        except urllib.error.HTTPError as exc:
            raise ReactiveResumeError(f"Reactive Resume API returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise ReactiveResumeError("Reactive Resume connection failed") from exc


def _fernet() -> Fernet:
    raw = os.environ.get(SECRET_ENV, "").strip()
    if not raw:
        raise SecretStoreError(f"{SECRET_ENV} is not configured")
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise SecretStoreError(f"{SECRET_ENV} is invalid") from exc


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ReactiveResumeError("Reactive Resume redirect URL is invalid")
    default_port = 443 if parsed.scheme == "https" else 80
    return parsed.scheme.lower(), parsed.hostname.lower(), parsed.port if parsed.port is not None else default_port


class _SameOriginRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = urllib.parse.urljoin(req.full_url, newurl)
        if _origin(req.full_url) != _origin(redirected):
            raise ReactiveResumeError("Reactive Resume cross-origin redirect was refused")
        return super().redirect_request(req, fp, code, msg, headers, redirected)
