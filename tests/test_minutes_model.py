"""Tests for the Python port of the Minutes model + Markdown parser.

This mirrors frontend/src/lib/minutes.ts (parseMinutes / ownerOrg / normalizeName)
so the .docx render path builds the same model the on-screen template does. All
data here is SYNTHETIC — no real names/orgs (privacy hard rule).
"""

from __future__ import annotations

import pytest

from meeting_minutes.minutes_model import (
    Attendee,
    Minutes,
    Outcome,
    normalize_name,
    owner_org,
    parse_minutes,
)

# A synthetic 4-section محضر in the exact Markdown contract the LLM emits.
SAMPLE_MD = """\
# محضر اجتماع — اجتماع تجريبي (2026-06-03)

| التاريخ | الوقت | الموقع |
| --- | --- | --- |
| 2026-06-03 | 10:00 | الرياض |

## قائمة الحضور
| # | الاسم | الجهة |
| --- | --- | --- |
| 1 | الحاضر الأول | جهة-أ |
| 2 | الحاضر الثاني | جهة-ب |
| 3 | الحاضر الثالث | — |

## نقاط نقاش الاجتماع
**ملخص الاجتماع**
فقرة تمهيدية عن الاجتماع التجريبي.

- نقطة النقاش الأولى المفصّلة
- نقطة النقاش الثانية المفصّلة

## نتائج الاجتماع
| المهام/ التوصيات | المسؤول | التاريخ المستهدف |
| --- | --- | --- |
| المهمة الأولى | الحاضر الأول | 2026-06-10 |
| المهمة الثانية | الحاضر الثالث | — |
| المهمة الثالثة | لجنة خارجية | — |

شكرًا لكم
"""


@pytest.fixture
def minutes() -> Minutes:
    return parse_minutes(SAMPLE_MD)


# --- A. structure -----------------------------------------------------------

def test_parse_extracts_title_date_time_location(minutes: Minutes) -> None:
    assert minutes.title == "اجتماع تجريبي"
    assert minutes.date == "2026-06-03"
    assert minutes.time == "10:00"
    assert minutes.location == "الرياض"


def test_parse_title_strips_prefix_and_trailing_date_only() -> None:
    md = "# محضر اجتماع — اجتماع تقني (تجريبي) (2026-01-05)\n"
    # The internal "(تجريبي)" parenthetical is meaningful and must survive; only a
    # trailing date-in-parens is stripped.
    assert parse_minutes(md).title == "اجتماع تقني (تجريبي)"


def test_parse_attendee_count_fields_and_order(minutes: Minutes) -> None:
    assert len(minutes.attendees) == 3
    assert minutes.attendees[0] == Attendee(name="الحاضر الأول", org="جهة-أ")
    assert minutes.attendees[1].name == "الحاضر الثاني"
    assert [a.name for a in minutes.attendees] == [
        "الحاضر الأول",
        "الحاضر الثاني",
        "الحاضر الثالث",
    ]


def test_parse_placeholder_org_becomes_empty(minutes: Minutes) -> None:
    # "—" is a placeholder → stored as empty string (matches isPlaceholder in TS).
    assert minutes.attendees[2].org == ""


def test_parse_summary_and_points_without_bullet_markers(minutes: Minutes) -> None:
    assert minutes.summary == "فقرة تمهيدية عن الاجتماع التجريبي."
    assert minutes.points == [
        "نقطة النقاش الأولى المفصّلة",
        "نقطة النقاش الثانية المفصّلة",
    ]
    assert all(not p.startswith("-") for p in minutes.points)


def test_parse_outcomes_count_and_fields(minutes: Minutes) -> None:
    assert len(minutes.outcomes) == 3
    assert minutes.outcomes[0] == Outcome(
        task="المهمة الأولى", person="الحاضر الأول", date="2026-06-10"
    )
    assert minutes.outcomes[1].date == ""  # "—" placeholder → empty


# --- B. owner resolution (person -> org), mirrors ownerOrg ------------------

def test_owner_resolves_roster_person_to_org(minutes: Minutes) -> None:
    assert owner_org(minutes, "الحاضر الأول") == "جهة-أ"


def test_owner_blank_org_returns_dash(minutes: Minutes) -> None:
    # Roster person whose الجهة is unknown → "—", never their name.
    assert owner_org(minutes, "الحاضر الثالث") == "—"


def test_owner_non_roster_person_shown_verbatim(minutes: Minutes) -> None:
    # A committee / external party not in the roster is shown as-is, never dropped.
    assert owner_org(minutes, "لجنة خارجية") == "لجنة خارجية"


def test_owner_empty_person_returns_dash(minutes: Minutes) -> None:
    assert owner_org(minutes, "") == "—"
    assert owner_org(minutes, "   ") == "—"


def test_owner_arabic_normalization_honorific_and_tashkeel(minutes: Minutes) -> None:
    # Same person written with a leading honorific + tashkeel + alef-hamza variant
    # still resolves to their org.
    assert owner_org(minutes, "أ. الحاضِر الأوّل") == "جهة-أ"
    assert owner_org(minutes, "الحاضر الاول") == "جهة-أ"  # bare alef variant


def test_normalize_name_strips_diacritics_and_unifies_letters() -> None:
    assert normalize_name("الحاضِر الأوّل") == normalize_name("الحاضر الاول")
    assert normalize_name("م. محمد") == "محمد"
    # ة is unified to ه for matching, so "سارة" -> "ساره" after honorific strip.
    assert normalize_name("الدكتور سارة") == "ساره"


# --- edge cases -------------------------------------------------------------

def test_escaped_pipe_in_outcome_task_not_split() -> None:
    md = (
        "# محضر اجتماع — ت\n\n"
        "## نتائج الاجتماع\n"
        "| المهام/ التوصيات | المسؤول | التاريخ المستهدف |\n"
        "| --- | --- | --- |\n"
        "| تشغيل أمر cat \\| grep | جهة | — |\n"
    )
    m = parse_minutes(md)
    assert len(m.outcomes) == 1
    assert m.outcomes[0].task == "تشغيل أمر cat | grep"


def test_attendee_unescaped_extra_pipe_folds_into_org() -> None:
    md = (
        "# محضر اجتماع — ت\n\n"
        "## قائمة الحضور\n"
        "| # | الاسم | الجهة |\n"
        "| --- | --- | --- |\n"
        "| 1 | اسم | جهة | فرع |\n"
    )
    m = parse_minutes(md)
    assert len(m.attendees) == 1
    assert m.attendees[0].name == "اسم"
    assert m.attendees[0].org == "جهة | فرع"


def test_missing_optional_fields_default_to_empty() -> None:
    md = "# محضر اجتماع — اجتماع\n\n## قائمة الحضور\n"
    m = parse_minutes(md)
    assert m.date == "" and m.time == "" and m.location == ""
    assert m.attendees == []
    assert m.outcomes == []
    assert m.summary == ""
    assert m.points == []


def test_placeholder_attendee_rows_are_skipped() -> None:
    md = (
        "# محضر اجتماع — ت\n\n"
        "## قائمة الحضور\n"
        "| # | الاسم | الجهة |\n"
        "| --- | --- | --- |\n"
        "| 1 | «اسم الحاضر» | «الجهة» |\n"
        "| 2 | اسم حقيقي | جهة |\n"
    )
    m = parse_minutes(md)
    assert len(m.attendees) == 1
    assert m.attendees[0].name == "اسم حقيقي"
