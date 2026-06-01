# meeting-minutes

Generate clean **topic-by-topic** meeting minutes from a diarized transcript JSON
plus a participant's rough notes.

## How it works

The generator treats the two inputs differently:

- **Notes are the spine** — they decide *which* topics matter and how to weight/order them.
- **Transcript is the ground truth** — accurate names, numbers, decisions, and who said what.

When the sources conflict on a *fact*, the transcript wins; when they conflict on
*emphasis*, the notes win. A typical meeting is summarised in a single LLM call;
very long transcripts fall back to map-reduce (per-window summaries → synthesis).

## Install

```bash
pip install -r requirements.txt
export GROQ_API_KEY=...   # default backend is Groq (Llama 3.3 70B)
```

> The default backend is **Groq** — cheap/near-free, fast, and not OpenRouter.
> A code-level guardrail refuses to run if any `*_BASE_URL` env var points at
> OpenRouter (reserved for Tafkeek). Claude / Ollama backends are stubbed for later.

## Usage

```bash
python -m meeting_minutes.cli \
  --transcript meeting.json \
  --notes notes.md \
  --out minutes.md \
  --title "Weekly Sync" --date 2026-06-01
```

Optional: `--include-actions` appends a *Decisions & Action Items* section;
`--backend {groq,claude,ollama}` and `--model <id>` swap the LLM.

### Transcript format

A JSON list of diarized segments. Default keys are `speaker`, `start`, `end`,
`text` (seconds). If your diarizer uses other names, adapt `FieldMap` in
`meeting_minutes/transcript.py` — the only place field names live.

```json
[
  {"speaker": "Alice", "start": 0.0, "end": 6.2, "text": "Morning everyone..."}
]
```

## Test

```bash
pytest --cov=meeting_minutes
```

Tests inject a fake LLM — no network calls, no spend.
