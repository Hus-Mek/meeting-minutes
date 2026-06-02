"""Orchestration: turn a transcript + notes into topic-by-topic minutes.

Routing is **model-aware**: it estimates the *full assembled prompt* (system +
notes + transcript, with a safety multiplier) against the chosen model's real
input budget. If it fits, one call; otherwise map-reduce — and the map-reduce
path is bounded at every level (windows are split to fit, and the synthesis step
is folded hierarchically) so it can never re-overflow the context it exists to
protect.

The LLM is injected (anything matching ``llm.LlmClient``), so tests run with a
fake and never touch the network.
"""

from __future__ import annotations

from pathlib import Path

from . import prompt
from .llm import (
    LlmClient,
    default_model_for,
    get_client,
    max_input_tokens,
)
from .transcript import (
    FieldMap,
    Segment,
    estimate_tokens,
    format_for_prompt,
    load_transcript,
    seconds_to_hms,
)

# chars/4 is optimistic on timestamped/diarized text; pad the estimate.
SAFETY_MULTIPLIER = 1.15

# Target wall-clock duration per map-reduce window (further split if it overflows).
WINDOW_SECONDS = 600.0


def _budget_tokens(text: str) -> int:
    """Padded token estimate used for all routing/fit decisions."""
    return int(estimate_tokens(text) * SAFETY_MULTIPLIER)


def chunk_by_window(
    segments: tuple[Segment, ...], *, window_seconds: float = WINDOW_SECONDS
) -> tuple[tuple[Segment, ...], ...]:
    """Group consecutive segments into fixed-duration windows by start time.

    Whole utterances are never split here; a window collects every segment whose
    start falls in ``[k*window, (k+1)*window)`` relative to the first segment.
    Segments are pre-sorted at load time, so the index is non-decreasing.
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


def _split_to_budget(
    window: tuple[Segment, ...], *, notes: str, budget: int
) -> list[tuple[Segment, ...]]:
    """Recursively halve a window on utterance boundaries until each fits the budget."""
    overhead = prompt.build_window_user(notes=notes, transcript=format_for_prompt(window))
    if len(window) <= 1 or _budget_tokens(prompt.WINDOW_SYSTEM_PROMPT + overhead) <= budget:
        return [window]
    mid = len(window) // 2
    left = _split_to_budget(window[:mid], notes=notes, budget=budget)
    right = _split_to_budget(window[mid:], notes=notes, budget=budget)
    return left + right


def _summarize_windows(
    client: LlmClient, *, segments: tuple[Segment, ...], notes: str, model: str, budget: int
) -> list[str]:
    """Map step: one labelled summary per (possibly sub-split) window."""
    summaries: list[str] = []
    for window in chunk_by_window(segments):
        for sub in _split_to_budget(window, notes=notes, budget=budget):
            label = (
                f"[{seconds_to_hms(sub[0].start_seconds)}–{seconds_to_hms(sub[-1].end_seconds)}]"
            )
            user = prompt.build_window_user(notes=notes, transcript=format_for_prompt(sub))
            summary = client.generate(prompt.WINDOW_SYSTEM_PROMPT, user, model=model).strip()
            summaries.append(f"{label}\n{summary}")
    return summaries


def _batch_to_budget(summaries: list[str], *, notes: str, budget: int) -> list[list[str]]:
    """Greedily group consecutive summaries so each group fits the budget."""
    batches: list[list[str]] = []
    current: list[str] = []
    for item in summaries:
        trial = current + [item]
        joined = prompt.build_window_user(notes=notes, transcript="\n\n".join(trial))
        if current and _budget_tokens(prompt.WINDOW_SYSTEM_PROMPT + joined) > budget:
            batches.append(current)
            current = [item]
        else:
            current = trial
    if current:
        batches.append(current)
    return batches


def _fold_summaries(
    client: LlmClient,
    summaries: list[str],
    *,
    notes: str,
    synthesis_system: str,
    model: str,
    budget: int,
) -> list[str]:
    """Reduce step guard: fold summaries-of-summaries until they fit one synthesis call."""
    while len(summaries) > 1:
        joined = "\n\n".join(summaries)
        if _budget_tokens(synthesis_system + notes + joined) <= budget:
            return summaries
        batches = _batch_to_budget(summaries, notes=notes, budget=budget)
        if len(batches) >= len(summaries):
            raise RuntimeError(
                "map-reduce cannot fit the segment summaries into the synthesis budget; "
                "the meeting is too large for this model's context window."
            )
        summaries = [
            client.generate(
                prompt.WINDOW_SYSTEM_PROMPT,
                prompt.build_window_user(notes=notes, transcript="\n\n".join(batch)),
                model=model,
            ).strip()
            for batch in batches
        ]
    return summaries


def _assert_well_formed(minutes: str) -> None:
    """Post-condition: refuse to write empty or heading-less output."""
    if not minutes.strip():
        raise RuntimeError("the model returned empty minutes; nothing was written")
    if "##" not in minutes:
        raise RuntimeError(
            "generated minutes contain no topic headings (`## ...`); output looks malformed"
        )


def _generate_map_reduce(
    client: LlmClient,
    *,
    notes: str,
    segments: tuple[Segment, ...],
    title: str,
    date: str,
    model: str,
    include_actions: bool,
    budget: int,
) -> str:
    summaries = _summarize_windows(
        client, segments=segments, notes=notes, model=model, budget=budget
    )
    system = prompt.build_system_prompt(
        title=title, date=date, include_actions=include_actions, for_synthesis=True
    )
    summaries = _fold_summaries(
        client, summaries, notes=notes, synthesis_system=system, model=model, budget=budget
    )
    user = prompt.build_synthesis_prompt(notes=notes, summaries="\n\n".join(summaries))
    return client.generate(system, user, model=model).strip()


def generate_minutes(
    *,
    segments: tuple[Segment, ...],
    notes: str,
    title: str,
    date: str,
    client: LlmClient,
    model: str,
    include_actions: bool = True,
    input_token_budget: int | None = None,
) -> str:
    """Produce minutes markdown, choosing single-pass vs map-reduce by real budget."""
    if not segments:
        raise ValueError(
            "transcript contains no segments — check the file and the field mapping "
            "(--speaker-key/--start-key/--end-key/--text-key)"
        )
    budget = input_token_budget if input_token_budget is not None else max_input_tokens(model)

    transcript_text = format_for_prompt(segments)  # computed once, reused below
    system = prompt.build_system_prompt(title=title, date=date, include_actions=include_actions)
    user = prompt.build_user_prompt(notes=notes, transcript=transcript_text)

    if _budget_tokens(system + user) <= budget:
        minutes = client.generate(system, user, model=model).strip()
    else:
        minutes = _generate_map_reduce(
            client,
            notes=notes,
            segments=segments,
            title=title,
            date=date,
            model=model,
            include_actions=include_actions,
            budget=budget,
        )
    _assert_well_formed(minutes)
    return minutes


def _apply_speaker_map(
    segments: tuple[Segment, ...], speaker_map: dict[str, str]
) -> tuple[Segment, ...]:
    """Rename anonymous diarization labels (e.g. SPEAKER_00 -> Alice). Immutable."""
    return tuple(
        seg
        if seg.speaker not in speaker_map
        else Segment(speaker_map[seg.speaker], seg.start_seconds, seg.end_seconds, seg.text)
        for seg in segments
    )


def parse_speaker_map(spec: str | None) -> dict[str, str]:
    """Parse 'SPEAKER_00=Alice,SPEAKER_01=Bob' into a rename map.

    Shared by the CLI and the web layer so anonymous-label renaming has one home.
    """
    if not spec:
        return {}
    mapping: dict[str, str] = {}
    for pair in spec.split(","):
        pair = pair.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"speaker-map entry {pair!r} must be LABEL=Name")
        label, name = pair.split("=", 1)
        mapping[label.strip()] = name.strip()
    return mapping


def build_minutes(
    *,
    segments: tuple[Segment, ...],
    notes: str,
    title: str,
    date: str,
    speaker_map: dict[str, str] | None = None,
    backend: str = "groq",
    model: str | None = None,
    include_actions: bool = True,
    client: LlmClient | None = None,
) -> str:
    """In-memory core: rename speakers, resolve model/client, generate minutes.

    Shared by the file-based CLI wrapper and the web layer — neither touches the
    filesystem here, so the same code path serves uploads and local files.
    """
    if speaker_map:
        segments = _apply_speaker_map(segments, speaker_map)
    resolved_model = model or default_model_for(backend)
    llm = client or get_client(backend)
    return generate_minutes(
        segments=segments,
        notes=notes,
        title=title,
        date=date,
        client=llm,
        model=resolved_model,
        include_actions=include_actions,
    )


def generate_minutes_from_files(
    *,
    transcript_path: str | Path,
    notes_path: str | Path,
    out_path: str | Path,
    title: str,
    date: str,
    backend: str = "groq",
    model: str | None = None,
    include_actions: bool = True,
    fields: FieldMap | None = None,
    speaker_map: dict[str, str] | None = None,
    client: LlmClient | None = None,
) -> Path:
    """End-to-end IO wrapper: read inputs, generate minutes, write the file."""
    segments = load_transcript(transcript_path, fields=fields)
    notes = Path(notes_path).read_text(encoding="utf-8")
    minutes = build_minutes(
        segments=segments,
        notes=notes,
        title=title,
        date=date,
        speaker_map=speaker_map,
        backend=backend,
        model=model,
        include_actions=include_actions,
        client=client,
    )
    out = Path(out_path)
    out.write_text(minutes + "\n", encoding="utf-8")
    return out
