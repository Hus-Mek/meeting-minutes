# Handover — "Use my own .docx template, rendered exactly" feature

> Paste this whole file to the implementing agent. It is self-contained.

## Mission

Let the user **upload their own Word `.docx` template** and have generated meeting
minutes rendered **exactly like that document** — same layout, fonts, colors,
logo, tables, header/footer. For the **POC**, the bar is: reproduce **one specific
real template** (path below) pixel-faithfully and produce a downloadable file the
user can hand to stakeholders.

The data side is already done (see "What already exists"). This feature is almost
entirely **(a) take their .docx as the render target, (b) inject the generated
content into it, (c) wire upload + download in the UI.**

## The target template (the POC must match this exactly)

File (FORMAT REFERENCE ONLY — see Privacy below, do NOT copy its content into the repo):
`/home/boypickle/Downloads/_20260511 محضر اجتماع مصفوفة إجراءات متابعة وقياس الالتزام (2).docx`

Extracted structure (RTL, Arabic):

- **Page:** US Letter (8.5"×11", 12240×15840 twips), margins 0.5" all sides, header/footer 0.2".
- **Header:** contains a **logo** (`word/media/image1.png` + svg). Keep it.
- **Footer:** `شكرًا لكم` + page number.
- **Fonts:** section headings (Heading1) = **"Bahij Janna" 18pt, color `#0070B9` (blue)**; body default ≈ 11pt. Bahij Janna is a commercial Arabic font — it lives inside the .docx, so the docx-fill approach preserves it for free; an HTML approach needs the font file or a close fallback (e.g. Cairo/Tajawal/Amiri).
- **Brand colors:** table-header rows = teal **`#00ABAF`** (white text); the narrow `#` column = grey **`#D9D9D9`**; data cells = white `#FFFFFF`.
- **Body order (4 tables + 3 headings):**
  1. **Title/meta table** (5 cols: 2 are hairline spacers): row1 = title `محضر اجتماع …` merged across; row2 = `التاريخ | الوقت | الموقع`; row3 = their values.
  2. Heading `قائمة الحضور`.
  3. **Attendees table** (3 cols ≈ `#`/الاسم/الجهة, widths 447/5386/4957 tw): teal header (`الاسم` spans `#`+name, then `الجهة`); ~10 data rows; `#` cell grey. Names are **Arabic** (e.g. مشاري الزنبقي), الجهة e.g. `هيئة الحكومة الرقمية`.
  4. Heading `نقاط نقاش الاجتماع`.
  5. **Summary table** (1 col): teal header `ملخص الاجتماع`; one white cell holding the summary paragraph(s) + discussion bullets.
  6. Heading `نتائج الاجتماع`.
  7. **Outcomes table** (4 cols `#`/المهام-التوصيات/المسؤول/التاريخ المستهدف, widths 446/5954/2551/1839 tw): teal header (`المهام/ التوصيات` spans `#`+task); `#` grey. **`المسؤول` is an ORGANIZATION** (e.g. `شركة هوّز`), not a person — this matches the existing owner-mapping design.
  8. Footer line `شكرًا لكم`.

(Re-extract anytime: a .docx is a zip; parse `word/document.xml` with the
`w:` namespace. `python-docx` is NOT installed in `.venv` yet.)

## Recommended approach

**Approach A — fill the user's .docx (DO THIS for the POC). True fidelity.**
The output IS their document, so fonts/logo/colors/borders are exact.
- Library: **`docxtpl`** (python-docx-template, Jinja over python-docx). Add to deps.
- Two ways to mark where content goes:
  - **(A1) Tagged template (most reliable):** user adds Jinja tags to their .docx —
    `{{date}}`, `{{time}}`, `{{location}}`, `{%tr for a in attendees %}` rows, `{{summary}}`, `{%tr for o in outcomes %}`. Ship a tagged copy of THIS template as the POC default.
  - **(A2) Auto-fill untouched .docx:** detect the known tables by header text
    (`قائمة الحضور`/`المسؤول`/`ملخص الاجتماع`) with `python-docx`, clone the styled
    data row, and append one per attendee/outcome. More magical, no user editing —
    nicer UX, more code. Recommend A1 for the POC, A2 as a follow-up.
- **PDF:** convert the filled .docx with **LibreOffice headless**
  (`soffice --headless --convert-to pdf --outdir … file.docx`) — preserves fidelity.
  Check if `soffice`/`libreoffice` is installed; if not, .docx download alone is fine for the POC.

**Approach B — match it in the HTML template (`DefaultTemplate.tsx`).** Faster for an
on-screen preview, but never pixel-exact to Word (font + logo + borders drift).
Optional: use B for the live preview and A for the downloadable artifact.

**Recommendation:** A1 (download an exact .docx) for the POC; optionally also retune
`DefaultTemplate.tsx` to this template's colors/columns so the on-screen preview looks right.

## What already exists (DO NOT rebuild)

- **Data model + (de)serialize:** `frontend/src/lib/minutes.ts` — `Minutes` type
  (`title,date,time,location,attendees[],summary,points[],outcomes[]`),
  `parseMinutes(md)`, `toMarkdown(m)`, `ownerOrg(m, person)` (maps assignee → org,
  Arabic-normalized; non-roster owner shown verbatim).
- **Owner mapping:** LLM emits the assignee's Arabic person name; the app resolves it
  to their الجهة from قائمة الحضور. So `outcomes[i].person` → `ownerOrg()` = the
  organization that belongs in `المسؤول` (e.g. شركة هوّز). Use the **resolved org** when filling the outcomes table.
- **Prompt contract:** `meeting_minutes/prompt.py` — produces exactly the 4-section
  Markdown the model expects, Arabic names (just added), `شكرًا لكم` footer, pipe-escaping.
- **Backend:** `meeting_minutes/web.py` FastAPI — `POST /api/minutes` returns
  `{minutes: <markdown>, meta}`. Add the docx render endpoint near it.
- **Frontend template system:** `components/templates/{DefaultTemplate.tsx,registry.ts}`
  + the picker in `components/MinutesPane.tsx` (toolbar `Select`). Extend the registry
  to represent uploaded/predefined client templates; add an upload control + a
  "Download .docx (my template)" action. `App.tsx` holds `minutes` (the markdown).

## Suggested plan (phased)

1. **Backend render module** `meeting_minutes/docx_render.py`: `render_docx(minutes_md_or_model, template_path) -> bytes`. Parse the markdown to the model (mirror `parseMinutes`, or expose the model from the engine), fill via `docxtpl`. Unit-test against a **synthetic** tagged template.
2. **Endpoint** `POST /api/minutes/docx` in `web.py`: body = `{minutes, template_id|upload}`, returns the `.docx` (and `?format=pdf` via LibreOffice if available). Keep it a separate module to minimize merge pain (see Parallel session).
3. **Template storage:** start with bundled predefined templates (the POC one, tagged) keyed by id; add per-client saved uploads later ("select a client → their template").
4. **Frontend:** upload `.docx`, list templates in the picker, "Download (.docx / PDF)" button that calls the endpoint with the current `minutes`.
5. (Optional) Retune `DefaultTemplate.tsx` to this template's teal/grey/columns for an accurate live preview.

## Hard rules & constraints (NON-NEGOTIABLE)

- **Claude Code must NEVER call OpenRouter.** The app's OpenRouter backend is the
  user's separate metered key; all tests mock the LLM client. Never run anything that
  hits OpenRouter during dev. (Engine details in `meeting_minutes/llm.py`.)
- **Saudi Arabic context:** names in Arabic; `المسؤول` = the organization.
- **Privacy:** the files in `~/Downloads` are **format references only**. Do NOT copy
  their real content into the repo, fixtures, or tests. Build a **synthetic** tagged
  template + synthetic data for tests (cf. `tests/fixtures/sample_transcript.txt`).
- **Git:** branch off and commit *specific* files (not `-A`); **no Claude/AI
  attribution** in commits or PRs; author `Hus-Mek <obaadahmm@gmail.com>`; commit +
  push after each meaningful chunk.
- **Obsidian:** write a session note to
  `/media/boypickle/Windows/Users/husam/Documents/ObsidianVault/Claude Sessions/`.
- **Testing:** TDD, 80%+ coverage; mock LibreOffice/heavy IO in unit tests.
- **⚠️ Parallel session active:** another agent is building backend features (local
  LLM backends LM Studio/Ollama/claude-code; "teams ingestion + RBAC" on branch
  `feat/teams-ingestion-rbac`). It actively edits `web.py`, `minutes.py`, `cli.py`,
  `InputsPane.tsx`, `docs/`, `scripts/`. **Check `git status`/branch first**, keep the
  docx feature in a **new module + new endpoint** to avoid collisions, and prefer a
  dedicated branch. `main` currently has the template HTML system + Arabic-names fix.

## Confirm with the user before/while building

1. **Output:** downloadable **.docx** (exact) — and/or **PDF**, and/or just an accurate on-screen preview?
2. **Tagging:** OK to add Jinja tags to a copy of your .docx (A1), or must it ingest your file untouched (A2 auto-detect)?
3. **Reuse:** one-off upload each time, or save templates **per client** and pick by client (the original vision)?
4. **Fonts/logo:** keep Bahij Janna + the header logo from the .docx as-is (yes for docx-fill).

## Verification

- Unit: model → filled synthetic .docx (assert tags replaced, row counts, owner=org).
- `soffice --headless --convert-to pdf` smoke if installed; else skip with a logged note.
- Live (no keys): server still serves; `POST /api/minutes backend=openrouter` with no key → clean 500 (no OpenRouter call). Render endpoint works from a pasted `minutes` markdown without any LLM call.
- Open the produced .docx in Word/LibreOffice and diff visually against the target template.
