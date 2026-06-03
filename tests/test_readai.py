"""Tests for read.ai integration."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from meeting_minutes.readai import (
    ReadAiClient,
    TokenSet,
    build_authorize_url,
    exchange_code,
    readai_recap_text,
    readai_turns_to_segments,
    readai_webhook_to_segments,
    refresh_tokens,
    register_client,
    verify_readai_signature,
    _pkce_pair,
)


class _FakeResp:
    """Minimal mock response."""

    def __init__(self, status_code: int, json_data: dict | None = None):
        self.status_code = status_code
        self._json_data = json_data or {}

    def json(self) -> dict:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class TestRegisterClient:
    """OAuth 2.1 client registration."""

    def test_register_client_success(self) -> None:
        """Register a new client and get credentials."""
        httpx = MagicMock()
        httpx.post.return_value = _FakeResp(
            200,
            {
                "client_id": "test_client_id",
                "client_secret": "test_client_secret",
            },
        )

        client_id, client_secret = register_client(httpx_mod=httpx)

        assert client_id == "test_client_id"
        assert client_secret == "test_client_secret"
        httpx.post.assert_called_once()

    def test_register_client_error(self) -> None:
        """Raise on registration failure."""
        httpx = MagicMock()
        httpx.post.return_value = _FakeResp(400, {"error": "invalid_request"})

        with pytest.raises(RuntimeError):
            register_client(httpx_mod=httpx)


class TestReadAiClient:
    """ReadAiClient with mocked httpx."""

    def test_get_transcript_success(self) -> None:
        """Fetch transcript with turns."""
        httpx = MagicMock()
        transcript_data = {
            "turns": [
                {
                    "speaker": {"name": "Alice"},
                    "text": "Hello",
                    "start_time_ms": 0,
                    "end_time_ms": 1000,
                },
                {
                    "speaker": {"name": "Bob"},
                    "text": "Hi there",
                    "start_time_ms": 1000,
                    "end_time_ms": 2000,
                },
            ]
        }
        meeting_data = {"id": "test_id", "transcript": transcript_data}

        def mock_get(url: str, params: dict | None = None, headers: dict | None = None, timeout: float | None = None) -> _FakeResp:
            if "/meetings/test_id" in url:
                return _FakeResp(200, meeting_data)
            raise ValueError(f"Unexpected URL: {url}")

        httpx.get.side_effect = mock_get

        # Create a client with mocked token storage to avoid filesystem access
        from meeting_minutes.readai import TokenSet

        tokens = TokenSet(
            access_token="test_token",
            refresh_token="test_refresh",
            expires_at=9999999999,
            client_id="test_client",
            client_secret="test_secret",
        )
        client = ReadAiClient(tokens=tokens, httpx_mod=httpx)
        transcript = client.get_transcript("test_id")

        assert transcript == transcript_data

    @patch("meeting_minutes.readai.refresh_tokens")
    def test_get_transcript_unauthorized(self, mock_refresh: MagicMock) -> None:
        """Raise on 401 (invalid token) after refresh attempt."""
        httpx = MagicMock()
        # First call is 401, which triggers a refresh attempt; refresh also fails
        httpx.get.return_value = _FakeResp(401)
        mock_refresh.side_effect = RuntimeError("refresh failed")

        from meeting_minutes.readai import TokenSet

        tokens = TokenSet(
            access_token="bad_token",
            refresh_token="test_refresh",
            expires_at=9999999999,
            client_id="test_client",
            client_secret="test_secret",
        )
        client = ReadAiClient(tokens=tokens, httpx_mod=httpx)

        with pytest.raises(RuntimeError):
            client.get_transcript("test_id")


class TestReadAiTurnsToSegments:
    """Convert read.ai transcript to internal Segment format."""

    def test_convert_turns_to_segments(self) -> None:
        """Convert turns with speaker/text/times (in milliseconds)."""
        # read.ai uses real millisecond timestamps (epoch-ms), not small integers
        transcript = {
            "turns": [
                {
                    "speaker": {"name": "Alice"},
                    "text": "Hello world",
                    "start_time_ms": 1_623_456_789_000,  # Real epoch-ms
                    "end_time_ms": 1_623_456_790_500,
                },
                {
                    "speaker": {"name": "Bob"},
                    "text": "Hi Alice",
                    "start_time_ms": 1_623_456_791_000,
                    "end_time_ms": 1_623_456_792_000,
                },
            ]
        }

        segments = readai_turns_to_segments(transcript)

        assert len(segments) == 2
        assert segments[0].speaker == "Alice"
        assert segments[0].text == "Hello world"
        assert segments[0].start_seconds == 1_623_456_789.0  # Converted from ms
        assert segments[0].end_seconds == 1_623_456_790.5
        assert segments[1].speaker == "Bob"
        assert segments[1].start_seconds == 1_623_456_791.0

    def test_convert_empty_turns(self) -> None:
        """Handle empty transcript."""
        transcript = {"turns": []}
        segments = readai_turns_to_segments(transcript)
        assert len(segments) == 0

    def test_convert_missing_speaker_name(self) -> None:
        """Gracefully handle missing speaker names."""
        transcript = {
            "turns": [
                {
                    "speaker": {},
                    "text": "Hello",
                    "start_time_ms": 0,
                    "end_time_ms": 1000,
                },
            ]
        }
        segments = readai_turns_to_segments(transcript)
        assert len(segments) == 1
        assert segments[0].speaker in ("", "Unknown")  # Depends on implementation


class TestReadAiRecapText:
    """Extract recap text from meeting response."""

    def test_extract_summary_text(self) -> None:
        """Extract summary field from meeting."""
        meeting = {
            "id": "test_id",
            "summary": "Project timeline discussed and approved.",
        }
        recap = readai_recap_text(meeting)
        assert recap == "Project timeline discussed and approved."

    def test_missing_summary(self) -> None:
        """Return empty string if no summary."""
        meeting = {"id": "test_id"}
        recap = readai_recap_text(meeting)
        assert recap == ""

    def test_none_summary(self) -> None:
        """Return empty string if summary is null."""
        meeting = {"id": "test_id", "summary": None}
        recap = readai_recap_text(meeting)
        assert recap == ""

    def test_assembles_all_sections(self) -> None:
        meeting = {
            "summary": "We met.",
            "action_items": [{"text": "Do X"}, {"text": "Do Y"}],
            "topics": [{"text": "Budget"}],
            "key_questions": [{"text": "When?"}],
            "chapter_summaries": [{"title": "Intro", "description": "kickoff"}],
        }
        text = readai_recap_text(meeting)
        for needle in ("We met.", "- Do X", "- Do Y", "Budget", "When?", "Intro", "kickoff"):
            assert needle in text


def _tokens(**over) -> TokenSet:
    base = dict(
        access_token="a1",
        refresh_token="r1",
        client_id="cid",
        client_secret="csec",
        expires_at=time.time() + 10_000,
    )
    base.update(over)
    return TokenSet(**base)


class _FakeHttpx:
    """Queue up .get/.post responses (uses the _FakeResp above)."""

    def __init__(self, *, gets=None, posts=None):
        self._gets = list(gets or [])
        self._posts = list(posts or [])
        self.get_calls = []
        self.post_calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.get_calls.append({"url": url, "params": params, "headers": headers})
        return self._gets.pop(0)

    def post(self, url, data=None, json=None, headers=None, timeout=None):
        self.post_calls.append({"url": url, "data": data, "json": json, "headers": headers})
        return self._posts.pop(0)


class TestWebhookToSegments:
    """Webhook payload (speaker_blocks) — a different shape from the REST API."""

    def test_speaker_blocks_end_at_next_start(self) -> None:
        payload = {
            "transcript": {
                "speaker_blocks": [
                    {"start_time": 0, "speaker": {"name": "Alice"}, "words": "hello"},
                    {"start_time": 5, "speaker": {"name": "Bob"}, "words": "hi there"},
                ]
            }
        }
        segs = readai_webhook_to_segments(payload)
        assert (segs[0].speaker, segs[0].start_seconds, segs[0].end_seconds) == ("Alice", 0.0, 5.0)
        assert segs[1].end_seconds == 5.0  # last block ends at its own start

    def test_large_epoch_ms_coerced_to_seconds(self) -> None:
        # Webhook start_time units are undocumented; the heuristic only coerces
        # clearly-epoch-ms (huge) values, leaving small relative offsets as seconds.
        payload = {"transcript": {"speaker_blocks": [
            {"start_time": 1_700_000_000_000, "speaker": {"name": "A"}, "words": "x"},
        ]}}
        assert readai_webhook_to_segments(payload)[0].start_seconds == 1_700_000_000.0


class TestSignature:
    def test_valid_hex_and_prefixed(self) -> None:
        body = b'{"a":1}'
        sig = hmac.new(b"secret", body, hashlib.sha256).hexdigest()
        assert verify_readai_signature("secret", body, sig) is True
        assert verify_readai_signature("secret", body, f"sha256={sig}") is True

    def test_rejects_wrong_missing_or_no_secret(self) -> None:
        assert verify_readai_signature("secret", b"x", "deadbeef") is False
        assert verify_readai_signature("secret", b"x", None) is False
        assert verify_readai_signature("", b"x", "anything") is False


class TestTokenStore:
    def test_save_load_roundtrip_and_perms(self, tmp_path) -> None:
        p = tmp_path / "tok.json"
        _tokens(access_token="aX", refresh_token="rX").save(p)
        loaded = TokenSet.load(p)
        assert (loaded.access_token, loaded.refresh_token) == ("aX", "rX")
        assert oct(p.stat().st_mode)[-3:] == "600"

    def test_load_missing_raises(self, tmp_path) -> None:
        with pytest.raises(RuntimeError, match="auth"):
            TokenSet.load(tmp_path / "nope.json")


class TestOAuthHelpers:
    def test_pkce_pair_is_url_safe(self) -> None:
        verifier, challenge = _pkce_pair()
        assert verifier and challenge
        assert not (set("=+/") & set(challenge))

    def test_authorize_url_has_pkce_params(self) -> None:
        url = build_authorize_url("cid", "chal")
        assert "client_id=cid" in url
        assert "code_challenge=chal" in url
        assert "code_challenge_method=S256" in url

    def test_exchange_code_parses_tokens(self) -> None:
        fake = _FakeHttpx(posts=[_FakeResp(200, {"access_token": "a", "refresh_token": "r", "expires_in": 600})])
        ts = exchange_code(
            client_id="cid", client_secret="csec", code="c", code_verifier="v", httpx_mod=fake
        )
        assert (ts.access_token, ts.refresh_token) == ("a", "r")
        assert fake.post_calls[0]["data"]["grant_type"] == "authorization_code"


class TestRefreshRotation:
    def test_refresh_rotates_and_persists(self, tmp_path) -> None:
        p = tmp_path / "tok.json"
        _tokens(refresh_token="r1", expires_at=time.time() - 1).save(p)
        fake = _FakeHttpx(posts=[_FakeResp(200, {"access_token": "a2", "refresh_token": "r2", "expires_in": 600})])
        client = ReadAiClient(token_path=p, httpx_mod=fake)
        client._do_refresh()
        assert client._tokens.refresh_token == "r2"
        assert TokenSet.load(p).refresh_token == "r2"  # rotated token persisted

    def test_keeps_old_refresh_when_not_rotated(self, tmp_path) -> None:
        p = tmp_path / "tok.json"
        fake = _FakeHttpx(posts=[_FakeResp(200, {"access_token": "a2", "expires_in": 600})])
        client = ReadAiClient(tokens=_tokens(refresh_token="r1"), token_path=p, httpx_mod=fake)
        client._do_refresh()
        assert client._tokens.refresh_token == "r1"

    def test_get_retries_once_on_401_then_succeeds(self, tmp_path) -> None:
        fake = _FakeHttpx(
            gets=[_FakeResp(401), _FakeResp(200, {"data": [], "has_more": False})],
            posts=[_FakeResp(200, {"access_token": "a2", "refresh_token": "r2", "expires_in": 600})],
        )
        client = ReadAiClient(tokens=_tokens(), token_path=tmp_path / "t.json", httpx_mod=fake)
        assert client.list_meetings() == {"data": [], "has_more": False}
        assert len(fake.post_calls) == 1


class TestEndpoints:
    def test_iter_meetings_paginates_with_cursor(self) -> None:
        fake = _FakeHttpx(gets=[
            _FakeResp(200, {"data": [{"id": "m1"}, {"id": "m2"}], "has_more": True}),
            _FakeResp(200, {"data": [{"id": "m3"}], "has_more": False}),
        ])
        client = ReadAiClient(tokens=_tokens(), httpx_mod=fake)
        assert [m["id"] for m in client.iter_meetings()] == ["m1", "m2", "m3"]
        assert fake.get_calls[1]["params"]["cursor"] == "m2"

    def test_get_transcript_sets_expand(self) -> None:
        fake = _FakeHttpx(gets=[_FakeResp(200, {"transcript": {"turns": []}})])
        client = ReadAiClient(tokens=_tokens(), httpx_mod=fake)
        assert client.get_transcript("m1") == {"turns": []}
        assert fake.get_calls[0]["params"]["expand[]"] == ["transcript"]


class TestFetchReport:
    """The convenience used by the web endpoint and fetch script."""

    def test_returns_transcript_and_recap(self) -> None:
        from meeting_minutes.readai import fetch_report

        class _FakeClient:
            def get_transcript(self, mid):
                return {"turns": [{"speaker": {"name": "A"}, "text": "hi", "start_time_ms": 0, "end_time_ms": 1000}]}

            def get_recap(self, mid):
                return {"summary": "We met."}

        transcript, recap = fetch_report(meeting_id="m1", client=_FakeClient())
        assert transcript["turns"][0]["text"] == "hi"
        assert recap == "We met."


class TestWebhookRoute:
    def _client(self):
        from fastapi.testclient import TestClient

        from meeting_minutes.web import app

        return TestClient(app)

    def test_503_without_secret(self, monkeypatch) -> None:
        monkeypatch.delenv("READAI_WEBHOOK_SECRET", raising=False)
        assert self._client().post("/api/webhooks/readai", json={}).status_code == 503

    def test_401_bad_signature(self, monkeypatch) -> None:
        monkeypatch.setenv("READAI_WEBHOOK_SECRET", "shh")
        body = json.dumps({"session_id": "s1"}).encode()
        r = self._client().post(
            "/api/webhooks/readai",
            content=body,
            headers={"Content-Type": "application/json", "X-Read-Signature": "bad"},
        )
        assert r.status_code == 401

    def test_200_valid_signature_and_dedup(self, monkeypatch) -> None:
        monkeypatch.setenv("READAI_WEBHOOK_SECRET", "shh")
        payload = {
            "session_id": "s1",
            "transcript": {"speaker_blocks": [
                {"start_time": 0, "speaker": {"name": "Alice"}, "words": "hello"},
                {"start_time": 5, "speaker": {"name": "Bob"}, "words": "hi"},
            ]},
        }
        body = json.dumps(payload).encode()
        sig = hmac.new(b"shh", body, hashlib.sha256).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "X-Read-Signature": sig,
            "X-Request-Id": "req-unique-1",
        }
        client = self._client()
        r = client.post("/api/webhooks/readai", content=body, headers=headers)
        assert r.status_code == 200
        assert r.json()["segments"] == 2
        r2 = client.post("/api/webhooks/readai", content=body, headers=headers)
        assert r2.json()["status"] == "duplicate"
