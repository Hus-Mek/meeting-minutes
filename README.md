# meeting-minutes

Generate a formal Arabic **محضر اجتماع** from a meeting transcript plus notes.

## Output structure

Markdown modelled on a formal minutes template:

- **Header** — التاريخ / الوقت / الموقع (date / time / location)
- **## قائمة الحضور** — attendees table (الاسم | الجهة)
- **## نقاط نقاش الاجتماع** — ملخص الاجتماع + bulleted discussion points
- **## نتائج الاجتماع** — outcomes table (المهام/التوصيات | المسؤول | التاريخ المستهدف)

## How it works

The generator treats the inputs differently:

- **Notes are the spine** — they decide *which* points matter and how to weight them.
- **Transcript is the ground truth** — accurate names, numbers, decisions, who said what.
- **Attendees are hybrid** — names come from the transcript speakers; you supply each
  one's organization (الجهة) and the date/time/location.

When the sources conflict on a *fact*, the transcript wins; when they conflict on
*emphasis*, the notes win. A typical meeting is summarised in a single LLM call;
very long transcripts fall back to map-reduce (per-window summaries → synthesis).

## Transcript formats (auto-detected)

- **Teams/Zoom text export** — `M:SS - Speaker` followed by the spoken text.
- **Diarized JSON** — a list of `speaker`/`start`/`end`/`text` segments (field-configurable).

Two ways to use it: the **[CLI](#usage)** or the **[web GUI](#web-gui)**.

## Web GUI

A document-grade, two-pane web app (React + Vite + shadcn/ui) served by FastAPI:
inputs (transcript + notes + options) on the left, the generated minutes rendered
as a real document on the right — with copy, download `.md`, and print-to-PDF.

```bash
# one-time build of the frontend
cd frontend && npm install && npm run build && cd ..

# run the server (serves the SPA + API at http://localhost:8000)
export GROQ_API_KEY=...
python -m meeting_minutes.web
```

Drop a diarized transcript JSON, paste your notes, and hit **Generate**. A live
preview ("42 segments · 3 speakers · 18m") confirms the file parsed before you
spend a call; non-default diarizer schemas and `SPEAKER_00`-style labels are
handled under **Advanced**.

**Frontend dev** (hot reload, proxies `/api` to FastAPI):

```bash
python -m meeting_minutes.web          # terminal 1 (API on :8000)
cd frontend && npm run dev             # terminal 2 (UI on :5173)
```

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
  --transcript meeting.txt \
  --notes notes.md \
  --out minutes.md \
  --title "اجتماع المتابعة" --date 11/5/2026 \
  --time "11:30–12:30" --location "عن بعد" \
  --attendees-file roster.txt    # one "Name — Organization" per line
```

`--backend {groq,claude,ollama}` and `--model <id>` swap the LLM (claude/ollama are
stubs for now); `--debug` prints full tracebacks.

Routing is **model-aware**: it sizes the full prompt against the model's real
context window (128k for Llama 3.3 70B, minus reserved output) and automatically
falls back to a bounded map-reduce for very long meetings.

### JSON transcripts — field mapping

For diarized JSON, default keys are `speaker`, `start`, `end`, `text` (seconds).
If your tool uses other names, pass them on the CLI — no need to edit source:

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
