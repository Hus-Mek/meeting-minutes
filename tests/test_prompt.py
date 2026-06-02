"""Unit tests for the Arabic محضر اجتماع prompt construction."""

from __future__ import annotations

from meeting_minutes.prompt import (
    build_synthesis_prompt,
    build_system_prompt,
    build_user_prompt,
    build_window_user,
)

HEADINGS = ("## قائمة الحضور", "## نقاط نقاش الاجتماع", "## نتائج الاجتماع")


class TestSystemPrompt:
    def test_includes_all_four_section_headings(self):
        result = build_system_prompt(title="اجتماع المتابعة", date="11/5/2026")
        assert "# محضر اجتماع — اجتماع المتابعة (11/5/2026)" in result
        for heading in HEADINGS:
            assert heading in result

    def test_header_row_uses_provided_metadata(self):
        result = build_system_prompt(
            title="t", date="11/5/2026", time="11:30–12:30", location="عن بعد"
        )
        assert "| 11/5/2026 | 11:30–12:30 | عن بعد |" in result

    def test_header_row_uses_dash_when_metadata_missing(self):
        result = build_system_prompt(title="t", date="")
        assert "| — | — | — |" in result

    def test_single_pass_grounds_in_transcript(self):
        result = build_system_prompt(title="t", date="d")
        assert "TRANSCRIPT" in result

    def test_synthesis_grounds_in_summaries(self):
        result = build_system_prompt(title="t", date="d", for_synthesis=True)
        assert "SUMMARIES" in result
        assert "ملخصات مقاطع" in result

    def test_attendees_rule_present(self):
        result = build_system_prompt(title="t", date="d")
        assert "Unidentified Speaker" in result
        assert "قائمة الحضور" in result


class TestUserPrompt:
    def test_wraps_roster_notes_and_transcript(self):
        result = build_user_prompt(
            notes="الأولوية للميزانية", transcript="[0:12] مشاري: مرحبا", attendees="مشاري — هيئة"
        )
        assert "<roster>" in result and "مشاري — هيئة" in result
        assert "<notes>" in result and "الأولوية للميزانية" in result
        assert "<transcript>" in result and "مرحبا" in result

    def test_missing_roster_becomes_dash(self):
        result = build_user_prompt(notes="n", transcript="t", attendees="")
        assert "<roster>\n—\n</roster>" in result


class TestSynthesisPrompt:
    def test_merges_roster_notes_and_summaries(self):
        result = build_synthesis_prompt(notes="n", summaries="- نقطة", attendees="x")
        assert "<segment_summaries>" in result
        assert "- نقطة" in result
        assert "x" in result


class TestWindowUser:
    def test_carries_notes_as_priority_hint(self):
        result = build_window_user(notes="ميزانية", transcript="[0:12] x")
        assert "priority_notes" in result
        assert "ميزانية" in result
