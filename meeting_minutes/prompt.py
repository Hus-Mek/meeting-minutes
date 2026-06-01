"""Prompt construction — the heart of minutes quality.

Strategy: the human **notes are the spine** (which topics mattered and how to
weight them); the **transcript is ground truth for facts** (names, numbers,
decisions, who said what). The prompts instruct the model to reconcile the two.

Two grounding modes exist because of map-reduce: in single-pass the model sees
the raw transcript; in the reduce/synthesis step it sees only per-window
summaries, so it must be told to ground in *those*, not in a transcript it cannot
see.
"""

from __future__ import annotations

_ANON_RULE = (
    "- If speaker labels look anonymous (e.g. SPEAKER_00, SPEAKER_1), they are "
    "anonymous — refer to them by their label and NEVER invent or guess real names."
)

_GROUNDING_TRANSCRIPT = (
    "- TRANSCRIPT is the ground truth for all facts — names, numbers, decisions, and\n"
    "  who said what. When the notes and transcript conflict on a fact, the TRANSCRIPT\n"
    "  wins. When they conflict on emphasis or what mattered, the NOTES win.\n"
    "- Never include anything not supported by the transcript or notes. No speculation."
)

_GROUNDING_SUMMARIES = (
    "- You are given PER-SEGMENT SUMMARIES of the meeting (not the raw transcript).\n"
    "  Ground every fact, name, number, quote, and [HH:MM:SS] anchor in those summaries.\n"
    "- When the notes and summaries conflict on a fact, the SUMMARIES win. When they\n"
    "  conflict on emphasis, the NOTES win.\n"
    "- Never include anything not supported by the summaries or notes. No speculation."
)

_OUTPUT_CONTRACT = """\
Produce the minutes as Markdown with this exact shape:

# Meeting Minutes — {heading}

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
- Be neutral and factual. Do NOT invent attendees, decisions, dates, or numbers."""

_ACTIONS_CONTRACT = """\

After the topics, append:

## Decisions & Action Items
- **Decision:** <what was decided>
- **Action:** <owner> — <task> (<due date if stated, else omit>)

Only include items explicitly present in the source. Omit the section if there are none."""

_SYSTEM_PROMPT = """\
You are a meticulous meeting scribe. You are given a participant's rough notes and
{source_desc} of the same meeting.

How to use each source:
- NOTES are the agenda/priority signal — they tell you which topics the team cared
  about and how much weight each deserves. Use them to choose and order topics.
{grounding}
{anon_rule}

{contract}"""

# Map step: summarise ONE transcript window, preserving anchors and exact figures.
WINDOW_SYSTEM_PROMPT = """\
You are a meeting scribe summarising ONE segment of a longer meeting transcript.
Extract, as terse Markdown bullets: the topics touched, the key points/decisions,
and any notable quotes with their speaker. CRITICAL fidelity rules:
- Preserve the [HH:MM:SS] timestamp anchors for decisions, action items, and quotes.
- Keep names, numbers, and figures EXACT — do not round, rename, or paraphrase them.
- If speaker labels are anonymous (SPEAKER_00), keep the label; never guess a name.
- Do not invent anything. Output only the bullets."""

_USER_TEMPLATE = """\
<human_notes>
{notes}
</human_notes>

<transcript>
{transcript}
</transcript>

Write the meeting minutes now, following the required Markdown shape."""

_WINDOW_USER_TEMPLATE = """\
<priority_topics_from_notes>
{notes}
</priority_topics_from_notes>

<transcript_segment>
{transcript}
</transcript_segment>

Summarise this segment now. Preserve detail touching the priority topics above."""

_SYNTHESIS_TEMPLATE = """\
<human_notes>
{notes}
</human_notes>

<segment_summaries>
{summaries}
</segment_summaries>

Merge these segment summaries (each prefixed with its [HH:MM:SS–HH:MM:SS] range, in
chronological order) into final meeting minutes. Anchor the topic list to the human
notes; deduplicate points that recur across segments. Follow the required Markdown shape."""


def _build_heading(title: str, date: str) -> str:
    """`Title (date)` — but drop the empty parens when no date is given."""
    return f"{title} ({date})" if date else title


def build_system_prompt(
    *, title: str, date: str, include_actions: bool = True, for_synthesis: bool = False
) -> str:
    """System prompt for the single-pass call, or the synthesis (reduce) call."""
    contract = _OUTPUT_CONTRACT.format(heading=_build_heading(title, date))
    if include_actions:
        contract += _ACTIONS_CONTRACT
    if for_synthesis:
        source_desc = "per-segment summaries"
        grounding = _GROUNDING_SUMMARIES
    else:
        source_desc = "the full diarized transcript"
        grounding = _GROUNDING_TRANSCRIPT
    return _SYSTEM_PROMPT.format(
        source_desc=source_desc, grounding=grounding, anon_rule=_ANON_RULE, contract=contract
    )


def build_user_prompt(*, notes: str, transcript: str) -> str:
    """User prompt pairing the notes (spine) with the full transcript (detail)."""
    return _USER_TEMPLATE.format(notes=notes.strip(), transcript=transcript.strip())


def build_window_user(*, notes: str, transcript: str) -> str:
    """User prompt for the map step: a window plus the notes as a priority hint."""
    return _WINDOW_USER_TEMPLATE.format(notes=notes.strip(), transcript=transcript.strip())


def build_synthesis_prompt(*, notes: str, summaries: str) -> str:
    """User prompt that merges per-window summaries (map-reduce reduce step)."""
    return _SYNTHESIS_TEMPLATE.format(notes=notes.strip(), summaries=summaries.strip())
