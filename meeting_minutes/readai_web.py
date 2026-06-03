"""FastAPI route for read.ai webhooks (the Pro-only push path).

Kept separate from ``web.py`` so the read.ai client/CLI need not import FastAPI,
and so wiring it in is a one-line ``include_router`` — minimal surface area.

Dormant until you set ``READAI_WEBHOOK_SECRET`` (webhooks require a paid read.ai
plan). Without the secret the route returns 503 so it's obviously inactive.
"""

from __future__ import annotations

import json
import os
from collections import deque

from fastapi import APIRouter, Header, HTTPException, Request

from .readai import readai_webhook_to_segments, verify_readai_signature

router = APIRouter()

# Dedup window: read.ai may re-deliver; remember recent request ids in-process.
# A bounded FIFO ring evicts oldest-first (a plain set cleared at a cap would let a
# replay slip through right after the flush).
_MAX_SEEN = 512
_seen_request_ids: deque[str] = deque(maxlen=_MAX_SEEN)


@router.post("/api/webhooks/readai")
async def readai_webhook(
    request: Request,
    x_read_signature: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
) -> dict:
    """Receive a read.ai meeting-report webhook, verify it, and acknowledge fast.

    Verifies the HMAC-SHA256 signature, dedups on the request id, and parses the
    transcript so a follow-up can generate minutes. We intentionally return 2xx
    quickly (read.ai disables a webhook after 25 consecutive non-2xx responses).
    """
    secret = os.environ.get("READAI_WEBHOOK_SECRET", "")
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="read.ai webhook is not configured (set READAI_WEBHOOK_SECRET; "
            "webhooks require a paid read.ai plan)",
        )

    body = await request.body()
    if not verify_readai_signature(secret, body, x_read_signature):
        raise HTTPException(status_code=401, detail="invalid read.ai webhook signature")

    if x_request_id and x_request_id in _seen_request_ids:
        return {"status": "duplicate", "request_id": x_request_id}
    if x_request_id:
        _seen_request_ids.append(x_request_id)  # deque(maxlen) evicts oldest

    # Parse the exact bytes we just verified — not a second await that could, under
    # a streaming middleware, read an empty body and pass an unsigned payload.
    payload = json.loads(body)
    segments = readai_webhook_to_segments(payload)
    # Acknowledge with what we parsed; downstream minute-generation can be wired in
    # here (e.g. enqueue a job) once the user is on a plan that sends webhooks.
    return {
        "status": "received",
        "session_id": payload.get("session_id"),
        "segments": len(segments),
    }
