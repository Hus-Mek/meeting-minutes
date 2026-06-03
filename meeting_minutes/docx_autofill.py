"""Fill an UNTOUCHED user .docx by auto-detecting its tables — no Jinja tags.

The user uploads their real template as-is; we locate each table by the Arabic
header text it already contains (قائمة الحضور / المسؤول / ملخص الاجتماع / التاريخ),
clone the *styled* sample data row's ``<w:tr>`` (a deepcopy carries shading,
borders, fonts, and RTL along for free), write the generated values into the
existing runs (so they inherit the run's formatting), and drop the sample row.

Result: the output IS the user's document — same logo, fonts, colors, header and
footer — with the minutes filled in. No manual tagging, exact fidelity.
"""

from __future__ import annotations

import copy
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.opc.exceptions import PackageNotFoundError
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph

from .minutes_model import Minutes, owner_org, parse_minutes

_DASH = "—"


# --- low-level cell/paragraph writers (preserve the existing run's formatting) ---

def _set_paragraph_text(paragraph: Paragraph, text: str) -> None:
    if paragraph.runs:
        paragraph.runs[0].text = text
        for extra in paragraph.runs[1:]:
            extra.text = ""
    else:
        paragraph.add_run(text)


def _set_cell_text(cell, text: str) -> None:
    p = cell.paragraphs[0]
    # Drop any Word list auto-numbering (numPr) so our literal value (e.g. the #
    # column index) isn't rendered *in addition to* an auto-number.
    pPr = p._p.find(qn("w:pPr"))
    if pPr is not None:
        numPr = pPr.find(qn("w:numPr"))
        if numPr is not None:
            pPr.remove(numPr)
    _set_paragraph_text(p, text)
    for extra in cell.paragraphs[1:]:
        extra._p.getparent().remove(extra._p)


# --- table discovery ---

def _header_text(table) -> str:
    return " ".join(c.text for c in table.rows[0].cells)


def _find_table(doc, *needles: str):
    """First table whose header row contains every needle substring."""
    for table in doc.tables:
        header = _header_text(table)
        if all(n in header for n in needles):
            return table
    return None


# --- repeating tables (attendees, outcomes) ---

def _fill_repeating_table(table, rows_data: list[tuple[str, ...]], *, header_rows: int = 1) -> None:
    """Replace the table's data rows with ``rows_data``, cloning the first existing
    data row so every generated row keeps its exact styling."""
    body = table.rows[header_rows:]
    if not body:
        return  # nothing to clone from; leave the table untouched
    sample_tr = body[0]._tr
    parent = sample_tr.getparent()
    for extra in body[1:]:  # drop any other pre-existing sample rows
        parent.remove(extra._tr)
    for data in rows_data:
        clone = copy.deepcopy(sample_tr)
        parent.append(clone)
        cells = table.rows[-1].cells
        for cell, value in zip(cells, data):
            _set_cell_text(cell, value)
    parent.remove(sample_tr)


def _fill_attendees(doc, minutes: Minutes) -> bool:
    table = _find_table(doc, "الاسم", "الجهة")
    if table is None:
        return False
    rows = [
        (str(i), a.name, a.org or _DASH)
        for i, a in enumerate(minutes.attendees, start=1)
    ]
    _fill_repeating_table(table, rows)
    return True


def _fill_outcomes(doc, minutes: Minutes) -> bool:
    table = _find_table(doc, "المسؤول")
    if table is None:
        return False
    rows = [
        (str(i), o.task, owner_org(minutes, o.person), o.date or _DASH)
        for i, o in enumerate(minutes.outcomes, start=1)
    ]
    _fill_repeating_table(table, rows)
    return True


# --- meta table (title + التاريخ/الوقت/الموقع) ---

def _find_meta_table(doc):
    """The meta table holds the exact labels التاريخ/الوقت/الموقع (its first row is
    the merged title, so a header-only search would miss it and match the outcomes
    table's «التاريخ المستهدف» instead). Scan every cell for the three labels."""
    for table in doc.tables:
        texts = {c.text.strip() for row in table.rows for c in row.cells}
        if {"التاريخ", "الوقت", "الموقع"} <= texts:
            return table
    return None


def _fill_meta(doc, minutes: Minutes) -> None:
    table = _find_meta_table(doc)
    if table is None:
        return
    labels = {"التاريخ": minutes.date, "الوقت": minutes.time, "الموقع": minutes.location}
    for ri, row in enumerate(table.rows):
        cells = row.cells
        keys = [c.text.strip() for c in cells]
        # The title cell (merged across the top) — keep the literal prefix, append the title.
        for c in cells:
            if "محضر اجتماع" in c.text and minutes.title:
                _set_cell_text(c, f"محضر اجتماع — {minutes.title}")
        if any(k in labels for k in keys) and ri + 1 < len(table.rows):
            value_row = table.rows[ri + 1]
            for ci, key in enumerate(keys):
                if key in labels:
                    _set_cell_text(value_row.cells[ci], labels[key] or _DASH)
            break


# --- summary block (paragraph + bullet points in one cell) ---

def _fill_summary(doc, minutes: Minutes) -> None:
    table = _find_table(doc, "ملخص الاجتماع")
    if table is None or len(table.rows) < 2:
        return
    body = table.rows[1].cells[0]
    first = body.paragraphs[0]
    _set_paragraph_text(first, minutes.summary or _DASH)
    for extra in body.paragraphs[1:]:  # clear any sample body paragraphs
        extra._p.getparent().remove(extra._p)
    # Re-add each discussion point as its own paragraph, cloning the summary
    # paragraph's properties so RTL/font/size carry over.
    anchor = first._p
    for point in minutes.points:
        clone = copy.deepcopy(first._p)
        anchor.addnext(clone)
        anchor = clone
        _set_paragraph_text(Paragraph(clone, body), f"- {point}")


def autofill_docx(minutes_md: str, template_path: str | Path) -> bytes:
    """Parse the محضر Markdown and inject it into an untouched user .docx by
    auto-detecting its tables. Returns the filled .docx bytes."""
    minutes = parse_minutes(minutes_md)
    try:
        doc = Document(str(template_path))
    except PackageNotFoundError as exc:
        raise ValueError(f"uploaded template is not a valid .docx: {exc}") from exc
    _fill_meta(doc, minutes)
    _fill_attendees(doc, minutes)
    _fill_summary(doc, minutes)
    _fill_outcomes(doc, minutes)
    buf = BytesIO()
    doc.save(buf)
    return buf.getvalue()
