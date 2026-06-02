"""Command-line entrypoint for the meeting-minutes generator.

Example:
    python -m meeting_minutes.cli \\
        --transcript meeting.json --notes notes.md --out minutes.md \\
        --title "Weekly Sync" --date 2026-06-01
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys

from .transcript import FieldMap
from .minutes import generate_minutes_from_files, parse_speaker_map as _parse_speaker_map


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meeting-minutes",
        description="Generate topic-by-topic meeting minutes from diarized "
        "transcript JSON plus human notes.",
    )
    parser.add_argument("--transcript", required=True, help="Path to diarized transcript JSON")
    parser.add_argument("--notes", required=True, help="Path to human notes (md/txt)")
    parser.add_argument("--out", required=True, help="Path to write the minutes markdown")
    parser.add_argument("--title", default="Meeting", help="Meeting title for the header")
    parser.add_argument(
        "--date",
        default=_dt.date.today().isoformat(),
        help="Meeting date for the header (default: today)",
    )
    parser.add_argument(
        "--backend",
        default="groq",
        choices=["groq", "claude", "ollama"],
        help="LLM backend (default: groq; claude/ollama not implemented yet)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model id (default: the chosen backend's default model)",
    )
    parser.add_argument(
        "--no-actions",
        action="store_true",
        help="Suppress the Decisions & Action Items section (included by default)",
    )
    # Field mapping for non-default diarizer schemas (no need to edit source).
    parser.add_argument("--speaker-key", default="speaker", help="JSON key for the speaker label")
    parser.add_argument("--start-key", default="start", help="JSON key for the start timestamp")
    parser.add_argument("--end-key", default="end", help="JSON key for the end timestamp")
    parser.add_argument("--text-key", default="text", help="JSON key for the utterance text")
    parser.add_argument(
        "--speaker-map",
        default=None,
        help="Rename anonymous labels, e.g. 'SPEAKER_00=Alice,SPEAKER_01=Bob'",
    )
    parser.add_argument("--debug", action="store_true", help="Show full tracebacks on error")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    fields = FieldMap(
        speaker=args.speaker_key,
        start=args.start_key,
        end=args.end_key,
        text=args.text_key,
    )
    try:
        speaker_map = _parse_speaker_map(args.speaker_map)
        out = generate_minutes_from_files(
            transcript_path=args.transcript,
            notes_path=args.notes,
            out_path=args.out,
            title=args.title,
            date=args.date,
            backend=args.backend,
            model=args.model,
            include_actions=not args.no_actions,
            fields=fields,
            speaker_map=speaker_map,
        )
    except Exception as exc:  # surface a clean message, not a traceback
        if args.debug:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
