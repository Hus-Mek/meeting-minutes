"""Tests for the /api/claude/login endpoint.

The launcher is stubbed so no real console/window is spawned — these only assert
the endpoint wiring (success path + the "no claude to log in to" error path).
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from meeting_minutes.web import app


def test_login_endpoint_spawns_and_returns_started(monkeypatch):
    # Arrange — stub the shared launcher so nothing is actually spawned.
    calls = []
    monkeypatch.setattr(
        "meeting_minutes.llm.launch_claude_login",
        lambda *args, **kwargs: calls.append(True),
    )

    # Act
    with TestClient(app) as client:
        resp = client.post("/api/claude/login")

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {"status": "started"}
    assert calls == [True]


def test_login_endpoint_returns_400_when_no_claude(monkeypatch):
    # Arrange — the launcher reports there is no claude to log in to.
    def _raise(*args, **kwargs):
        raise RuntimeError("Claude Code was not found, so there is nothing to log in to.")

    monkeypatch.setattr("meeting_minutes.llm.launch_claude_login", _raise)

    # Act
    with TestClient(app) as client:
        resp = client.post("/api/claude/login")

    # Assert
    assert resp.status_code == 400
    assert "not found" in resp.json()["error"].lower()


def test_status_endpoint_reports_available(monkeypatch):
    # Arrange — a working CLI resolves and runs.
    monkeypatch.setattr(
        "meeting_minutes.llm.claude_code_available",
        lambda *args, **kwargs: (True, "/usr/bin/claude"),
    )

    # Act
    with TestClient(app) as client:
        resp = client.get("/api/claude/status")

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {"available": True, "path": "/usr/bin/claude"}


def test_status_endpoint_reports_unavailable(monkeypatch):
    # Arrange — no working CLI on this machine.
    monkeypatch.setattr(
        "meeting_minutes.llm.claude_code_available",
        lambda *args, **kwargs: (False, None),
    )

    # Act
    with TestClient(app) as client:
        resp = client.get("/api/claude/status")

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {"available": False, "path": None}
