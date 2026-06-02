// Build a standalone, print-tuned HTML document from the rendered minutes template
// (used for PDF export / "Save as PDF"). The body HTML is the DefaultTemplate output.

function escapeHtml(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!)
}

// Mirrors the editorial + template styles, scoped for print (mm in cm/pt units).
const DOC_CSS = `
@import url('https://fonts.googleapis.com/css2?family=Amiri:wght@400;700&family=Fraunces:opsz,wght@9..144,600&family=Source+Serif+4&display=swap');
@page { margin: 22mm 20mm; }
* { box-sizing: border-box; }
body { margin: 0; background: #fff; color: #1a1a17;
  font-family: 'Source Serif 4','Amiri',Georgia,serif; }
.minutes-doc { max-width: 740px; margin: 0 auto; font-size: 12pt; line-height: 1.85; }
.minutes-doc[dir="rtl"], .tmpl-default { font-size: 13pt; line-height: 1.95; }
h2 { font-family: 'Fraunces','Amiri',serif; font-size: 15pt; margin: 16pt 0 6pt;
  padding-bottom: 4pt; border-bottom: 1px solid #e6e3da; }
p { margin: 0 0 8pt; }
ul { margin: 0; padding-inline-start: 18pt; }
li { margin: 3pt 0; } li::marker { color: #b0411e; }
table { width: 100%; border-collapse: collapse; margin: 6pt 0 14pt; page-break-inside: avoid; }
th, td { border: 1px solid #e6e3da; padding: 5pt 8pt; vertical-align: top; text-align: start; }
thead th { background: #f3e4dc; font-weight: 600; }
.mm-hdr th, .mm-hdr td { text-align: center; }
.mm-title { font-family: 'Amiri',serif; font-weight: 700; font-size: 16pt; background: #f3e4dc; }
.mm-num { width: 22pt; text-align: center; color: #6b6b63; }
.mm-owner { font-weight: 600; }
`

/** Wrap rendered template HTML in a standalone document for PDF/HTML export. */
export function buildStandaloneHtml(bodyHtml: string, title: string): string {
  return `<!doctype html>
<html lang="ar" dir="rtl"><head><meta charset="utf-8">
<title>${escapeHtml(title || "Meeting Minutes")}</title>
<style>${DOC_CSS}</style></head>
<body>${bodyHtml}</body></html>`
}
