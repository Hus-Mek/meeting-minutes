"""Unit tests for prompt construction."""

from __future__ import annotations

from meeting_minutes.prompt import (
    build_synthesis_prompt,
    build_system_prompt,
    build_user_prompt,
    build_window_user,
)


class TestSystemPrompt:
    def test_includes_title_and_date(self):
        result = build_system_prompt(title="Weekly Sync", date="2026-06-01")
        assert "# Meeting Minutes — Weekly Sync (2026-06-01)" in result

    def test_drops_empty_parens_when_no_date(self):
        result = build_system_prompt(title="Weekly Sync", date="")
        assert "# Meeting Minutes — Weekly Sync\n" in result
        assert "()" not in result

    def test_states_notes_are_spine(self):
        result = build_system_prompt(title="T", date="D")
        assert "NOTES are the agenda/priority signal" in result

    def test_single_pass_grounds_in_transcript(self):
        result = build_system_prompt(title="T", date="D")
        assert "TRANSCRIPT is the ground truth" in result

    def test_synthesis_grounds_in_summaries_not_transcript(self):
        result = build_system_prompt(title="T", date="D", for_synthesis=True)
        assert "PER-SEGMENT SUMMARIES" in result
        assert "the SUMMARIES win" in result
        assert "TRANSCRIPT is the ground truth" not in result

    def test_includes_anonymous_speaker_rule(self):
        result = build_system_prompt(title="T", date="D")
        assert "SPEAKER_00" in result
        assert "never invent or guess real names" in result.lower() or "NEVER invent" in result

    def test_enforces_topic_by_topic(self):
        result = build_system_prompt(title="T", date="D")
        assert "topic-by-topic" in result
        assert "One `##` heading per distinct topic" in result

    def test_includes_actions_by_default(self):
        result = build_system_prompt(title="T", date="D")
        assert "Decisions & Action Items" in result

    def test_excludes_actions_when_flagged_off(self):
        result = build_system_prompt(title="T", date="D", include_actions=False)
        assert "Decisions & Action Items" not in result


class TestUserPrompt:
    def test_wraps_notes_and_transcript_in_xml_tags(self):
        result = build_user_prompt(notes="my notes", transcript="[00:00:00] A: hi")
        assert "<human_notes>" in result
        assert "my notes" in result
        assert "<transcript>" in result
        assert "[00:00:00] A: hi" in result

    def test_strips_whitespace(self):
        result = build_user_prompt(notes="  n  ", transcript="  t  ")
        assert "<human_notes>\nn\n</human_notes>" in result


class TestWindowUser:
    def test_carries_notes_as_priority_hint(self):
        result = build_window_user(notes="budget", transcript="[00:00] A: x")
        assert "priority_topics_from_notes" in result
        assert "budget" in result
        assert "[00:00] A: x" in result


class TestSynthesisPrompt:
    def test_merges_notes_and_summaries(self):
        result = build_synthesis_prompt(notes="notes", summaries="- point one")
        assert "notes" in result
        assert "- point one" in result
        assert "<segment_summaries>" in result
