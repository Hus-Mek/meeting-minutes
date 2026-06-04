"""FastAPI web layer: serves the built SPA and a small JSON API over the engine.

The engine is untouched — every request flows through the same in-memory
``build_minutes`` the CLI uses. The LLM client is a dependency so tests inject a
fake and never hit the network. Engine exceptions map to clean HTTP errors.

Run locally: ``python -m meeting_minutes.web`` then open http://localhost:8000
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from . import docx_autofill, docx_render
from .llm import LlmClient, OpenRouterGuardError, TruncatedResponseError, get_client
from .minutes import build_handoff_prompt, build_minutes, parse_speaker_map
from .readai import ReadAiClient, readai_recap_text, readai_turns_to_segments
from .transcript import (
    MAX_TRANSCRIPT_BYTES,
    FieldMap,
    Segment,
    looks_like_json,
    parse_any,
    seconds_to_hms,
    sniff_text_header,
)

# A backend factory: name -> client. Injected so tests can swap in a fake.
ClientFactory = Callable[[str], LlmClient]


def default_client_factory() -> ClientFactory:
    """Default dependency: construct the real backend client by name."""
    return get_client


_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

app = FastAPI(title="Meeting Minutes", docs_url=None, redoc_url=None)

# read.ai webhook receiver (dormant until READAI_WEBHOOK_SECRET is set).
from .readai_web import router as readai_router  # noqa: E402

app.include_router(readai_router)


@app.exception_handler(HTTPException)
async def _http_exception_handler(_request: Request, exc: HTTPException) -> JSONResponse:
    """Return a uniform {"error": ...} body instead of {"detail": ...}."""
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


def _fields(speaker_key: str, start_key: str, end_key: str, text_key: str) -> FieldMap:
    return FieldMap(speaker=speaker_key, start=start_key, end=end_key, text=text_key)


def _decode(raw: bytes) -> str:
    """Validate size and decode bytes — as HTTP errors on failure."""
    if len(raw) > MAX_TRANSCRIPT_BYTES:
        raise HTTPException(status_code=413, detail="transcript file is too large")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="transcript must be UTF-8 text")


def _read_segments(raw: bytes, fields: FieldMap) -> tuple[Segment, ...]:
    """Decode + auto-detect (Teams text or diarized JSON) into Segments."""
    try:
        return parse_any(_decode(raw), fields=fields)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/inspect")
async def inspect(
    transcript: UploadFile = File(...),
    speaker_key: str = Form("speaker"),
    start_key: str = Form("start"),
    end_key: str = Form("end"),
    text_key: str = Form("text"),
) -> dict:
    """Parse only — power the pre-generation preview (counts, speakers, duration).

    For Teams text transcripts, also sniff a detected title/date to prefill the form.
    """
    raw = await transcript.read()
    text = _decode(raw)
    segments = _read_segments(raw, _fields(speaker_key, start_key, end_key, text_key))
    speakers = sorted({s.speaker for s in segments})
    if segments:
        duration = max(s.end_seconds for s in segments) - min(s.start_seconds for s in segments)
        duration_hms = seconds_to_hms(max(0.0, duration))
    else:
        duration_hms = "00:00:00"
    detected = {"title": "", "date": ""} if looks_like_json(text) else sniff_text_header(text)
    return {
        "segment_count": len(segments),
        "speakers": speakers,
        "duration": duration_hms,
        "detected": detected,
    }


@app.post("/api/minutes")
async def api_minutes(
    transcript: UploadFile = File(...),
    notes: str = Form(""),
    title: str = Form("Meeting"),
    date: str = Form(""),
    time: str = Form(""),
    location: str = Form(""),
    attendees: str = Form(""),
    recap: str = Form(""),
    backend: str = Form("groq"),
    model: str = Form(""),
    speaker_key: str = Form("speaker"),
    start_key: str = Form("start"),
    end_key: str = Form("end"),
    text_key: str = Form("text"),
    speaker_map: str = Form(""),
    make_client: ClientFactory = Depends(default_client_factory),
) -> dict:
    """Generate minutes from an uploaded transcript + notes."""
    raw = await transcript.read()
    segments = _read_segments(raw, _fields(speaker_key, start_key, end_key, text_key))
    try:
        smap = parse_speaker_map(speaker_map)
        if backend == "handoff":
            # No LLM call: return the assembled prompt for an agent (Cowork / Claude
            # Code) to write the محضر on its subscription. Pattern-2 handoff in the GUI.
            minutes = build_handoff_prompt(
                segments=segments,
                notes=notes,
                title=title,
                date=date,
                time=time,
                location=location,
                attendees=attendees,
                recap=recap,
                speaker_map=smap or None,
            )
            return {"minutes": minutes, "meta": {"backend": "handoff", "segments": len(segments)}}
        client = make_client(backend)  # raises ValueError(unknown)/NotImplementedError/RuntimeError
        minutes = await run_in_threadpool(
            build_minutes,
            segments=segments,
            notes=notes,
            title=title,
            date=date,
            time=time,
            location=location,
            attendees=attendees,
            recap=recap,
            speaker_map=smap or None,
            backend=backend,
            model=model or None,
            client=client,
        )
    except OpenRouterGuardError as exc:
        raise HTTPException(status_code=403, detail=str(exc))
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except TruncatedResponseError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    except RuntimeError as exc:
        msg = str(exc)
        status = 500 if "API_KEY" in msg else 502
        raise HTTPException(status_code=status, detail=msg)
    return {"minutes": minutes, "meta": {"backend": backend, "segments": len(segments)}}


# .docx with embedded fonts + a logo is comfortably under this; reject pathological uploads.
MAX_TEMPLATE_BYTES = 25 * 1024 * 1024
_DOCX_MEDIA = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def _content_disposition(name: str, ext: str) -> str:
    """attachment header with an ASCII fallback + RFC 5987 UTF-8 name (Arabic titles)."""
    ascii_name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "minutes"
    # safe="" so '/' and other reserved chars are percent-encoded (valid RFC 5987).
    return f"attachment; filename=\"{ascii_name}.{ext}\"; filename*=UTF-8''{quote(f'{name}.{ext}', safe='')}"


@app.post("/api/minutes/docx")
async def api_minutes_docx(
    minutes: str = Form(...),
    template: UploadFile | None = File(None),
    template_id: str = Form(""),
    format: str = Form("docx"),
    filename: str = Form("minutes"),
) -> Response:
    """Render محضر Markdown into a .docx template and return the file.

    The template is either an uploaded .docx (the user's own, kept only for this
    request) or the bundled synthetic one. ``format=pdf`` converts via headless
    LibreOffice. No LLM/network is touched — the minutes Markdown is already written.
    """
    fmt = format.lower().strip()
    if fmt not in ("docx", "pdf"):
        raise HTTPException(status_code=400, detail="format must be 'docx' or 'pdf'")

    template_bytes: bytes | None = None
    if template is not None:
        template_bytes = await template.read()
        if len(template_bytes) > MAX_TEMPLATE_BYTES:
            raise HTTPException(status_code=413, detail="template file is too large")
        template_bytes = template_bytes or None  # treat an empty upload as "no template"

    def _render() -> bytes:
        if template_bytes:
            # The user's OWN untouched .docx → auto-detect its tables and fill them
            # exactly (no Jinja tagging needed); the output IS their document.
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as tf:
                tf.write(template_bytes)
                tpath = tf.name
            try:
                rendered = docx_autofill.autofill_docx(minutes, tpath)
            finally:
                os.unlink(tpath)
        else:
            rendered = docx_render.render_docx(minutes)  # bundled synthetic template
        return docx_render.docx_to_pdf(rendered) if fmt == "pdf" else rendered

    try:
        data = await run_in_threadpool(_render)
    except ValueError as exc:  # malformed template / bad input
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:  # LibreOffice missing or PDF conversion failed
        raise HTTPException(status_code=503, detail=str(exc))

    media = "application/pdf" if fmt == "pdf" else _DOCX_MEDIA
    headers = {"Content-Disposition": _content_disposition(filename or "minutes", fmt)}
    return Response(content=data, media_type=media, headers=headers)


@app.post("/api/readai/fetch")
async def readai_fetch(
    meeting_id: str = Form(...), access_token: str | None = Form(None)
) -> dict[str, Any]:
    """Fetch transcript and recap from read.ai by meeting ID (using saved tokens or provided access_token).

    If `access_token` is provided, it updates the stored token.
    Returns {"transcript": {...}, "segments": [...], "recap": "..."} or error.
    """

    async def _fetch() -> dict[str, Any]:
        try:
            client = ReadAiClient()
            if access_token:
                # TODO: update token storage if new access_token provided
                pass

            transcript = client.get_transcript(meeting_id)
            segments = readai_turns_to_segments(transcript)
            recap_meeting = client.get_recap(meeting_id)
            recap = readai_recap_text(recap_meeting)

            return {
                "transcript": transcript,
                "segments": [
                    {
                        "speaker": s.speaker,
                        "start": s.start_seconds,
                        "end": s.end_seconds,
                        "text": s.text,
                    }
                    for s in segments
                ],
                "recap": recap,
            }
        except RuntimeError as exc:
            raise ValueError(f"read.ai API error: {exc}")
        except Exception as exc:
            raise ValueError(f"read.ai fetch failed: {exc}")

    try:
        result = await run_in_threadpool(_fetch)
        return result
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


@app.get("/api/claude/status")
async def claude_status() -> dict[str, object]:
    """Startup probe: whether a working Claude Code CLI is available, so the UI can
    open the setup guide on load instead of waiting until the user hits Generate."""
    from .llm import claude_code_available

    available, path = await run_in_threadpool(claude_code_available)
    return {"available": available, "path": path}


@app.get("/api/update/check")
async def update_check() -> dict[str, object]:
    """Report whether a newer release is published on GitHub (public repo).

    Backs the startup update banner. Fails SILENTLY in the checker itself, so this
    always returns 200 with ``update_available=False`` on any network/parse error —
    a transient GitHub hiccup must never surface as an app error.
    """
    from .update import check_for_update

    info = await run_in_threadpool(check_for_update)
    return info.as_dict()


@app.post("/api/claude/login")
async def claude_login() -> dict[str, str]:
    """Open an interactive Claude Code session for the one-time browser login.

    Backs the setup guide's "Log in to Claude" button. The app runs locally, so this
    spawns a console/window on the user's own machine via the shared launcher.
    """
    from .llm import launch_claude_login

    try:
        await run_in_threadpool(launch_claude_login)
    except RuntimeError as exc:  # no claude found to log in to
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:  # spawning the login window failed
        raise HTTPException(status_code=500, detail=f"Couldn't start the Claude login: {exc}")
    return {"status": "started"}


# Serve the built SPA last so /api/* takes precedence. Graceful message if unbuilt.
if _DIST.is_dir():
    app.mount("/", StaticFiles(directory=str(_DIST), html=True), name="spa")
else:

    @app.get("/", response_class=HTMLResponse)
    def _needs_build() -> str:
        return (
            "<h1>Frontend not built</h1>"
            "<p>Run <code>cd frontend &amp;&amp; npm install &amp;&amp; npm run build</code>, "
            "then restart.</p>"
        )


def main() -> None:
    import os

    import uvicorn

    # Bind to all interfaces by default so the app is reachable on the LAN; override
    # with HOST/PORT. NOTE: 0.0.0.0 exposes the server to your network — there is no
    # auth, and your GROQ_API_KEY funds every request. Use 127.0.0.1 for local-only.
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("meeting_minutes.web:app", host=host, port=port)


if __name__ == "__main__":
    main()
