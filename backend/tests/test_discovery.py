from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


def test_discovery_parses_firecrawl_deduplicates_and_does_not_ingest(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    os.environ["JOBFLOW_DB"] = str(db_path)
    os.environ["FIRECRAWL_API_KEY"] = "test-key"
    os.environ["FIRECRAWL_API_URL"] = "http://100.64.0.10:3002"

    from jobflow import firecrawl
    from jobflow.database import connect, encode_json, init_db
    from jobflow.main import app

    init_db(db_path)
    with connect(db_path) as db:
        db.execute(
            """
            INSERT INTO preferences (
                id, target_locations_json, work_modes_json, salary_currency,
                role_families_json, priorities_json, hard_rules_json,
                discovery_queries_json, discovery_limit_per_query, updated_at
            )
            VALUES ('default', '[]', '[]', 'EUR', '[]', '[]', '[]', ?, 5, ?)
            """,
            (encode_json(["python vienna", "backend vienna"]), "2026-08-02T08:00:00+00:00"),
        )

    def fake_urlopen(request: Any, timeout: int) -> FakeResponse:
        assert timeout == 60
        assert request.full_url.startswith("http://100.64.0.10:3002/")
        body = json.loads(request.data.decode("utf-8"))
        if request.full_url.endswith("/v2/search"):
            assert "sources" not in body
            if body["query"] == "empty query":
                return FakeResponse({"success": True, "data": {}})
            if body["query"] == "backend vienna":
                return FakeResponse(
                    {
                        "success": True,
                        "data": {
                            "web": [
                                {
                                    "url": "https://example.com/jobs/1?a=1&b=2&utm_campaign=again",
                                    "title": "Duplicate Backend Engineer",
                                    "description": "Duplicate result",
                                },
                                {
                                    "url": "https://example.com/jobs/3",
                                    "title": "Platform Engineer",
                                    "description": "Build workflow systems.",
                                },
                            ]
                        },
                    }
                )
            return FakeResponse(
                {
                    "success": True,
                    "data": {
                        "web": [
                            {
                                "url": "https://Example.com/jobs/1?utm_source=newsletter&b=2&a=1",
                                "title": " Python Engineer ",
                                "description": "  Build APIs.  ",
                            },
                            {
                                "url": "https://example.com/jobs/2",
                                "title": "Data Engineer",
                                "snippet": "Snippet fallback.",
                            },
                            {
                                "url": "http://example.com/not-accepted",
                                "title": "HTTP result",
                                "description": "Search may return it, run skips it.",
                            },
                        ]
                    },
                }
            )
        if request.full_url.endswith("/v1/scrape"):
            return FakeResponse(
                {
                    "success": True,
                    "data": {
                        "markdown": "# Job\nBuild APIs.",
                        "metadata": {"sourceURL": body["url"], "title": "Python Engineer"},
                    },
                }
            )
        raise AssertionError(f"Unexpected Firecrawl URL: {request.full_url}")

    monkeypatch.setattr(firecrawl, "urlopen", fake_urlopen)
    client = TestClient(app)

    search = client.post("/api/discovery/search", json={"query": "python vienna", "limit": 5})
    assert search.status_code == 200
    assert search.json()[0] == {
        "url": "https://Example.com/jobs/1?utm_source=newsletter&b=2&a=1",
        "title": "Python Engineer",
        "description": "Build APIs.",
    }
    assert search.json()[1]["description"] == "Snippet fallback."

    empty_search = client.post("/api/discovery/search", json={"query": "empty query", "limit": 5})
    assert empty_search.status_code == 200
    assert empty_search.json() == []

    scrape = client.post("/api/discovery/scrape", json={"url": "https://example.com/jobs/1"})
    assert scrape.status_code == 200
    assert scrape.json()["markdown"] == "# Job\nBuild APIs."
    assert scrape.json()["metadata"]["title"] == "Python Engineer"

    run = client.post("/api/discovery/run")
    assert run.status_code == 200
    results = run.json()["results"]
    assert [item["url"] for item in results] == [
        "https://example.com/jobs/1?a=1&b=2",
        "https://example.com/jobs/2",
        "https://example.com/jobs/3",
    ]
    assert results[0]["matched_queries"] == ["python vienna", "backend vienna"]
    assert client.get("/api/jobs?filter=all").json() == []


class FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")
