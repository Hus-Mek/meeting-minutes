"""Load meeting transcripts in two shapes, auto-detected.

1. **Diarized JSON** — a list of segments with speaker/start/end/text. Field names
   vary between tools, so the loader is field-configurable via ``FieldMap``.
2. **Teams/Zoom text export** — ``M:SS - Speaker`` headers followed by the spoken
   text (the common meeting-recording export). Parsed by ``parse_text_transcript``.

``parse_any`` sniffs the content and routes to the right parser.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

# Default JSON keys. Override via load_transcript(..., fields=FieldMap(...)) when
# your diarizer uses different names (e.g. "spk", "begin", "stop", "content").
DEFAULT_FIELDS = ("speaker", "start", "end", "text")

# Refuse absurdly large transcript files before read_text() turns them into an OOM.
MAX_TRANSCRIPT_BYTES = 50 * 1024 * 1024  # 50 MB

# Insert a pause marker between consecutive utterances separated by a long gap —
# preserves the topic-shift / silence signal the scribe model can use.
LONG_PAUSE_SECONDS = 30.0

_SECONDS_PER_HOUR = 3600
_SECONDS_PER_MINUTE = 60


@dataclass(frozen=True)
class FieldMap:
    """Maps logical fields to the keys used in a particular transcript JSON."""

    speaker: str = "speaker"
    start: str = "start"
    end: str = "end"
    text: str = "text"


@dataclass(frozen=True)
class Segment:
    """One diarized utterance. Immutable by design."""

    speaker: str
    start_seconds: float
    end_seconds: float
    text: str


def seconds_to_hms(seconds: float) -> str:
    """Render seconds as ``HH:MM:SS`` (hours grow unbounded for long meetings)."""
    if not math.isfinite(seconds):
        raise ValueError(f"seconds must be a finite number, got {seconds}")
    if seconds < 0:
        raise ValueError(f"seconds must be non-negative, got {seconds}")
    total = int(seconds)
    hours = total // _SECONDS_PER_HOUR
    minutes = (total % _SECONDS_PER_HOUR) // _SECONDS_PER_MINUTE
    secs = total % _SECONDS_PER_MINUTE
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _coerce_segment(raw: dict, fields: FieldMap, index: int) -> Segment:
    """Build a Segment from one raw JSON object, failing fast on bad data."""
    try:
        speaker = str(raw[fields.speaker])
        start = float(raw[fields.start])
        end = float(raw[fields.end])
        text = str(raw[fields.text])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"transcript segment #{index} is malformed or missing a mapped field "
            f"({fields}): {exc}"
        ) from exc
    if not math.isfinite(start) or not math.isfinite(end):
        raise ValueError(f"transcript segment #{index} has a non-finite timestamp")
    return Segment(speaker=speaker, start_seconds=start, end_seconds=end, text=text.strip())


def parse_transcript(data: list, *, fields: FieldMap | None = None) -> tuple[Segment, ...]:
    """Parse raw segment dicts into Segments, sorted chronologically.

    Diarizers and segment merges routinely emit slightly out-of-order or
    overlapping segments, so we sort by (start, end) at load time — every
    downstream stage (windowing, synthesis "chronological order") relies on it.
    """
    field_map = fields or FieldMap()
    if not isinstance(data, list):
        raise ValueError("transcript JSON must be a list of segment objects")
    segments = tuple(_coerce_segment(raw, field_map, i) for i, raw in enumerate(data))
    return tuple(sorted(segments, key=lambda s: (s.start_seconds, s.end_seconds)))


# A cue header in a Teams/Zoom text export: "1:57 - Speaker Name" / "01:02:03 — Name".
_CUE_RE = re.compile(r"^\s*(\d{1,2}(?::\d{2}){1,2})\s*[-–—]\s*(.+?)\s*$")


def _stamp_to_seconds(stamp: str) -> float:
    """Convert ``M:SS`` or ``H:MM:SS`` to seconds."""
    parts = [int(p) for p in stamp.split(":")]
    if len(parts) == 2:
        return float(parts[0] * 60 + parts[1])
    return float(parts[0] * 3600 + parts[1] * 60 + parts[2])


def looks_like_json(raw: str) -> bool:
    """Cheap sniff: a JSON transcript starts with ``[`` or ``{``."""
    head = raw.lstrip()[:1]
    return head in ("[", "{")


def sniff_text_header(raw: str) -> dict[str, str]:
    """Best-effort title/date from the two lines above the first cue (Teams export)."""
    title, date = "", ""
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _CUE_RE.match(stripped):
            break
        if not title:
            title = stripped
        elif not date:
            date = stripped
    return {"title": title, "date": date}


def parse_text_transcript(raw: str) -> tuple[Segment, ...]:
    """Parse a Teams/Zoom ``M:SS - Speaker`` text export into Segments.

    Lines before the first cue (title, date) are ignored. Each cue's end time is
    the next cue's start (the last cue ends where it starts).
    """
    cues: list[list] = []  # [start_seconds, speaker, [text lines]]
    for line in raw.splitlines():
        match = _CUE_RE.match(line)
        if match:
            cues.append([_stamp_to_seconds(match.group(1)), match.group(2).strip(), []])
        elif cues and line.strip():
            cues[-1][2].append(line.strip())
    if not cues:
        raise ValueError(
            "no 'M:SS - Speaker' cues found — is this a Teams/Zoom text transcript?"
        )
    segments: list[Segment] = []
    for i, (start, speaker, text_lines) in enumerate(cues):
        end = cues[i + 1][0] if i + 1 < len(cues) else start
        segments.append(
            Segment(
                speaker=speaker,
                start_seconds=float(start),
                end_seconds=float(end),
                text=" ".join(text_lines).strip(),
            )
        )
    return tuple(segments)


def parse_any(raw: str, *, fields: FieldMap | None = None) -> tuple[Segment, ...]:
    """Auto-detect JSON vs Teams text and parse into Segments."""
    if looks_like_json(raw):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"transcript looks like JSON but is not valid JSON: {exc}") from exc
        return parse_transcript(data, fields=fields)
    return parse_text_transcript(raw)


def load_transcript(path: str | Path, *, fields: FieldMap | None = None) -> tuple[Segment, ...]:
    """Load a transcript file (diarized JSON or Teams text) into Segments."""
    p = Path(path)
    size = p.stat().st_size
    if size > MAX_TRANSCRIPT_BYTES:
        raise ValueError(
            f"transcript file {path} is {size} bytes, over the "
            f"{MAX_TRANSCRIPT_BYTES}-byte ceiling; refusing to load"
        )
    return parse_any(p.read_text(encoding="utf-8"), fields=fields)


def format_for_prompt(segments: tuple[Segment, ...]) -> str:
    """Render segments as ``[HH:MM:SS–HH:MM:SS] Speaker: text`` lines for the model.

    The time *range* preserves utterance duration (a salience cue), and a pause
    marker is inserted when speakers fall silent for a while.
    """
    lines: list[str] = []
    prev_end: float | None = None
    for s in segments:
        if prev_end is not None and s.start_seconds - prev_end >= LONG_PAUSE_SECONDS:
            gap = seconds_to_hms(s.start_seconds - prev_end)
            lines.append(f"[... {gap} pause ...]")
        start = seconds_to_hms(s.start_seconds)
        end = seconds_to_hms(s.end_seconds)
        lines.append(f"[{start}–{end}] {s.speaker}: {s.text}")
        prev_end = s.end_seconds
    return "\n".join(lines)


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token). Callers add a safety multiplier."""
    return len(text) // 4
