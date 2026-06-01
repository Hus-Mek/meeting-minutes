"""Tests for orchestration. A fake LLM is injected — no network is ever touched."""

from __future__ import annotations

import json

import pytest

from meeting_minutes import minutes as M
from meeting_minutes import prompt as P
from meeting_minutes.minutes import (
    chunk_by_window,
    generate_minutes,
    generate_minutes_from_files,
)
from meeting_minutes.transcript import Segment, format_for_prompt

MODEL = "llama-3.3-70b-versatile"


class FakeLlm:
    """Records every call. Returns a well-formed (## heading) response by default."""

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


def _window_fit_tokens(part, notes="n"):
    """Mirror _split_to_budget's own fit estimate for a part."""
    text = P.build_window_user(notes=notes, transcript=format_for_prompt(part))
    return M._budget_tokens(P.WINDOW_SYSTEM_PROMPT + text)


class TestSplitToBudget:
    def test_splits_oversized_window_on_utterance_boundaries(self):
        segs = _segments(*[("A", i, i + 1, "word " * 200) for i in range(8)])
        # Budget that holds ~one segment (just under two), so an 8-segment window
        # must be split. Computed from the code's own estimate to avoid guessing.
        floor_one = _window_fit_tokens(segs[:1])
        floor_two = _window_fit_tokens(segs[:2])
        budget = (floor_one + floor_two) // 2

        parts = M._split_to_budget(segs, notes="n", budget=budget)

        assert len(parts) == 8  # each segment ends up alone
        for part in parts:
            assert _window_fit_tokens(part) <= budget
        assert sum(len(p) for p in parts) == len(segs)  # nothing lost

    def test_single_segment_never_split(self):
        segs = _segments(("A", 0, 1, "x" * 10000))
        parts = M._split_to_budget(segs, notes="n", budget=1)
        assert parts == [segs]


class TestGenerateMinutes:
    def test_rejects_empty_transcript_without_calling_llm(self):
        fake = FakeLlm()
        with pytest.raises(ValueError, match="no segments"):
            generate_minutes(
                segments=(), notes="n", title="T", date="D", client=fake, model=MODEL
            )
        assert fake.calls == []

    def test_single_pass_makes_one_call(self):
        fake = FakeLlm("## Budget\nWe discussed it.")
        segs = _segments(("Alice", 0, 2, "Hello"))
        result = generate_minutes(
            segments=segs, notes="budget", title="Sync", date="2026-06-01",
            client=fake, model=MODEL,
        )
        assert result == "## Budget\nWe discussed it."
        assert len(fake.calls) == 1
        assert "budget" in fake.calls[0]["user"]
        assert "Hello" in fake.calls[0]["user"]

    def test_map_reduce_triggered_below_budget(self):
        fake = FakeLlm("## Merged\nDone.")
        segs = _segments(("A", 0, 5, "x" * 200), ("B", 700, 705, "y" * 200))  # 2 windows
        # Force map-reduce by setting the budget just under the single-pass size.
        system = P.build_system_prompt(title="T", date="D")
        user = P.build_user_prompt(notes="n", transcript=format_for_prompt(segs))
        budget = M._budget_tokens(system + user) - 1

        result = generate_minutes(
            segments=segs, notes="n", title="T", date="D",
            client=fake, model=MODEL, input_token_budget=budget,
        )
        # 2 window summaries + 1 synthesis = 3 calls
        assert len(fake.calls) == 3
        assert result == "## Merged\nDone."
        assert "<segment_summaries>" in fake.calls[-1]["user"]
        # synthesis system must ground in summaries, not the transcript
        assert "PER-SEGMENT SUMMARIES" in fake.calls[-1]["system"]

    def test_rejects_malformed_output_without_heading(self):
        fake = FakeLlm("just prose, no heading")
        segs = _segments(("A", 0, 1, "x"))
        with pytest.raises(RuntimeError, match="no topic headings"):
            generate_minutes(
                segments=segs, notes="n", title="T", date="D", client=fake, model=MODEL
            )

    def test_rejects_empty_output(self):
        fake = FakeLlm("   ")
        segs = _segments(("A", 0, 1, "x"))
        with pytest.raises(RuntimeError, match="empty minutes"):
            generate_minutes(
                segments=segs, notes="n", title="T", date="D", client=fake, model=MODEL
            )

    def test_include_actions_propagates_to_system_prompt(self):
        fake = FakeLlm()
        generate_minutes(
            segments=_segments(("A", 0, 1, "x")), notes="n", title="T", date="D",
            client=fake, model=MODEL, include_actions=True,
        )
        assert "Decisions & Action Items" in fake.calls[0]["system"]

    def test_actions_off_omits_section(self):
        fake = FakeLlm()
        generate_minutes(
            segments=_segments(("A", 0, 1, "x")), notes="n", title="T", date="D",
            client=fake, model=MODEL, include_actions=False,
        )
        assert "Decisions & Action Items" not in fake.calls[0]["system"]


class TestFoldSummaries:
    def test_returns_unchanged_when_already_fits(self):
        fake = FakeLlm("## short")
        summaries = ["a", "b"]
        folded = M._fold_summaries(
            fake, summaries, notes="n", synthesis_system="S", model=MODEL, budget=10_000
        )
        assert folded == summaries
        assert fake.calls == []  # no re-summarization needed

    def test_folds_until_it_fits(self):
        fake = FakeLlm("## short")
        item = "y" * 400
        summaries = [item for _ in range(6)]
        # Budget that holds a batch of ~2 items but not all 6 — forces a fold round
        # that re-summarizes, after which the shorter list fits.
        pair = M._budget_tokens(
            P.WINDOW_SYSTEM_PROMPT + P.build_window_user(notes="n", transcript="\n\n".join(summaries[:2]))
        )
        folded = M._fold_summaries(
            fake, summaries, notes="n", synthesis_system="S", model=MODEL, budget=pair + 1
        )
        assert len(folded) < 6
        assert fake.calls  # at least one batch was re-summarized

    def test_raises_when_cannot_fit(self):
        fake = FakeLlm("summary")
        summaries = ["# big " + "x" * 500, "# big " + "y" * 500]
        with pytest.raises(RuntimeError, match="too large"):
            M._fold_summaries(
                fake, summaries, notes="n", synthesis_system="S", model=MODEL, budget=1
            )


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
            transcript_path=transcript, notes_path=notes, out_path=out,
            title="Sync", date="2026-06-01", client=fake,
        )
        assert result_path == out
        assert out.read_text() == "## Topic\nDone.\n"

    def test_applies_speaker_map(self, tmp_path):
        transcript = tmp_path / "t.json"
        transcript.write_text(
            json.dumps([{"speaker": "SPEAKER_00", "start": 0, "end": 1, "text": "hi"}])
        )
        notes = tmp_path / "n.md"
        notes.write_text("agenda")
        out = tmp_path / "minutes.md"
        fake = FakeLlm("## Topic\nDone.")

        generate_minutes_from_files(
            transcript_path=transcript, notes_path=notes, out_path=out,
            title="Sync", date="2026-06-01", client=fake,
            speaker_map={"SPEAKER_00": "Alice"},
        )
        assert "Alice" in fake.calls[0]["user"]
        assert "SPEAKER_00" not in fake.calls[0]["user"]
