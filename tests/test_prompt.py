"""Unit tests for prompt construction."""

from __future__ import annotations

from meeting_minutes.prompt import (
    build_synthesis_prompt,
    build_system_prompt,
    build_user_prompt,
)


class TestSystemPrompt:
    def test_includes_title_and_date(self):
        result = build_system_prompt(title="Weekly Sync", date="2026-06-01")
        assert "Weekly Sync" in result
        assert "2026-06-01" in result

    def test_states_notes_are_spine_and_transcript_is_truth(self):
        result = build_system_prompt(title="T", date="D")
        assert "NOTES are the agenda/priority signal" in result
        assert "TRANSCRIPT is the ground truth" in result

    def test_enforces_topic_by_topic(self):
        result = build_system_prompt(title="T", date="D")
        assert "topic-by-topic" in result
        assert "One `##` heading per distinct topic" in result

    def test_omits_actions_section_by_default(self):
        result = build_system_prompt(title="T", date="D")
        assert "Decisions & Action Items" not in result

    def test_includes_actions_when_flagged(self):
        result = build_system_prompt(title="T", date="D", include_actions=True)
        assert "Decisions & Action Items" in result


class TestUserPrompt:
    def test_contains_notes_and_transcript_markers(self):
        result = build_user_prompt(notes="my notes", transcript="[00:00:00] A: hi")
        assert "=== HUMAN NOTES ===" in result
        assert "my notes" in result
        assert "=== FULL TRANSCRIPT" in result
        assert "[00:00:00] A: hi" in result

    def test_strips_whitespace(self):
        result = build_user_prompt(notes="  n  ", transcript="  t  ")
        assert "\nn\n" in result
        assert "\nt" in result


class TestSynthesisPrompt:
    def test_merges_notes_and_summaries(self):
        result = build_synthesis_prompt(notes="notes", summaries="- point one")
        assert "notes" in result
        assert "- point one" in result
        assert "PER-SEGMENT SUMMARIES" in result
