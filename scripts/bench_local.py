#!/usr/bin/env python3
"""Benchmark local LLMs (Ollama / LM Studio) on the real minutes task.

Runs a transcript through ``build_minutes`` once per candidate model on a local,
OpenAI-compatible server, writing each model's Markdown to ``--out-dir`` and
printing a timing/throughput table. You then eyeball the outputs against a known
good reference (your Sonnet run) to pick the winner — Arabic quality is a human
judgement, not a number.

LOCAL ONLY. This script refuses any non-local backend, so it can never spend money
or touch OpenRouter — it only talks to your local server.

Examples
--------
    # LM Studio (start its server first; load each model's id you list)
    python scripts/bench_local.py --backend lmstudio \\
        --transcript meeting.json --notes notes.md --reference sonnet.md \\
        --models "allam-7b,yehia-7b,gemma-4-e4b,qwen3-8b"

    # Ollama (default slate)
    python scripts/bench_local.py --backend ollama \\
        --transcript meeting.json --notes notes.md
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

# Make the package importable when run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meeting_minutes.llm import LOCAL_BACKENDS  # noqa: E402
from meeting_minutes.minutes import build_minutes  # noqa: E402
from meeting_minutes.transcript import (  # noqa: E402
    FieldMap,
    estimate_tokens,
    load_transcript,
)

# Default Ollama tags for the recommended Arabic-capable slate. For LM Studio pass
# your own --models (the ids of the GGUFs you've loaded).
DEFAULT_SLATE = "iKhalid/ALLaM:7b,yehia7b,gemma4:e4b,qwen3:8b,QCRI/Fanar-1-9B-Instruct"


def _slug(model: str) -> str:
    """Filesystem-safe filename stem for a model id."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", model).strip("_")


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Benchmark local LLMs on the minutes task.")
    p.add_argument("--transcript", required=True, help="Transcript file (Teams text or JSON)")
    p.add_argument("--notes", default=None, help="Optional notes file (md/txt)")
    p.add_argument(
        "--reference",
        default=None,
        help="Optional reference minutes (e.g. your Sonnet output) — copied next to "
        "the results for side-by-side comparison; not scored automatically",
    )
    p.add_argument(
        "--backend",
        default="lmstudio",
        choices=sorted(LOCAL_BACKENDS),
        help="Local backend (default: lmstudio). Refuses cloud backends.",
    )
    p.add_argument("--models", default=DEFAULT_SLATE, help="Comma-separated model ids/tags")
    p.add_argument("--out-dir", default="bench_out", help="Where to write per-model minutes")
    p.add_argument("--title", default="اجتماع", help="Meeting title for the header")
    p.add_argument("--date", default="", help="Meeting date for the header")
    p.add_argument("--attendees", default="", help="Roster, 'Name — Org' per line")
    # JSON field mapping for non-default diarizer schemas.
    p.add_argument("--speaker-key", default="speaker")
    p.add_argument("--start-key", default="start")
    p.add_argument("--end-key", default="end")
    p.add_argument("--text-key", default="text")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.backend not in LOCAL_BACKENDS:  # defence in depth beyond argparse choices
        print(f"error: {args.backend!r} is not a local backend", file=sys.stderr)
        return 2

    fields = FieldMap(
        speaker=args.speaker_key, start=args.start_key, end=args.end_key, text=args.text_key
    )
    segments = load_transcript(args.transcript, fields=fields)
    notes = Path(args.notes).read_text(encoding="utf-8") if args.notes else ""
    models = [m.strip() for m in args.models.split(",") if m.strip()]

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if args.reference:
        ref = Path(args.reference)
        (out_dir / f"_reference{ref.suffix or '.md'}").write_text(
            ref.read_text(encoding="utf-8"), encoding="utf-8"
        )

    print(f"Benchmarking {len(models)} model(s) via {args.backend} on {len(segments)} segments.\n")
    rows: list[tuple[str, str, str, str]] = []
    for model in models:
        print(f"→ {model} …", flush=True)
        started = time.perf_counter()
        try:
            minutes = build_minutes(
                segments=segments,
                notes=notes,
                title=args.title,
                date=args.date,
                attendees=args.attendees,
                backend=args.backend,
                model=model,
            )
        except Exception as exc:  # one bad model shouldn't abort the whole run
            elapsed = time.perf_counter() - started
            print(f"   ✗ failed after {elapsed:.0f}s: {exc}\n", file=sys.stderr)
            rows.append((model, f"{elapsed:.0f}", "—", f"ERROR: {exc}"))
            continue
        elapsed = time.perf_counter() - started
        out_tokens = estimate_tokens(minutes)
        tok_s = out_tokens / elapsed if elapsed > 0 else 0.0
        (out_dir / f"{_slug(model)}.md").write_text(minutes + "\n", encoding="utf-8")
        rows.append((model, f"{elapsed:.0f}", str(out_tokens), f"~{tok_s:.1f} tok/s"))
        print(f"   ✓ {elapsed:.0f}s, ~{out_tokens} out-tokens (~{tok_s:.1f} tok/s)\n", flush=True)

    width = max((len(r[0]) for r in rows), default=5)
    print("\n=== Results (output written to "
          f"{out_dir}/) — judge Arabic quality by reading the files ===")
    print(f"{'model'.ljust(width)}  {'secs':>5}  {'out~tok':>8}  throughput / status")
    for model, secs, toks, status in rows:
        print(f"{model.ljust(width)}  {secs:>5}  {toks:>8}  {status}")
    if args.reference:
        print(f"\nReference (Sonnet) copied to {out_dir}/_reference* — open it alongside the rest.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
