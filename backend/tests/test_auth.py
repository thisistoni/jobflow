from __future__ import annotations

import base64
import importlib
import sys
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient


def test_basic_auth_protects_everything_except_health(tmp_path: Path, monkeypatch: Any) -> None:
    db_path = tmp_path / "jobflow.sqlite3"
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><title>JobFlow</title>", encoding="utf-8")

    monkeypatch.setenv("JOBFLOW_DB", str(db_path))
    monkeypatch.setenv("JOBFLOW_STATIC_DIR", str(static_dir))
    monkeypatch.setenv("JOBFLOW_AUTH_USERNAME", "jobflow-user")
    monkeypatch.setenv("JOBFLOW_AUTH_PASSWORD", "jobflow-pass")

    from jobflow.database import init_db

    module_name = "jobflow.main"
    if module_name in sys.modules:
        module = importlib.reload(sys.modules[module_name])
    else:
        module = importlib.import_module(module_name)

    init_db(db_path)
    client = TestClient(module.app)

    assert client.get("/health").status_code == 200

    root = client.get("/")
    assert root.status_code == 401
    assert root.headers["WWW-Authenticate"] == 'Basic realm="JobFlow"'

    api = client.get("/api/jobs")
    assert api.status_code == 401
    assert api.headers["WWW-Authenticate"] == 'Basic realm="JobFlow"'

    token = base64.b64encode(b"jobflow-user:jobflow-pass").decode("ascii")
    headers = {"Authorization": f"Basic {token}"}
    assert client.get("/", headers=headers).status_code == 200
    assert client.get("/api/jobs", headers=headers).status_code == 200
