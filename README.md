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
  --title "Weekly Sync"        # --date defaults to today
```

A *Decisions & Action Items* section is included by default — pass `--no-actions`
to drop it. `--backend {groq,claude,ollama}` and `--model <id>` swap the LLM
(claude/ollama are stubs for now); `--debug` prints full tracebacks.

Routing is **model-aware**: it sizes the full prompt against the model's real
context window (128k for Llama 3.3 70B, minus reserved output) and automatically
falls back to a bounded map-reduce for very long meetings.

### Transcript format

A JSON list of diarized segments. Default keys are `speaker`, `start`, `end`,
`text` (seconds). If your diarizer uses other names, pass them on the CLI — no
need to edit source:

```bash
--speaker-key spk --start-key begin --end-key stop --text-key content
```

Anonymous labels can be renamed: `--speaker-map "SPEAKER_00=Alice,SPEAKER_01=Bob"`
(and the model is told never to invent names for unmapped `SPEAKER_NN` labels).

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
