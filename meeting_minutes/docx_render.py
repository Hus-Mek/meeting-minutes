"""Render محضر Markdown into a user's .docx template (docxtpl), optionally to PDF.

Pipeline: ``parse_minutes`` (mirror of the on-screen model) → ``build_context``
(resolving each owner person→org, the one non-obvious rule) → ``fill_template``
(docxtpl fills the *user's actual* .docx, so its embedded font + logo + colors are
preserved for free). ``docx_to_pdf`` shells out to headless LibreOffice and is
isolated so tests mock it at the boundary — they never spawn ``soffice``.

No LLM / no network is ever touched here: the minutes Markdown is already written.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path

from docx.opc.exceptions import PackageNotFoundError
from docxtpl import DocxTemplate
from jinja2 import TemplateError
from jinja2.sandbox import SandboxedEnvironment

from .minutes_model import Minutes, owner_org, parse_minutes
from .sample_template import SAMPLE_TEMPLATE_PATH, build

SOFFICE_TIMEOUT_S = 120
_DASH = "—"


def build_context(minutes: Minutes) -> dict:
    """Build the docxtpl render context. ``outcomes[i].owner`` is the **resolved
    organization** (never the person) so «المسؤول» matches the owner-mapping
    design; empty الجهة/dates display as "—" exactly like the on-screen template."""
    return {
        "title": minutes.title,
        "date": minutes.date,
        "time": minutes.time,
        "location": minutes.location,
        "attendees": [{"name": a.name, "org": a.org or _DASH} for a in minutes.attendees],
        "summary": minutes.summary,
        "points": list(minutes.points),
        "outcomes": [
            {"task": o.task, "owner": owner_org(minutes, o.person), "date": o.date or _DASH}
            for o in minutes.outcomes
        ],
    }


def fill_template(context: dict, template_path: str | Path) -> bytes:
    """Fill *template_path* with *context* and return the resulting .docx bytes.

    Rendered through a Jinja ``SandboxedEnvironment`` (autoescape on): the template
    comes from an uploaded, untrusted .docx, so the sandbox blocks SSTI/RCE chains
    (e.g. ``{{ ''.__class__.__mro__ }}``) — they raise ``SecurityError`` and are
    rejected. ``autoescape`` also keeps a literal ``& < >`` from corrupting the XML.
    A file that is not a valid/renderable .docx raises ``ValueError`` (so the web
    layer maps it to a clean 400)."""
    try:
        tpl = DocxTemplate(str(template_path))
        tpl.render(context, jinja_env=SandboxedEnvironment(autoescape=True))
    except (PackageNotFoundError, TemplateError) as exc:
        raise ValueError(f"invalid or unrenderable .docx template: {exc}") from exc
    buf = BytesIO()
    tpl.save(buf)
    return buf.getvalue()


def render_docx(minutes_md: str, template_path: str | Path | None = None) -> bytes:
    """Parse the محضر Markdown and render it into *template_path* (defaults to the
    bundled synthetic template, generated on demand)."""
    path = Path(template_path) if template_path else ensure_sample_template()
    context = build_context(parse_minutes(minutes_md))
    return fill_template(context, path)


def soffice_binary() -> str | None:
    """Path to a headless LibreOffice binary, or None when unavailable."""
    return shutil.which("soffice") or shutil.which("libreoffice")


def docx_to_pdf(docx_bytes: bytes) -> bytes:
    """Convert .docx bytes to PDF via headless LibreOffice. Raises if unavailable
    or the conversion fails."""
    soffice = soffice_binary()
    if not soffice:
        raise RuntimeError("LibreOffice (soffice) is not installed; cannot convert to PDF")

    with tempfile.TemporaryDirectory() as tmp:
        in_path = os.path.join(tmp, "minutes.docx")
        out_path = os.path.join(tmp, "minutes.pdf")
        with open(in_path, "wb") as f:
            f.write(docx_bytes)
        try:
            result = subprocess.run(  # noqa: S603 — fixed argv, no shell, validated binary
                [soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, in_path],
                capture_output=True,
                timeout=SOFFICE_TIMEOUT_S,
                check=False,
            )
        except subprocess.TimeoutExpired:
            # TimeoutExpired is not a RuntimeError; re-raise as one so the web layer
            # maps it to a clean 503 instead of a 500 traceback.
            raise RuntimeError(
                f"LibreOffice PDF conversion timed out after {SOFFICE_TIMEOUT_S}s"
            ) from None
        # LibreOffice can exit 0 yet produce nothing, so verify the file exists.
        if result.returncode != 0 or not os.path.exists(out_path):
            detail = result.stderr.decode("utf-8", "replace").strip()[:500]
            raise RuntimeError(f"LibreOffice PDF conversion failed (rc={result.returncode}): {detail}")
        with open(out_path, "rb") as f:
            return f.read()


def ensure_sample_template() -> Path:
    """Generate the bundled synthetic template on first use; return its path."""
    if not SAMPLE_TEMPLATE_PATH.exists():
        build(SAMPLE_TEMPLATE_PATH)
    return SAMPLE_TEMPLATE_PATH
