#!/usr/bin/env python3
"""Fetch transcript and recap from read.ai by meeting ID.

Usage:
    python scripts/fetch_readai.py --meeting-id <id> --access-token <token> [--out-dir <dir>]

Writes meeting_<id>_transcript.json and meeting_<id>_recap.txt to the output directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="fetch_readai",
        description="Fetch transcript and recap from read.ai.",
    )
    parser.add_argument("--meeting-id", required=True, help="read.ai meeting ID")
    parser.add_argument("--access-token", required=True, help="read.ai access token")
    parser.add_argument(
        "--out-dir",
        default=".",
        help="Output directory (default: current dir)",
    )
    parser.add_argument("--debug", action="store_true", help="Show full tracebacks on error")

    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)

    try:
        from meeting_minutes.readai import fetch_report

        transcript, recap = fetch_report(meeting_id=args.meeting_id, access_token=args.access_token)

        # Write transcript as JSON
        transcript_file = out_dir / f"meeting_{args.meeting_id}_transcript.json"
        transcript_file.write_text(json.dumps(transcript, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"wrote {transcript_file}")

        # Write recap as plain text
        recap_file = out_dir / f"meeting_{args.meeting_id}_recap.txt"
        recap_file.write_text(recap, encoding="utf-8")
        print(f"wrote {recap_file}")

        return 0
    except Exception as exc:
        if args.debug:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
