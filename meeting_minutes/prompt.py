"""Prompt construction — the heart of minutes quality.

Strategy: the human **notes are the spine** (which topics mattered and how to
weight them); the **transcript is ground truth for facts** (names, numbers,
decisions, who said what). The prompts instruct the model to reconcile the two.
"""

from __future__ import annotations

_OUTPUT_CONTRACT = """\
Produce the minutes as Markdown with this exact shape:

# Meeting Minutes — {title} ({date})

## <Topic name>
<2-4 sentence neutral summary of what was discussed and concluded>
- <key point>
- <key point>

## <Next topic>
...

Rules for the output:
- Organize strictly topic-by-topic. One `##` heading per distinct topic.
- Derive the topic list PRIMARILY from the human notes; add a transcript-only
  topic only when it was clearly substantive.
- Order topics by importance as signalled by the notes, not by chronology.
- Be neutral and factual. Do NOT invent attendees, decisions, dates, or numbers.
- Every concrete fact must be grounded in the transcript."""

_ACTIONS_CONTRACT = """\

After the topics, append:

## Decisions & Action Items
- **Decision:** <what was decided>
- **Action:** <owner> — <task> (<due date if stated, else omit>)

Only include items explicitly present in the transcript or notes."""

SYSTEM_PROMPT = """\
You are a meticulous meeting scribe. You are given a participant's rough notes and
the full diarized transcript of the same meeting.

How to use each source:
- NOTES are the agenda/priority signal — they tell you which topics the team cared
  about and how much weight each deserves. Use them to choose and order topics.
- TRANSCRIPT is the ground truth for all facts — names, numbers, decisions, and who
  said what. When the notes and transcript conflict on a fact, the TRANSCRIPT wins.
  When they conflict on emphasis or what mattered, the NOTES win.
- Never include anything not supported by the transcript or notes. No speculation.

{contract}"""

_USER_TEMPLATE = """\
=== HUMAN NOTES ===
{notes}

=== FULL TRANSCRIPT (diarized, [HH:MM:SS] Speaker: text) ===
{transcript}

Write the meeting minutes now, following the required Markdown shape."""

# Used in the map-reduce path to summarise one transcript window.
WINDOW_SYSTEM_PROMPT = """\
You are a meeting scribe summarising ONE segment of a longer meeting transcript.
Extract, as terse Markdown bullets: the topics touched, the key points/decisions,
and any notable verbatim-ish quotes with their speaker. Do not invent anything.
Output only the bullets."""

_SYNTHESIS_TEMPLATE = """\
=== HUMAN NOTES ===
{notes}

=== PER-SEGMENT SUMMARIES (in chronological order) ===
{summaries}

Merge these segment summaries into final meeting minutes. Anchor the topic list to
the human notes; deduplicate points that recur across segments. Follow the required
Markdown shape."""


def build_system_prompt(*, title: str, date: str, include_actions: bool = False) -> str:
    """System prompt for the single-pass / synthesis call."""
    contract = _OUTPUT_CONTRACT.format(title=title, date=date)
    if include_actions:
        contract += _ACTIONS_CONTRACT
    return SYSTEM_PROMPT.format(contract=contract)


def build_user_prompt(*, notes: str, transcript: str) -> str:
    """User prompt pairing the notes (spine) with the full transcript (detail)."""
    return _USER_TEMPLATE.format(notes=notes.strip(), transcript=transcript.strip())


def build_synthesis_prompt(*, notes: str, summaries: str) -> str:
    """User prompt that merges per-window summaries (map-reduce reduce step)."""
    return _SYNTHESIS_TEMPLATE.format(notes=notes.strip(), summaries=summaries.strip())
