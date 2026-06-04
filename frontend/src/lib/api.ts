// Typed client for the FastAPI backend. Same-origin in prod; Vite proxies /api in dev.

export interface FieldKeys {
  speakerKey: string
  startKey: string
  endKey: string
  textKey: string
}

export interface MinutesOptions extends FieldKeys {
  notes: string
  title: string
  date: string
  time: string
  location: string
  attendees: string
  recap: string
  backend: string
  model: string
  speakerMap: string
}

export interface InspectResult {
  segment_count: number
  speakers: string[]
  duration: string
  detected: { title: string; date: string }
}

export interface MinutesResult {
  minutes: string
  meta: { backend: string; segments: number }
}

function appendFieldKeys(form: FormData, keys: FieldKeys): void {
  form.append("speaker_key", keys.speakerKey)
  form.append("start_key", keys.startKey)
  form.append("end_key", keys.endKey)
  form.append("text_key", keys.textKey)
}

/** Build the multipart body for /api/minutes. Exported for unit testing. */
export function buildMinutesFormData(file: File, opts: MinutesOptions): FormData {
  const form = new FormData()
  form.append("transcript", file)
  form.append("notes", opts.notes)
  form.append("title", opts.title || "Meeting")
  form.append("date", opts.date)
  form.append("time", opts.time)
  form.append("location", opts.location)
  form.append("attendees", opts.attendees)
  form.append("recap", opts.recap)
  form.append("backend", opts.backend)
  form.append("model", opts.model)
  form.append("speaker_map", opts.speakerMap)
  appendFieldKeys(form, opts)
  return form
}

async function unwrap<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = `Request failed (${res.status})`
    try {
      const body = await res.json()
      if (body?.error) message = body.error
    } catch {
      // non-JSON error body; keep the status-based message
    }
    throw new Error(message)
  }
  return (await res.json()) as T
}

export async function inspectTranscript(file: File, keys: FieldKeys): Promise<InspectResult> {
  const form = new FormData()
  form.append("transcript", file)
  appendFieldKeys(form, keys)
  return unwrap<InspectResult>(await fetch("/api/inspect", { method: "POST", body: form }))
}

export async function generateMinutes(file: File, opts: MinutesOptions): Promise<MinutesResult> {
  const form = buildMinutesFormData(file, opts)
  return unwrap<MinutesResult>(await fetch("/api/minutes", { method: "POST", body: form }))
}

export type DocxFormat = "docx" | "pdf"

export interface DocxExportOptions {
  template?: File | null // the user's own .docx template; falls back to the bundled one
  format?: DocxFormat
  filename?: string
}

/** Build the multipart body for /api/minutes/docx. Exported for unit testing. */
export function buildDocxFormData(minutesMarkdown: string, opts: DocxExportOptions = {}): FormData {
  const form = new FormData()
  form.append("minutes", minutesMarkdown)
  if (opts.template) form.append("template", opts.template)
  form.append("format", opts.format ?? "docx")
  form.append("filename", opts.filename || "minutes")
  return form
}

/** Render minutes Markdown into a .docx/PDF on the server and return the file blob. */
export async function exportMinutesDocx(
  minutesMarkdown: string,
  opts: DocxExportOptions = {},
): Promise<Blob> {
  const res = await fetch("/api/minutes/docx", {
    method: "POST",
    body: buildDocxFormData(minutesMarkdown, opts),
  })
  if (!res.ok) {
    let message = `Export failed (${res.status})`
    try {
      const body = await res.json()
      if (body?.error) message = body.error
    } catch {
      // non-JSON error body (e.g. a binary); keep the status-based message
    }
    throw new Error(message)
  }
  return res.blob()
}

/** Open an interactive Claude Code login window on the local machine (used by the
 *  setup guide's "Log in to Claude" button). */
export async function claudeLogin(): Promise<void> {
  const res = await fetch("/api/claude/login", { method: "POST" })
  await unwrap<{ status: string }>(res)
}

export interface ClaudeStatus {
  available: boolean
  path: string | null
}

/** Startup probe: whether a working Claude Code CLI is available on this machine. */
export async function getClaudeStatus(): Promise<ClaudeStatus> {
  return unwrap<ClaudeStatus>(await fetch("/api/claude/status"))
}

export interface UpdateInfo {
  current: string
  latest: string | null
  update_available: boolean
  html_url: string | null
  download_url: string | null
}

/** Startup probe: whether a newer release is published on GitHub. The backend
 *  checker fails silently, so this resolves to `update_available: false` on any
 *  network error rather than throwing. */
export async function checkForUpdate(): Promise<UpdateInfo> {
  return unwrap<UpdateInfo>(await fetch("/api/update/check"))
}
