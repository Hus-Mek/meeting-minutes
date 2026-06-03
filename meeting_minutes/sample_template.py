"""Generate the bundled, privacy-safe SYNTHETIC .docx template.

The real client template can't live in git (commercial Bahij Janna font, client
logo, real names — privacy hard rule), and docxtpl needs a *concrete* .docx to
fill. So instead of committing a binary look-alike, we commit this generator: a
reviewer can read it and *prove* only synthetic placeholders and a generated
solid-color logo ever appear. The artifact (``SAMPLE_TEMPLATE_PATH``) is produced
on demand and git-ignored.

It reproduces the *format* of the reference محضر (verified from its OOXML):
US-Letter, 0.5" margins, RTL; section headings 18pt #0070B9; table-header rows
teal #00ABAF (white text); the # column grey #D9D9D9; data cells white; the four
tables with the reference's exact column widths; a page-number footer; and a
trailing شكرًا لكم line. Fonts use installed OSS Arabic faces (Noto) as the
Bahij-Janna stand-in — the *real* uploaded template keeps its embedded font.

The docxtpl Jinja tags placed here (``{%tr ... %}`` row loops, ``{%p ... %}``
paragraph loop, ``{{ ... }}`` vars) are what ``docx_render.fill_template`` fills.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Twips

# --- format constants (verified from the reference word/document.xml + styles.xml)
PAGE_W_TW, PAGE_H_TW = 12240, 15840  # US Letter
MARGIN_TW = 720  # 0.5"
HEADER_FOOTER_TW = 288  # 0.2"

TEAL = "00ABAF"  # table-header rows (white text)
GREY = "D9D9D9"  # the narrow # column
WHITE = "FFFFFF"  # data cells
BLUE = "0070B9"  # section headings
WHITE_RGB = RGBColor(0xFF, 0xFF, 0xFF)
BLUE_RGB = RGBColor(0x00, 0x70, 0xB9)

HEADING_PT = 18
BODY_PT = 11
HEADING_FONT = "Noto Kufi Arabic"  # OSS stand-in for Bahij Janna (installed)
BODY_FONT = "Noto Naskh Arabic"

# Exact reference grids (twips). Title uses a clean 3-col split of the 10790 content width.
GRID_TITLE = [3597, 3597, 3596]
GRID_ATTEND = [447, 5386, 4957]
GRID_SUMMARY = [10790]
GRID_OUTCOME = [446, 5954, 2551, 1839]

THANKS = "شكرًا لكم"

SAMPLE_TEMPLATE_PATH = Path(__file__).resolve().parent / "templates" / "sample_arabic_minutes.docx"


# --- low-level OOXML helpers ------------------------------------------------

def _insert_ordered(parent, element, successors: tuple[str, ...]) -> None:
    """Insert *element* before the first existing child whose tag is in
    *successors* (keeps the WordprocessingML schema's child order valid)."""
    for tag in successors:
        nxt = parent.find(qn(tag))
        if nxt is not None:
            nxt.addprevious(element)
            return
    parent.append(element)


def _bidi_para(paragraph) -> None:
    """Mark a paragraph RTL: <w:bidi/> + right alignment."""
    paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    pPr = paragraph._p.get_or_add_pPr()
    for existing in pPr.findall(qn("w:bidi")):
        pPr.remove(existing)
    _insert_ordered(pPr, OxmlElement("w:bidi"), ("w:jc", "w:spacing", "w:ind", "w:rPr"))


def _style_run(run, *, font: str, size_pt: int, bold: bool = False, color: RGBColor | None = None) -> None:
    run.font.name = font
    run.font.size = Pt(size_pt)
    run.font.bold = bold
    if color is not None:
        run.font.color.rgb = color
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.get_or_add_rFonts()
    rFonts.set(qn("w:cs"), font)  # complex-script font for Arabic
    rPr.append(OxmlElement("w:rtl"))  # rtl is near the end of CT_RPr order


def _shade(cell, fill: str) -> None:
    tcPr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    _insert_ordered(tcPr, shd, ("w:tcMar", "w:textDirection", "w:tcFit", "w:vAlign", "w:hideMark"))


def _table_rtl(table) -> None:
    tblPr = table._tbl.tblPr
    _insert_ordered(
        tblPr,
        OxmlElement("w:bidiVisual"),
        ("w:tblW", "w:jc", "w:tblBorders", "w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook"),
    )


def _table_borders(table, *, sz: int = 4, color: str = "BFBFBF") -> None:
    tblPr = table._tbl.tblPr
    borders = OxmlElement("w:tblBorders")
    for edge in ("top", "left", "bottom", "right", "insideH", "insideV"):
        el = OxmlElement(f"w:{edge}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(sz))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)
    _insert_ordered(tblPr, borders, ("w:shd", "w:tblLayout", "w:tblCellMar", "w:tblLook"))


def _set_col_widths(table, widths_tw: list[int]) -> None:
    table.autofit = False
    table.allow_autofit = False
    grid = table._tbl.tblGrid
    for gc in list(grid.findall(qn("w:gridCol"))):
        grid.remove(gc)
    for w in widths_tw:
        gc = OxmlElement("w:gridCol")
        gc.set(qn("w:w"), str(w))
        grid.append(gc)
    for row in table.rows:
        cells = row.cells
        # Skip merged rows (fewer distinct cells than columns) — the grid governs them.
        if len({id(c._tc) for c in cells}) != len(widths_tw):
            continue
        for idx, cell in enumerate(cells):
            cell.width = Twips(widths_tw[idx])


def _clear_runs(paragraph) -> None:
    for r in list(paragraph.runs):
        r._element.getparent().remove(r._element)


def _set_cell(cell, text: str, *, fill: str | None = None, bold: bool = False,
              white: bool = False, font: str = BODY_FONT, size: int = BODY_PT):
    """Write a single styled, RTL paragraph into *cell* (clearing prior content)."""
    if fill:
        _shade(cell, fill)
    p = cell.paragraphs[0]
    _clear_runs(p)
    _bidi_para(p)
    run = p.add_run(text)
    _style_run(run, font=font, size_pt=size, bold=bold, color=WHITE_RGB if white else None)
    return p


def _add_page_number(paragraph) -> None:
    """Append a Word PAGE field to *paragraph* (cached value '1')."""
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), "PAGE")
    r = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "1"
    r.append(t)
    fld.append(r)
    paragraph._p.append(fld)


def write_solid_png(path: str | Path, *, width: int = 280, height: int = 90,
                    rgb: tuple[int, int, int] = (0x00, 0x70, 0xB9)) -> Path:
    """Write a minimal valid solid-color PNG with the standard library only.

    A deliberately synthetic 'logo' — never the client's real image (privacy)."""

    def _chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)  # 8-bit truecolor RGB
    row = b"\x00" + bytes(rgb) * width  # filter byte 0 + RGB pixels
    idat = zlib.compress(row * height, 9)
    png = b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr) + _chunk(b"IDAT", idat) + _chunk(b"IEND", b"")
    path = Path(path)
    path.write_bytes(png)
    return path


# --- section builders -------------------------------------------------------

def _setup_page(section) -> None:
    section.page_width = Twips(PAGE_W_TW)
    section.page_height = Twips(PAGE_H_TW)
    for attr in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(section, attr, Twips(MARGIN_TW))
    section.header_distance = Twips(HEADER_FOOTER_TW)
    section.footer_distance = Twips(HEADER_FOOTER_TW)
    sectPr = section._sectPr
    _insert_ordered(sectPr, OxmlElement("w:bidi"), ("w:rtlGutter", "w:docGrid"))


def _configure_heading_style(document) -> None:
    style = document.styles["Heading 1"]
    style.font.name = HEADING_FONT
    style.font.size = Pt(HEADING_PT)
    style.font.bold = True
    style.font.color.rgb = BLUE_RGB
    rPr = style.element.get_or_add_rPr()
    rPr.get_or_add_rFonts().set(qn("w:cs"), HEADING_FONT)


def _add_heading(document, text: str):
    p = document.add_paragraph(style="Heading 1")
    _bidi_para(p)
    run = p.add_run(text)
    rPr = run._element.get_or_add_rPr()
    rPr.get_or_add_rFonts().set(qn("w:cs"), HEADING_FONT)
    rPr.append(OxmlElement("w:rtl"))
    return p


def _new_table(document, rows: int, cols: int, widths: list[int]):
    table = document.add_table(rows=rows, cols=cols)
    _table_rtl(table)
    _table_borders(table)
    _set_col_widths(table, widths)
    return table


def _build_title_table(document) -> None:
    table = _new_table(document, rows=3, cols=3, widths=GRID_TITLE)
    title_cell = table.cell(0, 0).merge(table.cell(0, 2))
    _set_cell(title_cell, "محضر اجتماع — {{ title }}", bold=True, font=HEADING_FONT, size=14)
    for cell, label in zip(table.rows[1].cells, ("التاريخ", "الوقت", "الموقع")):
        _set_cell(cell, label, bold=True)
    for cell, var in zip(table.rows[2].cells, ("{{ date }}", "{{ time }}", "{{ location }}")):
        _set_cell(cell, var)


# docxtpl's {%tr%}/{%p%} directives *consume* the whole row/paragraph that holds
# them (replacing it with bare jinja), so the for/endfor markers live on their own
# rows and the styled data row in between is what repeats. See the marker rows below.

def _build_attendees_table(document) -> None:
    table = _new_table(document, rows=4, cols=3, widths=GRID_ATTEND)
    for cell, label in zip(table.rows[0].cells, ("#", "الاسم", "الجهة")):
        _set_cell(cell, label, fill=TEAL, bold=True, white=True)
    _set_cell(table.rows[1].cells[0], "{%tr for a in attendees %}")
    data = table.rows[2].cells
    _set_cell(data[0], "{{ loop.index }}", fill=GREY, bold=True)
    _set_cell(data[1], "{{ a.name }}", fill=WHITE)
    _set_cell(data[2], "{{ a.org }}", fill=WHITE)
    _set_cell(table.rows[3].cells[0], "{%tr endfor %}")


def _build_summary_table(document) -> None:
    table = _new_table(document, rows=2, cols=1, widths=GRID_SUMMARY)
    _set_cell(table.cell(0, 0), "ملخص الاجتماع", fill=TEAL, bold=True, white=True)
    body = table.cell(1, 0)
    _shade(body, WHITE)
    _set_cell(body, "{{ summary }}")  # reuses the cell's first paragraph
    # Each bullet is its own <w:p> (the {%p%} markers are consumed like {%tr%}).
    for text in ("{%p for point in points %}", "- {{ point }}", "{%p endfor %}"):
        p = body.add_paragraph()
        _bidi_para(p)
        _style_run(p.add_run(text), font=BODY_FONT, size_pt=BODY_PT)


def _build_outcomes_table(document) -> None:
    table = _new_table(document, rows=4, cols=4, widths=GRID_OUTCOME)
    headers = ("#", "المهام/ التوصيات", "المسؤول", "التاريخ المستهدف")
    for cell, label in zip(table.rows[0].cells, headers):
        _set_cell(cell, label, fill=TEAL, bold=True, white=True)
    _set_cell(table.rows[1].cells[0], "{%tr for o in outcomes %}")
    data = table.rows[2].cells
    _set_cell(data[0], "{{ loop.index }}", fill=GREY, bold=True)
    _set_cell(data[1], "{{ o.task }}", fill=WHITE)
    _set_cell(data[2], "{{ o.owner }}", fill=WHITE)
    _set_cell(data[3], "{{ o.date }}", fill=WHITE)
    _set_cell(table.rows[3].cells[0], "{%tr endfor %}")


def _build_header_logo(document, section) -> None:
    import tempfile

    header = section.header
    header.is_linked_to_previous = False
    p = header.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        logo = write_solid_png(tmp.name)
    try:
        p.add_run().add_picture(str(logo), width=Twips(1700))
    finally:
        logo.unlink(missing_ok=True)


def _build_footer(document, section) -> None:
    footer = section.footer
    footer.is_linked_to_previous = False
    p = footer.paragraphs[0]
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _add_page_number(p)


def build(output_path: str | Path = SAMPLE_TEMPLATE_PATH) -> Path:
    """Generate the synthetic tagged template and save it to *output_path*."""
    document = Document()
    section = document.sections[0]
    _setup_page(section)
    _configure_heading_style(document)
    _build_header_logo(document, section)
    _build_footer(document, section)

    _build_title_table(document)
    _add_heading(document, "قائمة الحضور")
    _build_attendees_table(document)
    _add_heading(document, "نقاط نقاش الاجتماع")
    _build_summary_table(document)
    _add_heading(document, "نتائج الاجتماع")
    _build_outcomes_table(document)

    thanks = document.add_paragraph()
    thanks.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = thanks.add_run(THANKS)
    _style_run(run, font=BODY_FONT, size_pt=BODY_PT, bold=True)

    # Write atomically: save to a sibling temp file then rename, so a concurrent
    # reader (or a crash mid-save) never sees a truncated, unopenable .docx.
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_name(f"{output_path.name}.tmp")
    document.save(str(tmp))
    tmp.replace(output_path)
    return output_path


if __name__ == "__main__":  # pragma: no cover
    print(build())
