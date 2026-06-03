"""Command-line entrypoint for the meeting-minutes generator.

Example:
    python -m meeting_minutes.cli \\
        --transcript meeting.txt --notes notes.md --out minutes.md \\
        --title "اجتماع المتابعة" --date 11/5/2026 --location "عن بعد"
"""

from __future__ import annotations

import argparse
import datetime as _dt
import sys
from pathlib import Path

from .transcript import FieldMap
from .minutes import (
    emit_prompt_from_files,
    generate_minutes_from_files,
    parse_speaker_map as _parse_speaker_map,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="meeting-minutes",
        description="Generate formal Arabic meeting minutes (محضر اجتماع) from a "
        "transcript (Teams text or diarized JSON) plus notes.",
    )
    parser.add_argument("--transcript", required=True, help="Transcript file (Teams text or JSON)")
    parser.add_argument("--notes", required=True, help="Path to notes (md/txt); may be empty")
    parser.add_argument("--out", required=True, help="Path to write the minutes markdown")
    parser.add_argument("--title", default="Meeting", help="Meeting title for the header")
    parser.add_argument(
        "--date",
        default=_dt.date.today().isoformat(),
        help="Meeting date for the header (default: today)",
    )
    parser.add_argument("--time", default="", help="Meeting time for the header, e.g. '11:30–12:30'")
    parser.add_argument("--location", default="", help="Meeting location, e.g. 'عن بعد'")
    parser.add_argument(
        "--attendees",
        default="",
        help="Roster, one 'Name — Organization' per line (or use --attendees-file)",
    )
    parser.add_argument("--attendees-file", default=None, help="Path to a roster file")
    parser.add_argument(
        "--recap",
        default="",
        help="Optional read.ai recap text (partial/approximate; or use --recap-file)",
    )
    parser.add_argument("--recap-file", default=None, help="Path to a read.ai recap file")
    parser.add_argument(
        "--backend",
        default="groq",
        choices=["groq", "openrouter", "anthropic", "claude-code", "ollama", "lmstudio"],
        help="LLM backend (default: groq; claude-code = local Claude Code CLI on your "
        "subscription, no API key; anthropic = Claude via ANTHROPIC_API_KEY; openrouter "
        "= Sonnet via OPENROUTER_API_KEY; ollama/lmstudio = local server)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Model id (default: the chosen backend's default model)",
    )
    # Field mapping for non-default diarizer schemas (JSON transcripts only).
    parser.add_argument("--speaker-key", default="speaker", help="JSON key for the speaker label")
    parser.add_argument("--start-key", default="start", help="JSON key for the start timestamp")
    parser.add_argument("--end-key", default="end", help="JSON key for the end timestamp")
    parser.add_argument("--text-key", default="text", help="JSON key for the utterance text")
    parser.add_argument(
        "--speaker-map",
        default=None,
        help="Rename anonymous labels, e.g. 'SPEAKER_00=Alice,SPEAKER_01=Bob'",
    )
    parser.add_argument(
        "--emit-prompt",
        action="store_true",
        help="Write the assembled prompt to --out instead of generating minutes "
        "(no LLM call) — hand off to Cowork/Claude Code to write the محضر on their "
        "subscription. Ignores --backend/--model.",
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
        attendees = args.attendees
        if args.attendees_file:
            attendees = Path(args.attendees_file).read_text(encoding="utf-8")
        recap = args.recap
        if args.recap_file:
            recap = Path(args.recap_file).read_text(encoding="utf-8")
        if args.emit_prompt:
            out = emit_prompt_from_files(
                transcript_path=args.transcript,
                notes_path=args.notes,
                out_path=args.out,
                title=args.title,
                date=args.date,
                time=args.time,
                location=args.location,
                attendees=attendees,
                recap=recap,
                fields=fields,
                speaker_map=speaker_map,
            )
            print(f"wrote prompt to {out} — hand to Cowork/Claude Code to write the minutes")
            return 0
        out = generate_minutes_from_files(
            transcript_path=args.transcript,
            notes_path=args.notes,
            out_path=args.out,
            title=args.title,
            date=args.date,
            time=args.time,
            location=args.location,
            attendees=attendees,
            recap=recap,
            backend=args.backend,
            model=args.model,
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
