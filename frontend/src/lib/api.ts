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
