// Structured model of the meeting minutes + parse/serialize between it and the
// Markdown the LLM produces. Templates render this model (screen + PDF), so adding
// a client-specific template later is just another renderer over the same data.

export interface Attendee {
  name: string
  org: string
}

export interface Outcome {
  task: string
  person: string // assignee — hidden in the table; mapped to their org
  date: string
}

export interface Minutes {
  title: string
  date: string
  time: string
  location: string
  attendees: Attendee[]
  summary: string
  points: string[]
  outcomes: Outcome[]
}

const isPlaceholder = (s: string) => s.includes("«") || s === "" || /^[-—\s]*$/.test(s)

// Leading honorifics/titles to ignore when matching names (the transcript may
// introduce "م. محمد" or "الدكتور سارة" while the roster stores the bare name).
const HONORIFIC = /^(?:م|د|أ|ا|الاستاذ|الدكتور|المهندس|الشيخ|السيد|السيده|الانسه)\.?\s+/u

/**
 * Normalize an Arabic/Latin name for *matching only* (display always uses the
 * original): drop tashkeel/tatweel, unify alef/ya/ta-marbuta variants, strip a
 * leading honorific, collapse whitespace, and lowercase. Saudi context: names
 * appear with small spelling differences across the two tables.
 */
function normalizeName(s: string): string {
  return s
    .normalize("NFC")
    .replace(/[ً-ْٰـ]/g, "") // tashkeel + superscript alef + tatweel
    .replace(/[أإآ]/g, "ا")
    .replace(/ى/g, "ي")
    .replace(/ة/g, "ه")
    .replace(/\s+/g, " ")
    .trim()
    .replace(HONORIFIC, "")
    .toLowerCase()
}

/**
 * Resolve a task's owner for display. A roster person shows their الجهة (or "—"
 * until it's filled in). Anyone NOT in the roster — a committee, a company, an
 * external party, or a name spelled differently — is shown verbatim rather than
 * dropped, so the document never loses the owner the LLM actually decided.
 */
export function ownerOrg(minutes: Minutes, person: string): string {
  const key = normalizeName(person)
  if (!key) return "—"
  const a = minutes.attendees.find((x) => normalizeName(x.name) === key)
  if (a) {
    const org = a.org.trim()
    return org && org !== "—" ? org : "—"
  }
  return person.trim()
}

function splitSections(md: string): Record<string, string[]> {
  const sections: Record<string, string[]> = { _preamble: [] }
  let current = "_preamble"
  for (const line of md.split("\n")) {
    const m = line.match(/^##\s+(.+?)\s*$/)
    if (m) {
      current = m[1].trim()
      sections[current] = []
    } else {
      sections[current].push(line)
    }
  }
  return sections
}

function sectionByKeyword(sections: Record<string, string[]>, needle: string): string[] {
  const key = Object.keys(sections).find((k) => k.includes(needle))
  return key ? sections[key] : []
}

// Rows of a Markdown pipe-table (the separator line is dropped). Each row is cells.
// Only the outer structural pipes delimit cells: a literal "\|" inside a cell is
// unescaped, not split on, so prose like `cat log \| grep` stays in one cell.
function tableRows(lines: string[]): string[][] {
  const rows: string[][] = []
  for (const line of lines) {
    const t = line.trim()
    if (!t.startsWith("|")) continue
    if (/^\|[\s:|-]+\|?\s*$/.test(t)) continue // separator
    rows.push(
      t
        .replace(/^\|/, "")
        .replace(/\|$/, "")
        .split(/(?<!\\)\|/)
        .map((c) => c.replace(/\\\|/g, "|").trim()),
    )
  }
  return rows
}

export function parseMinutes(md: string): Minutes {
  const sections = splitSections(md)
  const pre = sections._preamble ?? []

  const h1 = pre.find((l) => l.startsWith("# ")) ?? ""
  let title = h1.replace(/^#\s+/, "").replace(/^محضر اجتماع\s*[—-]\s*/, "")
  // Strip only a trailing DATE in parens (starts with an ASCII/Arabic-Indic digit),
  // never an internal/meaningful parenthetical like "(تقني)" or "(يناير-مارس)".
  title = title.replace(/\s*\([\d٠-٩][^)]*\)\s*$/u, "").trim()

  const headerRows = tableRows(pre)
  const meta = headerRows[1] ?? [] // row after the التاريخ/الوقت/الموقع header
  const [date = "", time = "", location = ""] = meta

  const attendees: Attendee[] = []
  for (const row of tableRows(sectionByKeyword(sections, "قائمة الحضور")).slice(1)) {
    // # | name | org. Any extra columns (an unescaped pipe in the org) fold back in.
    const name = row.length >= 3 ? row[1] : row[0]
    const org = row.length >= 3 ? row.slice(2).join(" | ") : (row[1] ?? "")
    if (name && !isPlaceholder(name)) attendees.push({ name, org: isPlaceholder(org) ? "" : org })
  }

  const disc = sectionByKeyword(sections, "نقاط نقاش")
  const summaryParts: string[] = []
  const points: string[] = []
  for (const raw of disc) {
    const line = raw.trim()
    if (!line || line.startsWith("**ملخص") || line === "ملخص الاجتماع") continue
    const bullet = line.match(/^[-*•]\s+(.*)$/)
    if (bullet) {
      if (!isPlaceholder(bullet[1])) points.push(bullet[1])
    } else if (!isPlaceholder(line)) {
      summaryParts.push(line)
    }
  }

  const outcomes: Outcome[] = []
  for (const row of tableRows(sectionByKeyword(sections, "نتائج")).slice(1)) {
    // task | person | date. The task is the prose field most likely to contain an
    // unescaped pipe, so any extra columns fold back into it (person/date are last two).
    let task = row[0] ?? ""
    let person = row[1] ?? ""
    let date2 = row[2] ?? ""
    if (row.length > 3) {
      task = row.slice(0, row.length - 2).join(" | ")
      person = row[row.length - 2]
      date2 = row[row.length - 1]
    }
    if (task && !isPlaceholder(task)) {
      outcomes.push({
        task,
        person: isPlaceholder(person) ? "" : person,
        date: isPlaceholder(date2) ? "" : date2,
      })
    }
  }

  return {
    title,
    date,
    time,
    location,
    attendees,
    summary: summaryParts.join("\n"), // one entry per paragraph; preserved across serialize
    points,
    outcomes,
  }
}

// A table cell: trim, default to "—", and escape any literal pipe so it survives
// re-parsing (tableRows unescapes "\|" back to "|").
const cell = (s: string) => (s && s.trim() ? s.trim() : "—").replace(/\|/g, "\\|")

/** Serialize back to the Markdown contract (for the .md download / Copy). */
export function toMarkdown(m: Minutes): string {
  const heading = m.date ? `${m.title || "اجتماع"} (${m.date})` : m.title || "اجتماع"
  const lines: string[] = [
    `# محضر اجتماع — ${heading}`,
    "",
    "| التاريخ | الوقت | الموقع |",
    "| --- | --- | --- |",
    `| ${cell(m.date)} | ${cell(m.time)} | ${cell(m.location)} |`,
    "",
    "## قائمة الحضور",
    "| # | الاسم | الجهة |",
    "| --- | --- | --- |",
    ...m.attendees.map((a, i) => `| ${i + 1} | ${cell(a.name)} | ${cell(a.org)} |`),
    "",
    "## نقاط نقاش الاجتماع",
    "**ملخص الاجتماع**",
    m.summary
      .split(/\n+/)
      .map((p) => p.trim())
      .filter(Boolean)
      .join("\n\n"), // blank line between paragraphs (round-trips back to "\n"-joined)
    "",
    ...m.points.filter((p) => p.trim()).map((p) => `- ${p}`),
    "",
    "## نتائج الاجتماع",
    "| المهام/ التوصيات | المسؤول | التاريخ المستهدف |",
    "| --- | --- | --- |",
    ...m.outcomes.map((o) => `| ${cell(o.task)} | ${cell(ownerOrg(m, o.person))} | ${cell(o.date)} |`),
    "",
    "شكرًا لكم",
  ]
  return lines.join("\n")
}
