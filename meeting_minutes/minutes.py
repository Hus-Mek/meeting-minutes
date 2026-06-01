"""Orchestration: turn a transcript + notes into topic-by-topic minutes.

Single-pass by default (a typical meeting fits one context). For very long
transcripts it falls back to map-reduce: summarise ~10-minute windows, then
synthesise the windows into final minutes anchored to the notes.

The LLM is injected (anything matching ``llm.LlmClient``), so tests run with a
fake and never touch the network.
"""

from __future__ import annotations

from pathlib import Path

from . import prompt
from .llm import DEFAULT_GROQ_MODEL, LlmClient, get_client
from .transcript import (
    Segment,
    estimate_tokens,
    format_for_prompt,
    load_transcript,
)

# Above this estimated token count for the formatted transcript, switch to
# map-reduce instead of a single call.
SINGLE_PASS_TOKEN_LIMIT = 150_000

# Target wall-clock duration per map-reduce window.
WINDOW_SECONDS = 600.0


def chunk_by_window(
    segments: tuple[Segment, ...], *, window_seconds: float = WINDOW_SECONDS
) -> tuple[tuple[Segment, ...], ...]:
    """Group consecutive segments into fixed-duration windows by start time.

    Speaker-aware in that whole utterances are never split; a window simply
    collects every segment whose start falls in ``[k*window, (k+1)*window)``
    relative to the first segment.
    """
    if not segments:
        return ()
    base = segments[0].start_seconds
    windows: list[list[Segment]] = []
    current_index = -1
    for seg in segments:
        idx = int((seg.start_seconds - base) // window_seconds)
        if idx != current_index:
            windows.append([])
            current_index = idx
        windows[-1].append(seg)
    return tuple(tuple(w) for w in windows)


def _generate_single_pass(
    client: LlmClient,
    *,
    notes: str,
    segments: tuple[Segment, ...],
    title: str,
    date: str,
    model: str,
    include_actions: bool,
) -> str:
    system = prompt.build_system_prompt(title=title, date=date, include_actions=include_actions)
    user = prompt.build_user_prompt(notes=notes, transcript=format_for_prompt(segments))
    return client.generate(system, user, model=model).strip()


def _generate_map_reduce(
    client: LlmClient,
    *,
    notes: str,
    segments: tuple[Segment, ...],
    title: str,
    date: str,
    model: str,
    include_actions: bool,
) -> str:
    summaries: list[str] = []
    for window in chunk_by_window(segments):
        window_user = format_for_prompt(window)
        summary = client.generate(prompt.WINDOW_SYSTEM_PROMPT, window_user, model=model)
        summaries.append(summary.strip())

    system = prompt.build_system_prompt(title=title, date=date, include_actions=include_actions)
    user = prompt.build_synthesis_prompt(notes=notes, summaries="\n\n".join(summaries))
    return client.generate(system, user, model=model).strip()


def generate_minutes(
    *,
    segments: tuple[Segment, ...],
    notes: str,
    title: str,
    date: str,
    client: LlmClient,
    model: str = DEFAULT_GROQ_MODEL,
    include_actions: bool = False,
    single_pass_token_limit: int = SINGLE_PASS_TOKEN_LIMIT,
) -> str:
    """Produce minutes markdown, choosing single-pass vs map-reduce by size."""
    transcript_text = format_for_prompt(segments)
    kwargs = dict(
        notes=notes,
        segments=segments,
        title=title,
        date=date,
        model=model,
        include_actions=include_actions,
    )
    if estimate_tokens(transcript_text) <= single_pass_token_limit:
        return _generate_single_pass(client, **kwargs)
    return _generate_map_reduce(client, **kwargs)


def generate_minutes_from_files(
    *,
    transcript_path: str | Path,
    notes_path: str | Path,
    out_path: str | Path,
    title: str,
    date: str,
    backend: str = "groq",
    model: str = DEFAULT_GROQ_MODEL,
    include_actions: bool = False,
    client: LlmClient | None = None,
) -> Path:
    """End-to-end IO wrapper: read inputs, generate minutes, write the file."""
    segments = load_transcript(transcript_path)
    notes = Path(notes_path).read_text(encoding="utf-8")
    llm = client or get_client(backend)
    minutes = generate_minutes(
        segments=segments,
        notes=notes,
        title=title,
        date=date,
        client=llm,
        model=model,
        include_actions=include_actions,
    )
    out = Path(out_path)
    out.write_text(minutes + "\n", encoding="utf-8")
    return out
