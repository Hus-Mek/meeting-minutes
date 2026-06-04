"""Tests for the GET /api/update/check endpoint.

The checker (``meeting_minutes.update.check_for_update``) is stubbed so no network
call is made — these only assert the endpoint wiring + JSON shape.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from meeting_minutes.update import UpdateInfo
from meeting_minutes.web import app


def test_update_check_reports_available(monkeypatch):
    # Arrange — a newer release exists.
    monkeypatch.setattr(
        "meeting_minutes.update.check_for_update",
        lambda *args, **kwargs: UpdateInfo(
            current="1.0.3",
            latest="v1.0.4",
            update_available=True,
            html_url="https://github.com/Hus-Mek/meeting-minutes/releases/tag/v1.0.4",
            download_url="https://github.com/Hus-Mek/meeting-minutes/releases/download/v1.0.4/MeetingMinutes-Setup.exe",
        ),
    )

    # Act
    with TestClient(app) as client:
        resp = client.get("/api/update/check")

    # Assert
    assert resp.status_code == 200
    body = resp.json()
    assert body["update_available"] is True
    assert body["latest"] == "v1.0.4"
    assert body["download_url"].endswith("MeetingMinutes-Setup.exe")


def test_update_check_reports_up_to_date(monkeypatch):
    # Arrange — running the latest (or the check failed silently).
    monkeypatch.setattr(
        "meeting_minutes.update.check_for_update",
        lambda *args, **kwargs: UpdateInfo(
            current="1.0.4",
            latest=None,
            update_available=False,
            html_url=None,
            download_url=None,
        ),
    )

    # Act
    with TestClient(app) as client:
        resp = client.get("/api/update/check")

    # Assert
    assert resp.status_code == 200
    assert resp.json() == {
        "current": "1.0.4",
        "latest": None,
        "update_available": False,
        "html_url": None,
        "download_url": None,
    }
