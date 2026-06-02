// Build a standalone, print-tuned HTML document from the rendered minutes template
// (used for PDF export / "Save as PDF"). The body HTML is the DefaultTemplate output.
import amiriRegular from "@fontsource/amiri/files/amiri-arabic-400-normal.woff2?url"
import amiriBold from "@fontsource/amiri/files/amiri-arabic-700-normal.woff2?url"
import frauncesLatin from "@fontsource-variable/fraunces/files/fraunces-latin-wght-normal.woff2?url"

function escapeHtml(s: string): string {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!)
}

// Embed the app's OWN bundled fonts (same origin) instead of a CDN, so the PDF
// renders Arabic in Amiri even offline / on a restricted corporate network. URLs
// are resolved to absolute because the print popup is an about:blank document.
function fontFaceCss(): string {
  const abs = (u: string) => new URL(u, document.baseURI).href
  return `
@font-face { font-family:'Amiri'; font-weight:400; font-style:normal; font-display:swap;
  src:url('${abs(amiriRegular)}') format('woff2'); }
@font-face { font-family:'Amiri'; font-weight:700; font-style:normal; font-display:swap;
  src:url('${abs(amiriBold)}') format('woff2'); }
@font-face { font-family:'Fraunces'; font-weight:100 900; font-style:normal; font-display:swap;
  src:url('${abs(frauncesLatin)}') format('woff2'); }
`
}

// Mirrors the editorial + template styles, scoped for print (mm in cm/pt units).
const DOC_CSS = `
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
<style>${fontFaceCss()}${DOC_CSS}</style></head>
<body>${bodyHtml}</body></html>`
}
