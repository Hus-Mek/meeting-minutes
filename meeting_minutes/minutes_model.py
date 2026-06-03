"""Structured Minutes model + Markdown parser — the Python mirror of
``frontend/src/lib/minutes.ts`` (``parseMinutes`` / ``ownerOrg`` / ``normalizeName``).

The LLM emits the محضر as a fixed 4-section Markdown contract (see
``meeting_minutes/prompt.py``). The on-screen template parses that to a model in
TypeScript; the .docx render path needs the *same* model server-side, so the two
renderers stay byte-for-byte equivalent. This module is that parser — pure,
network-free, and the logic-heavy core, so it carries the bulk of the test weight.

Owner mapping (the one non-obvious rule): the LLM writes the assignee's **person
name** in «المسؤول»; ``owner_org`` resolves it to that person's الجهة from the
roster (Arabic-normalized), and a non-roster owner (committee/external) is shown
verbatim rather than dropped. See [[owner-mapping-design]].
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Attendee:
    name: str
    org: str


@dataclass(frozen=True)
class Outcome:
    task: str
    person: str  # assignee — resolved to an org for «المسؤول» via owner_org()
    date: str


@dataclass
class Minutes:
    title: str = ""
    date: str = ""
    time: str = ""
    location: str = ""
    attendees: list[Attendee] = field(default_factory=list)
    summary: str = ""
    points: list[str] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)


# --- normalization ----------------------------------------------------------

# tashkeel (ً–ْ) + superscript alef (ٰ) + tatweel (ـ).
_TASHKEEL_RE = re.compile(r"[ً-ْٰـ]")
# Leading honorifics/titles to ignore when matching names (mirrors HONORIFIC in TS).
_HONORIFIC_RE = re.compile(
    r"^(?:م|د|أ|ا|الاستاذ|الدكتور|المهندس|الشيخ|السيد|السيده|الانسه)\.?\s+"
)


def normalize_name(s: str) -> str:
    """Normalize an Arabic/Latin name for *matching only* (display keeps the
    original): drop tashkeel/tatweel, unify alef/ya/ta-marbuta variants, strip a
    leading honorific, collapse whitespace, lowercase. Mirrors ``normalizeName``.
    """
    s = unicodedata.normalize("NFC", s)
    s = _TASHKEEL_RE.sub("", s)
    s = s.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    s = s.replace("ى", "ي")
    s = s.replace("ة", "ه")
    s = re.sub(r"\s+", " ", s).strip()
    s = _HONORIFIC_RE.sub("", s)
    return s.lower()


def owner_org(minutes: Minutes, person: str) -> str:
    """Resolve a task's owner for display: a roster person shows their الجهة (or
    "—" until it is filled in); anyone not in the roster is shown verbatim.
    """
    key = normalize_name(person)
    if not key:
        return "—"
    for a in minutes.attendees:
        if normalize_name(a.name) == key:
            org = a.org.strip()
            return org if org and org != "—" else "—"
    return person.strip()


# --- markdown parsing -------------------------------------------------------

_HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
_SEPARATOR_RE = re.compile(r"^\|[\s:|\-]+\|?\s*$")
_PIPE_SPLIT_RE = re.compile(r"(?<!\\)\|")
_BULLET_RE = re.compile(r"^[-*•]\s+(.*)$")
_PLACEHOLDER_RE = re.compile(r"^[-—\s]*$")
_TITLE_PREFIX_RE = re.compile(r"^محضر اجتماع\s*[—-]\s*")
# Strip only a trailing DATE in parens (starts with an ASCII/Arabic-Indic digit),
# never an internal parenthetical like "(تقني)".
_TRAILING_DATE_RE = re.compile(r"\s*\([0-9٠-٩][^)]*\)\s*$")


def _is_placeholder(s: str) -> bool:
    return "«" in s or s == "" or bool(_PLACEHOLDER_RE.match(s))


def _split_sections(md: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"_preamble": []}
    current = "_preamble"
    for line in md.split("\n"):
        m = _HEADING_RE.match(line)
        if m:
            current = m.group(1).strip()
            sections[current] = []
        else:
            sections[current].append(line)
    return sections


def _section_by_keyword(sections: dict[str, list[str]], needle: str) -> list[str]:
    for key, lines in sections.items():
        if needle in key:
            return lines
    return []


def _table_rows(lines: list[str]) -> list[list[str]]:
    """Rows of a Markdown pipe-table (separator dropped). Only outer structural
    pipes delimit cells: a literal ``\\|`` inside a cell stays in one cell."""
    rows: list[list[str]] = []
    for line in lines:
        t = line.strip()
        if not t.startswith("|"):
            continue
        if _SEPARATOR_RE.match(t):
            continue
        body = re.sub(r"\|$", "", re.sub(r"^\|", "", t))
        cells = [c.replace("\\|", "|").strip() for c in _PIPE_SPLIT_RE.split(body)]
        rows.append(cells)
    return rows


def _parse_title(preamble: list[str]) -> str:
    h1 = next((line for line in preamble if line.startswith("# ")), "")
    title = re.sub(r"^#\s+", "", h1)
    title = _TITLE_PREFIX_RE.sub("", title)
    return _TRAILING_DATE_RE.sub("", title).strip()


def _parse_attendees(sections: dict[str, list[str]]) -> list[Attendee]:
    attendees: list[Attendee] = []
    for row in _table_rows(_section_by_keyword(sections, "قائمة الحضور"))[1:]:
        # # | name | org. Extra columns (an unescaped pipe in the org) fold back in.
        name = row[1] if len(row) >= 3 else (row[0] if row else "")
        org = " | ".join(row[2:]) if len(row) >= 3 else (row[1] if len(row) > 1 else "")
        if name and not _is_placeholder(name):
            attendees.append(Attendee(name=name, org="" if _is_placeholder(org) else org))
    return attendees


def _parse_discussion(sections: dict[str, list[str]]) -> tuple[str, list[str]]:
    summary_parts: list[str] = []
    points: list[str] = []
    for raw in _section_by_keyword(sections, "نقاط نقاش"):
        line = raw.strip()
        if not line or line.startswith("**ملخص") or line == "ملخص الاجتماع":
            continue
        bullet = _BULLET_RE.match(line)
        if bullet:
            if not _is_placeholder(bullet.group(1)):
                points.append(bullet.group(1))
        elif not _is_placeholder(line):
            summary_parts.append(line)
    return "\n".join(summary_parts), points


def _parse_outcomes(sections: dict[str, list[str]]) -> list[Outcome]:
    outcomes: list[Outcome] = []
    for row in _table_rows(_section_by_keyword(sections, "نتائج"))[1:]:
        # task | person | date. The task is the field most likely to carry an
        # unescaped pipe, so extra columns fold back into it (person/date are last two).
        task = row[0] if row else ""
        person = row[1] if len(row) > 1 else ""
        date = row[2] if len(row) > 2 else ""
        if len(row) > 3:
            task = " | ".join(row[: len(row) - 2])
            person = row[len(row) - 2]
            date = row[len(row) - 1]
        if task and not _is_placeholder(task):
            outcomes.append(
                Outcome(
                    task=task,
                    person="" if _is_placeholder(person) else person,
                    date="" if _is_placeholder(date) else date,
                )
            )
    return outcomes


def parse_minutes(md: str) -> Minutes:
    """Parse the 4-section محضر Markdown into a structured model (mirrors
    ``parseMinutes``)."""
    sections = _split_sections(md)
    preamble = sections.get("_preamble", [])

    header_rows = _table_rows(preamble)
    meta = header_rows[1] if len(header_rows) > 1 else []  # row after التاريخ/الوقت/الموقع
    date = meta[0] if len(meta) > 0 else ""
    time = meta[1] if len(meta) > 1 else ""
    location = meta[2] if len(meta) > 2 else ""

    summary, points = _parse_discussion(sections)
    return Minutes(
        title=_parse_title(preamble),
        date=date,
        time=time,
        location=location,
        attendees=_parse_attendees(sections),
        summary=summary,
        points=points,
        outcomes=_parse_outcomes(sections),
    )
