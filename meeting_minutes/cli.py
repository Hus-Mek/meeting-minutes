"""Command-line entrypoint for the meeting-minutes generator.

Example:
    python -m meeting_minutes.cli \\
        --transcript meeting.json --notes notes.md --out minutes.md \\
        --title "Weekly Sync" --date 2026-06-01
"""

from __future__ import annotations

import argparse
import sys

from .llm import DEFAULT_GROQ_MODEL
from .minutes import generate_minutes_from_files


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
    parser.add_argument("--date", default="", help="Meeting date for the header (e.g. 2026-06-01)")
    parser.add_argument(
        "--backend",
        default="groq",
        choices=["groq", "claude", "ollama"],
        help="LLM backend (default: groq)",
    )
    parser.add_argument("--model", default=DEFAULT_GROQ_MODEL, help="Model id for the backend")
    parser.add_argument(
        "--include-actions",
        action="store_true",
        help="Append a Decisions & Action Items section",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        out = generate_minutes_from_files(
            transcript_path=args.transcript,
            notes_path=args.notes,
            out_path=args.out,
            title=args.title,
            date=args.date,
            backend=args.backend,
            model=args.model,
            include_actions=args.include_actions,
        )
    except Exception as exc:  # surface a clean message, not a traceback
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
