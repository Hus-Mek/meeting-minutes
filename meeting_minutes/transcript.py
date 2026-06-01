"""Load and format diarized meeting transcripts.

The input is a diarized JSON transcript: a list of segments, each carrying a
speaker label, a start/end timestamp (seconds), and the spoken text. Field names
vary between diarization tools, so the loader is field-configurable — adapt the
real schema in one place (``FieldMap``) without touching any logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Default JSON keys. Override via load_transcript(..., fields=FieldMap(...)) when
# your diarizer uses different names (e.g. "spk", "begin", "stop", "content").
DEFAULT_FIELDS = ("speaker", "start", "end", "text")

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
    return Segment(speaker=speaker, start_seconds=start, end_seconds=end, text=text.strip())


def parse_transcript(data: list, *, fields: FieldMap | None = None) -> tuple[Segment, ...]:
    """Parse an already-loaded list of raw segment dicts into Segments."""
    field_map = fields or FieldMap()
    if not isinstance(data, list):
        raise ValueError("transcript JSON must be a list of segment objects")
    return tuple(_coerce_segment(raw, field_map, i) for i, raw in enumerate(data))


def load_transcript(path: str | Path, *, fields: FieldMap | None = None) -> tuple[Segment, ...]:
    """Load a diarized transcript JSON file into an immutable tuple of Segments."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"transcript file {path} is not valid JSON: {exc}") from exc
    return parse_transcript(data, fields=fields)


def format_for_prompt(segments: tuple[Segment, ...]) -> str:
    """Render segments as ``[HH:MM:SS] Speaker: text`` lines for the model."""
    return "\n".join(
        f"[{seconds_to_hms(s.start_seconds)}] {s.speaker}: {s.text}" for s in segments
    )


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) used to pick single-pass vs map-reduce."""
    return len(text) // 4
