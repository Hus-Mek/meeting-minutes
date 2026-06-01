"""Tests for orchestration. A fake LLM is injected — no network is ever touched."""

from __future__ import annotations

import json

from meeting_minutes.minutes import (
    chunk_by_window,
    generate_minutes,
    generate_minutes_from_files,
)
from meeting_minutes.transcript import Segment


class FakeLlm:
    """Records every call and returns a canned response per call."""

    def __init__(self, response="## Topic\nSummary."):
        self.response = response
        self.calls: list[dict] = []

    def generate(self, system: str, user: str, *, model: str) -> str:
        self.calls.append({"system": system, "user": user, "model": model})
        return self.response


def _segments(*specs):
    return tuple(Segment(spk, start, end, text) for spk, start, end, text in specs)


class TestChunkByWindow:
    def test_empty_returns_empty(self):
        assert chunk_by_window(()) == ()

    def test_groups_by_window_boundary(self):
        segs = _segments(
            ("A", 0, 5, "one"),
            ("B", 300, 305, "two"),     # same 600s window
            ("A", 601, 605, "three"),   # next window
        )
        windows = chunk_by_window(segs, window_seconds=600)
        assert len(windows) == 2
        assert len(windows[0]) == 2
        assert windows[1][0].text == "three"

    def test_never_splits_an_utterance(self):
        segs = _segments(("A", 0, 1, "x"), ("A", 10, 11, "y"))
        windows = chunk_by_window(segs, window_seconds=600)
        assert windows == (segs,)


class TestGenerateMinutes:
    def test_single_pass_makes_one_call(self):
        # Arrange
        fake = FakeLlm("## Budget\nWe discussed it.")
        segs = _segments(("Alice", 0, 2, "Hello"))

        # Act
        result = generate_minutes(
            segments=segs, notes="budget", title="Sync", date="2026-06-01", client=fake
        )

        # Assert
        assert result == "## Budget\nWe discussed it."
        assert len(fake.calls) == 1
        assert "budget" in fake.calls[0]["user"]
        assert "Hello" in fake.calls[0]["user"]

    def test_map_reduce_triggered_above_limit(self):
        fake = FakeLlm("bullets")
        segs = _segments(
            ("A", 0, 5, "early"),
            ("B", 700, 705, "later"),  # forces 2 windows at 600s
        )

        result = generate_minutes(
            segments=segs,
            notes="n",
            title="T",
            date="D",
            client=fake,
            single_pass_token_limit=0,  # force map-reduce
        )

        # 2 window summaries + 1 synthesis = 3 calls
        assert len(fake.calls) == 3
        assert result == "bullets"
        # final synthesis call carries the notes
        assert "PER-SEGMENT SUMMARIES" in fake.calls[-1]["user"]

    def test_include_actions_propagates_to_system_prompt(self):
        fake = FakeLlm()
        generate_minutes(
            segments=_segments(("A", 0, 1, "x")),
            notes="n",
            title="T",
            date="D",
            client=fake,
            include_actions=True,
        )
        assert "Decisions & Action Items" in fake.calls[0]["system"]


class TestGenerateMinutesFromFiles:
    def test_writes_output_file(self, tmp_path):
        transcript = tmp_path / "t.json"
        transcript.write_text(
            json.dumps([{"speaker": "A", "start": 0, "end": 1, "text": "hi"}])
        )
        notes = tmp_path / "n.md"
        notes.write_text("agenda")
        out = tmp_path / "minutes.md"
        fake = FakeLlm("## Topic\nDone.")

        result_path = generate_minutes_from_files(
            transcript_path=transcript,
            notes_path=notes,
            out_path=out,
            title="Sync",
            date="2026-06-01",
            client=fake,
        )

        assert result_path == out
        assert out.read_text() == "## Topic\nDone.\n"
