"""Retrieve meeting transcripts + recaps from read.ai and feed the minutes engine.

read.ai exposes a REST API (``https://api.read.ai``, OAuth 2.1) that — unlike its
webhooks (Pro+) — is documented as available on **all plans** (open beta), gated
only by a workspace "Downloads" toggle. So this works on a free plan, subject to
the plan's monthly report cap.

This module has four parts:
  * ``ReadAiClient`` — list meetings and fetch a meeting's transcript / recap, with
    OAuth token refresh + single-use refresh-token rotation handled transparently.
  * normalisers — turn read.ai's transcript shape into the app's ``Segment`` tuple
    (REST and webhook payloads have *different* shapes), and assemble a recap hint.
  * ``verify_readai_signature`` — HMAC-SHA256 check for the (Pro-only) webhook.
  * a CLI (``python -m meeting_minutes.readai``) — ``auth`` / ``list`` / ``fetch``.

The webhook *route* lives in ``readai_web.py`` so this module stays free of FastAPI
and importable by the CLI alone.

NOTE: read.ai's API is open beta. The transcript field names are documented and used
below; some response shapes (action-item / topic objects) are passed through as-is.
Verify against a real response from your dashboard before relying on every field.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from .transcript import Segment

# --- API constants (confirmed from read.ai's API docs) -----------------------
API_BASE = "https://api.read.ai"
TOKEN_URL = "https://authn.read.ai/oauth2/token"
REGISTER_URL = f"{API_BASE}/oauth/register"
AUTHORIZE_UI = f"{API_BASE}/oauth/ui"
REDIRECT_URI = f"{API_BASE}/oauth/ui"
SCOPES = "openid email offline_access profile meeting:read mcp:execute"
PAGE_LIMIT = 10  # read.ai caps /meetings at 10 per page
RATE_LIMIT_PER_MIN = 100
# Refresh a little before expiry (access tokens live ~10 min) to avoid races.
REFRESH_SKEW_SECONDS = 60
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}

# Valid `expand[]` values; "transcript" carries the diarized turns.
EXPAND_TRANSCRIPT = ("transcript",)
EXPAND_RECAP = ("summary", "action_items", "topics", "key_questions", "chapter_summaries")


def _token_store_path() -> Path:
    """Where the OAuth tokens are cached (XDG-aware)."""
    override = os.environ.get("READAI_TOKEN_PATH")
    if override:
        return Path(override)
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "meeting-minutes" / "readai_token.json"


@dataclass
class TokenSet:
    """OAuth tokens + the dynamically-registered client credentials.

    ``refresh_token`` is single-use and rotates on every refresh, so it MUST be
    persisted after each refresh or the chain breaks.
    """

    access_token: str
    refresh_token: str
    client_id: str
    client_secret: str
    expires_at: float = 0.0  # epoch seconds

    @classmethod
    def load(cls, path: Path | None = None) -> "TokenSet":
        p = path or _token_store_path()
        if not p.exists():
            raise RuntimeError(
                f"no read.ai token at {p}. Run `python -m meeting_minutes.readai auth` first."
            )
        data = json.loads(p.read_text(encoding="utf-8"))
        return cls(
            access_token=data["access_token"],
            refresh_token=data["refresh_token"],
            client_id=data["client_id"],
            client_secret=data["client_secret"],
            expires_at=float(data.get("expires_at", 0.0)),
        )

    def save(self, path: Path | None = None) -> None:
        p = path or _token_store_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")
        # Tokens are secrets — keep them readable only by the owner.
        try:
            p.chmod(0o600)
        except OSError:
            pass


# --- OAuth 2.1 (PKCE) helpers ------------------------------------------------
def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) for an S256 PKCE flow."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode("ascii")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def _now() -> float:
    return time.time()


def _httpx():
    import httpx

    return httpx


def register_client(*, httpx_mod=None) -> tuple[str, str]:
    """Dynamic client registration → (client_id, client_secret)."""
    httpx = httpx_mod or _httpx()
    resp = httpx.post(
        REGISTER_URL,
        json={
            "redirect_uris": [REDIRECT_URI],
            "scope": SCOPES,
            "token_endpoint_auth_method": "client_secret_basic",
        },
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["client_id"], data["client_secret"]


def build_authorize_url(client_id: str, code_challenge: str) -> str:
    """The browser URL the user visits to approve access and get a code."""
    from urllib.parse import urlencode

    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPES,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{AUTHORIZE_UI}?{query}"


def _basic_auth_header(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode("ascii")
    return "Basic " + base64.b64encode(raw).decode("ascii")


def exchange_code(
    *, client_id: str, client_secret: str, code: str, code_verifier: str, httpx_mod=None
) -> TokenSet:
    """Exchange an authorization code for the initial token set."""
    httpx = httpx_mod or _httpx()
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        headers={"Authorization": _basic_auth_header(client_id, client_secret)},
        timeout=30.0,
    )
    resp.raise_for_status()
    return _token_set_from_response(resp.json(), client_id, client_secret)


def refresh_tokens(tokens: TokenSet, *, httpx_mod=None) -> TokenSet:
    """Use the (single-use) refresh token to get a fresh access token."""
    httpx = httpx_mod or _httpx()
    resp = httpx.post(
        TOKEN_URL,
        data={"grant_type": "refresh_token", "refresh_token": tokens.refresh_token},
        headers={"Authorization": _basic_auth_header(tokens.client_id, tokens.client_secret)},
        timeout=30.0,
    )
    resp.raise_for_status()
    return _token_set_from_response(resp.json(), tokens.client_id, tokens.client_secret)


def _token_set_from_response(data: dict, client_id: str, client_secret: str) -> TokenSet:
    expires_in = float(data.get("expires_in", 600))
    return TokenSet(
        access_token=data["access_token"],
        # If the server omits a rotated refresh token, keep reusing the old one.
        refresh_token=data.get("refresh_token", ""),
        client_id=client_id,
        client_secret=client_secret,
        expires_at=_now() + expires_in,
    )


# --- REST client -------------------------------------------------------------
class ReadAiClient:
    """List meetings and fetch transcript/recap, refreshing tokens as needed."""

    def __init__(
        self,
        tokens: TokenSet | None = None,
        *,
        token_path: Path | None = None,
        httpx_mod=None,
    ) -> None:
        self._path = token_path or _token_store_path()
        self._tokens = tokens or TokenSet.load(self._path)
        self._httpx = httpx_mod or _httpx()

    # -- auth plumbing --
    def _ensure_fresh(self) -> None:
        if self._tokens.expires_at - _now() <= REFRESH_SKEW_SECONDS:
            self._do_refresh()

    def _do_refresh(self) -> None:
        new = refresh_tokens(self._tokens, httpx_mod=self._httpx)
        # Preserve a non-rotated refresh token if the server didn't send a new one.
        if not new.refresh_token:
            new.refresh_token = self._tokens.refresh_token
        self._tokens = new
        self._tokens.save(self._path)  # persist the rotated refresh token immediately

    def _get(self, path: str, params: dict | None = None) -> dict:
        self._ensure_fresh()
        url = f"{API_BASE}{path}"
        for attempt in range(4):
            headers = {"Authorization": f"Bearer {self._tokens.access_token}"}
            resp = self._httpx.get(url, params=params, headers=headers, timeout=30.0)
            if resp.status_code == 401 and attempt == 0:
                self._do_refresh()  # token may have just expired; refresh once and retry
                continue
            if resp.status_code in _RETRYABLE_STATUS and attempt < 3:
                continue
            if resp.status_code == 429:
                raise RuntimeError("read.ai rate limit hit (100 req/min); slow down and retry")
            resp.raise_for_status()
            return resp.json()
        raise RuntimeError(f"read.ai GET {path} failed after retries")

    # -- endpoints --
    def list_meetings(
        self,
        *,
        limit: int = PAGE_LIMIT,
        cursor: str | None = None,
        start_time_ms_gte: int | None = None,
        start_time_ms_lt: int | None = None,
        expand: tuple[str, ...] = (),
    ) -> dict:
        params: dict[str, Any] = {"limit": min(limit, PAGE_LIMIT)}
        if cursor:
            params["cursor"] = cursor
        if start_time_ms_gte is not None:
            params["start_time_ms.gte"] = start_time_ms_gte
        if start_time_ms_lt is not None:
            params["start_time_ms.lt"] = start_time_ms_lt
        if expand:
            params["expand[]"] = list(expand)
        return self._get("/v1/meetings", params)

    def iter_meetings(self, **filters) -> Iterator[dict]:
        """Yield meetings across pages (newest first) until exhausted."""
        cursor: str | None = None
        while True:
            page = self.list_meetings(cursor=cursor, **filters)
            data = page.get("data", [])
            for meeting in data:
                yield meeting
            if not page.get("has_more") or not data:
                return
            cursor = data[-1].get("id")
            if not cursor:
                return

    def get_meeting(self, meeting_id: str, *, expand: tuple[str, ...] = ()) -> dict:
        params = {"expand[]": list(expand)} if expand else None
        return self._get(f"/v1/meetings/{meeting_id}", params)

    def get_transcript(self, meeting_id: str) -> dict:
        """The ``transcript`` object (speakers + turns)."""
        meeting = self.get_meeting(meeting_id, expand=EXPAND_TRANSCRIPT)
        return meeting.get("transcript", {})

    def get_recap(self, meeting_id: str) -> dict:
        """The meeting with summary/action_items/topics expanded (the recap hint)."""
        return self.get_meeting(meeting_id, expand=EXPAND_RECAP)

    def latest_meeting_id(self) -> str | None:
        page = self.list_meetings(limit=1)
        data = page.get("data", [])
        return data[0].get("id") if data else None


def fetch_report(
    *,
    meeting_id: str,
    access_token: str | None = None,
    client: "ReadAiClient | None" = None,
) -> tuple[dict, str]:
    """Fetch ``(transcript_object, recap_text)`` for one meeting.

    Convenience shared by the web endpoint and the fetch script. With
    ``access_token`` the token is used directly (no refresh/persistence — supply a
    fresh one); otherwise the cached OAuth tokens are used. Pass ``client`` to inject
    a pre-built/fake client (tests).
    """
    if client is None:
        if access_token:
            client = ReadAiClient(
                tokens=TokenSet(
                    access_token=access_token,
                    refresh_token="",
                    client_id="",
                    client_secret="",
                    expires_at=_now() + 3600,
                ),
                token_path=Path(os.devnull),  # direct-token mode never touches the real store
            )
        else:
            client = ReadAiClient()
    transcript = client.get_transcript(meeting_id)
    recap = readai_recap_text(client.get_recap(meeting_id))
    return transcript, recap


# --- normalisers: read.ai shapes -> the app's Segment tuple ------------------
def _ms_or_s_to_seconds(value: float) -> float:
    """Coerce a timestamp to seconds, tolerating milliseconds (heuristic)."""
    v = float(value)
    return v / 1000.0 if v >= 1_000_000 else v  # > ~11 days in seconds ⇒ it's ms


def readai_turns_to_segments(transcript: dict) -> tuple[Segment, ...]:
    """REST ``transcript.turns[]`` → Segments (times are epoch-ms, speaker nested).

    Each turn: ``{speaker: {name}, text, start_time_ms, end_time_ms}``. Sorted
    chronologically to match ``transcript.parse_transcript``.
    """
    turns = transcript.get("turns") or []
    segments: list[Segment] = []
    for turn in turns:
        text = (turn.get("text") or "").strip()
        if not text:
            continue
        speaker = (turn.get("speaker") or {}).get("name") or "Unknown"
        start = _ms_or_s_to_seconds(turn.get("start_time_ms", 0))
        end = _ms_or_s_to_seconds(turn.get("end_time_ms", turn.get("start_time_ms", 0)))
        segments.append(Segment(speaker=str(speaker), start_seconds=start, end_seconds=end, text=text))
    return tuple(sorted(segments, key=lambda s: (s.start_seconds, s.end_seconds)))


def readai_webhook_to_segments(payload: dict) -> tuple[Segment, ...]:
    """Webhook ``transcript.speaker_blocks[]`` → Segments (a *different* shape).

    Each block: ``{start_time, speaker: {name}, words}``. Blocks rarely carry an
    end time, so each block ends where the next begins (last ends at its start),
    mirroring the Teams-text parser.
    """
    blocks = (payload.get("transcript") or {}).get("speaker_blocks") or []
    starts = [_ms_or_s_to_seconds(b.get("start_time", 0)) for b in blocks]
    segments: list[Segment] = []
    for i, block in enumerate(blocks):
        text = (block.get("words") or "").strip()
        if not text:
            continue
        speaker = (block.get("speaker") or {}).get("name") or "Unknown"
        end = starts[i + 1] if i + 1 < len(starts) else starts[i]
        segments.append(
            Segment(speaker=str(speaker), start_seconds=starts[i], end_seconds=end, text=text)
        )
    return tuple(sorted(segments, key=lambda s: (s.start_seconds, s.end_seconds)))


def readai_recap_text(meeting: dict) -> str:
    """Assemble the expanded fields into the free-text recap hint the prompt uses.

    Defensive: every field is optional and shapes are passed through loosely, since
    read.ai is open beta. Produces a plain, sectioned text block (or "" if empty).
    """
    parts: list[str] = []
    summary = (meeting.get("summary") or "").strip()
    if summary:
        parts.append(summary)

    def _bullets(items: list, key: str = "text") -> list[str]:
        out: list[str] = []
        for item in items or []:
            if isinstance(item, dict):
                val = (item.get(key) or "").strip()
            else:
                val = str(item).strip()
            if val:
                out.append(f"- {val}")
        return out

    sections = (
        ("Action items", _bullets(meeting.get("action_items", []))),
        ("Key questions", _bullets(meeting.get("key_questions", []))),
        ("Topics", _bullets(meeting.get("topics", []))),
    )
    for label, bullets in sections:
        if bullets:
            parts.append(f"{label}:\n" + "\n".join(bullets))

    for chapter in meeting.get("chapter_summaries", []) or []:
        if isinstance(chapter, dict):
            title = (chapter.get("title") or "").strip()
            desc = (chapter.get("description") or "").strip()
            if title or desc:
                parts.append(f"{title}\n{desc}".strip())
    return "\n\n".join(parts).strip()


# --- webhook signature (Pro-only path) ---------------------------------------
def verify_readai_signature(secret: str, body: bytes, signature_header: str | None) -> bool:
    """Constant-time HMAC-SHA256 check of the ``X-Read-Signature`` header.

    The header may be the raw hex digest or prefixed (e.g. ``sha256=<hex>``). An
    empty secret or missing header is treated as a failure.
    """
    if not secret or not signature_header:
        return False
    header = signature_header.strip()
    provided = header[7:] if header.startswith("sha256=") else header
    expected = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(provided, expected)


# --- CLI ---------------------------------------------------------------------
def cmd_auth(args) -> int:
    """Walk the OAuth 2.1 (PKCE) flow and cache the tokens."""
    import webbrowser

    client_id, client_secret = register_client()
    verifier, challenge = _pkce_pair()
    url = build_authorize_url(client_id, challenge)
    print("Open this URL, approve access, and copy the authorization code shown:\n")
    print(f"  {url}\n")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    code = input("Paste the authorization code here: ").strip()
    tokens = exchange_code(
        client_id=client_id, client_secret=client_secret, code=code, code_verifier=verifier
    )
    tokens.save()
    print(f"Saved read.ai tokens to {_token_store_path()}")
    return 0


def cmd_list(args) -> int:
    client = ReadAiClient()
    page = client.list_meetings(limit=args.limit)
    for meeting in page.get("data", []):
        mid = meeting.get("id", "?")
        title = meeting.get("title", "(untitled)")
        start = meeting.get("start_time_ms", "")
        print(f"{mid}\t{title}\t{start}")
    return 0


def cmd_fetch(args) -> int:
    client = ReadAiClient()
    meeting_id = args.meeting or client.latest_meeting_id()
    if not meeting_id:
        print("error: no meeting found", flush=True)
        return 1
    transcript = client.get_transcript(meeting_id)
    recap_meeting = client.get_recap(meeting_id)
    segments = readai_turns_to_segments(transcript)
    recap = readai_recap_text(recap_meeting)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Dump the raw transcript (so it can be re-fed) and the recap hint.
    (out_dir / "transcript.json").write_text(
        json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "recap.txt").write_text(recap, encoding="utf-8")
    print(f"Wrote {out_dir}/transcript.json and recap.txt ({len(segments)} segments)")

    if args.minutes:
        from .minutes import build_minutes

        minutes = build_minutes(
            segments=segments,
            notes="",
            title=recap_meeting.get("title", "اجتماع"),
            date="",
            recap=recap,
            backend=args.backend,
            model=args.model or None,
        )
        out = out_dir / "minutes.md"
        out.write_text(minutes + "\n", encoding="utf-8")
        print(f"Wrote {out}")
    return 0


def build_parser():
    import argparse

    parser = argparse.ArgumentParser(
        prog="meeting-minutes-readai",
        description="Fetch transcripts + recaps from read.ai and (optionally) make minutes.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="One-time OAuth login; caches tokens locally")

    p_list = sub.add_parser("list", help="List recent meetings")
    p_list.add_argument("--limit", type=int, default=PAGE_LIMIT)

    p_fetch = sub.add_parser("fetch", help="Fetch a meeting's transcript + recap")
    g = p_fetch.add_mutually_exclusive_group()
    g.add_argument("--meeting", help="Meeting id (default: the latest)")
    g.add_argument("--latest", action="store_true", help="Use the most recent meeting")
    p_fetch.add_argument("--out-dir", default="readai_out")
    p_fetch.add_argument("--minutes", action="store_true", help="Also generate minutes.md")
    p_fetch.add_argument(
        "--backend", default="lmstudio", help="LLM backend for --minutes (default: lmstudio)"
    )
    p_fetch.add_argument("--model", default=None, help="Model id for --minutes")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"auth": cmd_auth, "list": cmd_list, "fetch": cmd_fetch}
    try:
        return handlers[args.command](args)
    except Exception as exc:  # clean message, not a traceback
        print(f"error: {exc}", flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
