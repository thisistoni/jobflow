from __future__ import annotations

import base64
import importlib
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient


def test_app_session_auth_and_basic_api_client(tmp_path: Path, monkeypatch: Any) -> None:
    module = load_app(tmp_path, monkeypatch)

    from jobflow.database import init_db

    init_db(tmp_path / "jobflow.sqlite3")
    client = TestClient(module.app)

    assert client.get("/health").status_code == 200

    root = client.get("/")
    assert root.status_code == 200
    assert "www-authenticate" not in root.headers

    asset = client.get("/assets/app.js")
    assert asset.status_code == 200
    assert "www-authenticate" not in asset.headers

    status = client.get("/api/auth/status")
    assert status.status_code == 200
    assert status.json() == {"auth_required": True, "authenticated": False, "expires_at": None}

    api = client.get("/api/jobs")
    assert api.status_code == 401
    assert api.json() == {"detail": "Authentication required"}
    assert "www-authenticate" not in api.headers

    bad_login = client.post("/api/auth/login", json={"username": "jobflow-user", "password": "wrong"})
    assert bad_login.status_code == 401
    assert bad_login.json() == {"detail": "Invalid username or password"}
    assert "www-authenticate" not in bad_login.headers

    login = client.post("/api/auth/login", json={"username": "jobflow-user", "password": "jobflow-pass"})
    assert login.status_code == 200
    assert login.json()["authenticated"] is True
    cookie = login.headers["set-cookie"]
    assert "jobflow_session=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie

    assert client.get("/api/auth/status").json()["authenticated"] is True
    assert client.get("/api/jobs").status_code == 200

    logout = client.post("/api/auth/logout")
    assert logout.status_code == 200
    assert logout.json() == {"auth_required": True, "authenticated": False, "expires_at": None}
    after_logout = client.get("/api/jobs")
    assert after_logout.status_code == 401
    assert "www-authenticate" not in after_logout.headers

    token = base64.b64encode(b"jobflow-user:jobflow-pass").decode("ascii")
    basic = client.get("/api/jobs", headers={"Authorization": f"Basic {token}"})
    assert basic.status_code == 200
    assert "www-authenticate" not in basic.headers


def test_partial_auth_config_fails_closed_on_startup(tmp_path: Path, monkeypatch: Any) -> None:
    module = load_app(tmp_path, monkeypatch, password=None)

    with pytest.raises(RuntimeError, match="JOBFLOW_AUTH_USERNAME and JOBFLOW_AUTH_PASSWORD must be set together"):
        with TestClient(module.app):
            pass


def load_app(tmp_path: Path, monkeypatch: Any, password: str | None = "jobflow-pass") -> Any:
    static_dir = tmp_path / "dist"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html><title>JobFlow</title>", encoding="utf-8")
    assets_dir = static_dir / "assets"
    assets_dir.mkdir()
    (assets_dir / "app.js").write_text("console.log('jobflow');", encoding="utf-8")

    monkeypatch.setenv("JOBFLOW_DB", str(tmp_path / "jobflow.sqlite3"))
    monkeypatch.setenv("JOBFLOW_STATIC_DIR", str(static_dir))
    monkeypatch.setenv("JOBFLOW_AUTH_USERNAME", "jobflow-user")
    if password is None:
        monkeypatch.delenv("JOBFLOW_AUTH_PASSWORD", raising=False)
    else:
        monkeypatch.setenv("JOBFLOW_AUTH_PASSWORD", password)
    monkeypatch.setenv("JOBFLOW_AUTH_COOKIE_SECURE", "false")

    module_name = "jobflow.main"
    if module_name in sys.modules:
        return importlib.reload(sys.modules[module_name])
    return importlib.import_module(module_name)
