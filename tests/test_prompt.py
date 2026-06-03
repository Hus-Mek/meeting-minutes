"""Unit tests for the Arabic محضر اجتماع prompt construction."""

from __future__ import annotations

from meeting_minutes.prompt import (
    WINDOW_SYSTEM_PROMPT,
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

    def test_owner_is_assignee_name_for_app_to_map(self):
        result = build_system_prompt(title="t", date="d")
        assert "الاسم الكامل للشخص المكلّف" in result
        assert "سيتولّى النظام لاحقًا استبدال الاسم بجهته" in result

    def test_requires_consistent_names_across_tables(self):
        result = build_system_prompt(title="t", date="d")
        assert "نفس صيغة الاسم بالضبط" in result

    def test_requires_pipe_escaping_in_table_cells(self):
        result = build_system_prompt(title="t", date="d")
        assert "مهرّبة" in result
        assert "\\|" in result

    def test_requires_arabic_names_with_saudi_transliteration(self):
        result = build_system_prompt(title="t", date="d")
        assert "أسماء الأشخاص بالعربية" in result
        assert "النطق السعودي" in result

    def test_demands_detailed_discussion_points(self):
        result = build_system_prompt(title="t", date="d")
        assert "تفصيلية وشاملة" in result

    def test_forbids_placeholder_echo(self):
        result = build_system_prompt(title="t", date="d")
        assert "placeholder" in result

    def test_requires_gender_agreement(self):
        result = build_system_prompt(title="t", date="d")
        assert "التطابق الصرفي الصحيح للجنس" in result

    def test_recap_is_described_as_unreliable_hint(self):
        result = build_system_prompt(title="t", date="d")
        assert "read.ai" in result
        assert "ولا تعتمدها مصدرًا للحقائق" in result


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

    def test_includes_recap_when_provided(self):
        result = build_user_prompt(notes="n", transcript="t", recap="Action Items: ...")
        assert "recap_readai_unreliable" in result
        assert "Action Items: ..." in result


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


class TestWindowSystemPrompt:
    """The map step must agree with the synthesis contract: owner = PERSON name,
    not the organization (the app maps the name to a الجهة downstream)."""

    def test_map_step_emits_person_name_not_org(self):
        # The old, contradictory instruction ("الجهة/الشركة المسؤولة (لا اسم شخص)")
        # would put an org in the «المسؤول» column and break the name→org lookup.
        assert "لا اسم شخص" not in WINDOW_SYSTEM_PROMPT
        assert "اسم الشخص المكلّف" in WINDOW_SYSTEM_PROMPT
        assert "لا الجهة" in WINDOW_SYSTEM_PROMPT
