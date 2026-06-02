"""Tests for the FastAPI web layer. A fake LLM is injected — no network is touched."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from meeting_minutes import web
from meeting_minutes.llm import OpenRouterGuardError, TruncatedResponseError
from meeting_minutes.web import app, default_client_factory


class FakeLlm:
    def generate(self, system: str, user: str, *, model: str) -> str:
        # Echo enough to assert wiring: a heading + whether the user block carried inputs.
        return "## Topic\nGenerated."


@pytest.fixture
def client():
    app.dependency_overrides[default_client_factory] = lambda: (lambda backend: FakeLlm())
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _transcript_file(segments=None):
    segments = segments if segments is not None else [
        {"speaker": "Alice", "start": 0, "end": 2, "text": "Q3 budget is over."},
        {"speaker": "Bob", "start": 2, "end": 4, "text": "Move to spot pricing."},
    ]
    return ("transcript.json", json.dumps(segments).encode(), "application/json")


class TestHealth:
    def test_health_ok(self, client):
        assert client.get("/api/health").json() == {"status": "ok"}


class TestInspect:
    def test_returns_counts_speakers_duration(self, client):
        resp = client.post(
            "/api/inspect", files={"transcript": _transcript_file()}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["segment_count"] == 2
        assert body["speakers"] == ["Alice", "Bob"]
        assert body["duration"] == "00:00:04"

    def test_alternate_field_keys(self, client):
        segs = [{"spk": "A", "begin": 0, "stop": 1, "content": "hi"}]
        resp = client.post(
            "/api/inspect",
            files={"transcript": ("t.json", json.dumps(segs).encode(), "application/json")},
            data={"speaker_key": "spk", "start_key": "begin", "end_key": "stop", "text_key": "content"},
        )
        assert resp.status_code == 200
        assert resp.json()["speakers"] == ["A"]


TEAMS_TEXT = (
    "اجتماع تجريبي\nThu, May 14, 2026\n\n"
    "0:05 - مشاري\nمرحبا بالجميع.\n\n"
    "1:20 - عبادة\nاستعرضت المصفوفة ومراحلها.\n"
)


class TestTeamsTextFormat:
    def test_inspect_parses_teams_text_and_sniffs_header(self, client):
        resp = client.post(
            "/api/inspect",
            files={"transcript": ("meeting.txt", TEAMS_TEXT.encode(), "text/plain")},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["segment_count"] == 2
        assert "مشاري" in body["speakers"]
        assert body["detected"]["title"] == "اجتماع تجريبي"

    def test_minutes_from_teams_text_with_metadata(self, client):
        resp = client.post(
            "/api/minutes",
            files={"transcript": ("meeting.txt", TEAMS_TEXT.encode(), "text/plain")},
            data={
                "title": "اجتماع",
                "date": "11/5/2026",
                "time": "11:30–12:30",
                "location": "عن بعد",
                "attendees": "مشاري — هيئة الحكومة الرقمية",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "##" in body["minutes"]
        assert body["meta"]["segments"] == 2

    def test_inspect_json_has_empty_detected(self, client):
        resp = client.post("/api/inspect", files={"transcript": _transcript_file()})
        assert resp.json()["detected"] == {"title": "", "date": ""}


class TestMinutes:
    def test_happy_path(self, client):
        resp = client.post(
            "/api/minutes",
            files={"transcript": _transcript_file()},
            data={"notes": "budget", "title": "Sync", "date": "2026-06-01"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "##" in body["minutes"]
        assert body["meta"]["segments"] == 2

    def test_bad_json_is_400(self, client):
        resp = client.post(
            "/api/minutes",
            files={"transcript": ("t.json", b"{not json", "application/json")},
        )
        assert resp.status_code == 400
        assert "valid JSON" in resp.json()["error"]

    def test_empty_transcript_is_400(self, client):
        resp = client.post(
            "/api/minutes",
            files={"transcript": ("t.json", b"[]", "application/json")},
        )
        assert resp.status_code == 400
        assert "no segments" in resp.json()["error"]

    def test_oversize_is_413(self, client, monkeypatch):
        monkeypatch.setattr(web, "MAX_TRANSCRIPT_BYTES", 5)
        resp = client.post(
            "/api/minutes", files={"transcript": _transcript_file()}
        )
        assert resp.status_code == 413

    def test_speaker_map_applied(self, client):
        segs = [{"speaker": "SPEAKER_00", "start": 0, "end": 1, "text": "hi"}]
        resp = client.post(
            "/api/minutes",
            files={"transcript": ("t.json", json.dumps(segs).encode(), "application/json")},
            data={"speaker_map": "SPEAKER_00=Alice"},
        )
        assert resp.status_code == 200

    def test_malformed_segment_is_400(self, client):
        segs = [{"speaker": "A", "start": "soon", "end": 1, "text": "x"}]
        resp = client.post(
            "/api/minutes",
            files={"transcript": ("t.json", json.dumps(segs).encode(), "application/json")},
        )
        assert resp.status_code == 400


class _RaiseAtGenerate:
    def __init__(self, exc):
        self._exc = exc

    def generate(self, system, user, *, model):
        raise self._exc


def _override(factory):
    app.dependency_overrides[default_client_factory] = factory
    return TestClient(app)


class TestErrorMapping:
    """The engine's exceptions map to clean HTTP status codes."""

    def teardown_method(self):
        app.dependency_overrides.clear()

    def test_openrouter_guard_is_403(self):
        def factory():
            def make(_backend):
                raise OpenRouterGuardError("points at OpenRouter")
            return make

        c = _override(factory)
        resp = c.post("/api/minutes", files={"transcript": _transcript_file()})
        assert resp.status_code == 403
        assert "OpenRouter" in resp.json()["error"]

    def test_missing_api_key_is_500(self):
        def factory():
            def make(_backend):
                raise RuntimeError("GROQ_API_KEY is not set")
            return make

        c = _override(factory)
        resp = c.post("/api/minutes", files={"transcript": _transcript_file()})
        assert resp.status_code == 500

    def test_truncated_response_is_502(self):
        c = _override(lambda: (lambda _b: _RaiseAtGenerate(TruncatedResponseError("trunc"))))
        resp = c.post("/api/minutes", files={"transcript": _transcript_file()})
        assert resp.status_code == 502

    def test_generic_runtime_error_is_502(self):
        c = _override(lambda: (lambda _b: _RaiseAtGenerate(RuntimeError("model returned empty"))))
        resp = c.post("/api/minutes", files={"transcript": _transcript_file()})
        assert resp.status_code == 502


class TestSpaFallback:
    def test_serves_needs_build_message_when_unbuilt(self):
        # frontend/dist does not exist yet → the GET / fallback route is registered.
        with TestClient(app) as c:
            resp = c.get("/")
        if resp.status_code == 200 and "Frontend not built" in resp.text:
            assert "npm run build" in resp.text
        else:
            pytest.skip("frontend/dist exists; SPA is mounted")


class TestRealBackendErrors:
    """Exercise the real exception->HTTP mapping without the fake override."""

    def test_claude_stub_is_501(self):
        # No override: real get_client → claude stub raises NotImplementedError → 501.
        with TestClient(app) as c:
            resp = c.post(
                "/api/minutes",
                files={"transcript": _transcript_file()},
                data={"backend": "claude"},
            )
        assert resp.status_code == 501

    def test_unknown_backend_is_400(self):
        with TestClient(app) as c:
            resp = c.post(
                "/api/minutes",
                files={"transcript": _transcript_file()},
                data={"backend": "nope"},
            )
        assert resp.status_code == 400
