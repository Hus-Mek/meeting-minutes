"""FastAPI web layer: serves the built SPA and a small JSON API over the engine.

The engine is untouched — every request flows through the same in-memory
``build_minutes`` the CLI uses. The LLM client is a dependency so tests inject a
fake and never hit the network. Engine exceptions map to clean HTTP errors.

Run locally: ``python -m meeting_minutes.web`` then open http://localhost:8000
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request

from .llm import LlmClient, OpenRouterGuardError, TruncatedResponseError, get_client
from .minutes import build_minutes, parse_speaker_map
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
        status = 500 if "GROQ_API_KEY" in msg else 502
        raise HTTPException(status_code=status, detail=msg)
    return {"minutes": minutes, "meta": {"backend": backend, "segments": len(segments)}}


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
