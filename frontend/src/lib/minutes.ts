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

/** The الجهة of a task's assignee, or "—" until it's filled in. The person is never shown. */
export function ownerOrg(minutes: Minutes, person: string): string {
  const a = minutes.attendees.find((x) => x.name.trim() === person.trim())
  const org = a?.org?.trim()
  return org && org !== "—" ? org : "—"
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
function tableRows(lines: string[]): string[][] {
  const rows: string[][] = []
  for (const line of lines) {
    const t = line.trim()
    if (!t.startsWith("|")) continue
    if (/^\|[\s:|-]+\|?\s*$/.test(t)) continue // separator
    rows.push(
      t
        .replace(/^\||\|$/g, "")
        .split("|")
        .map((c) => c.trim()),
    )
  }
  return rows
}

export function parseMinutes(md: string): Minutes {
  const sections = splitSections(md)
  const pre = sections._preamble ?? []

  const h1 = pre.find((l) => l.startsWith("# ")) ?? ""
  let title = h1.replace(/^#\s+/, "").replace(/^محضر اجتماع\s*[—-]\s*/, "")
  title = title.replace(/\s*\(.*\)\s*$/, "").trim()

  const headerRows = tableRows(pre)
  const meta = headerRows[1] ?? [] // row after the التاريخ/الوقت/الموقع header
  const [date = "", time = "", location = ""] = meta

  const attendees: Attendee[] = []
  for (const row of tableRows(sectionByKeyword(sections, "قائمة الحضور")).slice(1)) {
    const name = row.length >= 3 ? row[1] : row[0]
    const org = row.length >= 3 ? row[2] : (row[1] ?? "")
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
    const [task = "", person = "", date2 = ""] = row
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
    summary: summaryParts.join(" "),
    points,
    outcomes,
  }
}

const cell = (s: string) => (s && s.trim() ? s.trim() : "—")

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
    m.summary,
    "",
    ...m.points.map((p) => `- ${p}`),
    "",
    "## نتائج الاجتماع",
    "| المهام/ التوصيات | المسؤول | التاريخ المستهدف |",
    "| --- | --- | --- |",
    ...m.outcomes.map((o) => `| ${cell(o.task)} | ${cell(ownerOrg(m, o.person))} | ${cell(o.date)} |`),
  ]
  return lines.join("\n")
}
