import { afterEach, describe, expect, it, vi } from "vitest"
import {
  buildDocxFormData,
  buildMinutesFormData,
  exportMinutesDocx,
  generateMinutes,
  type MinutesOptions,
} from "./api"

const OPTIONS: MinutesOptions = {
  notes: "budget",
  title: "Weekly Sync",
  date: "2026-06-01",
  time: "11:30–12:30",
  location: "عن بعد",
  attendees: "مشاري — هيئة",
  recap: "Action Items: ...",
  backend: "groq",
  model: "",
  speakerKey: "speaker",
  startKey: "start",
  endKey: "end",
  textKey: "text",
  speakerMap: "SPEAKER_00=Alice",
}

function file() {
  return new File(["[]"], "t.json", { type: "application/json" })
}

describe("buildMinutesFormData", () => {
  it("includes the transcript, notes, and field keys", () => {
    const form = buildMinutesFormData(file(), OPTIONS)
    expect((form.get("transcript") as File).name).toBe("t.json")
    expect(form.get("notes")).toBe("budget")
    expect(form.get("speaker_key")).toBe("speaker")
    expect(form.get("speaker_map")).toBe("SPEAKER_00=Alice")
  })

  it("includes the metadata fields (time, location, attendees)", () => {
    const form = buildMinutesFormData(file(), OPTIONS)
    expect(form.get("time")).toBe("11:30–12:30")
    expect(form.get("location")).toBe("عن بعد")
    expect(form.get("attendees")).toBe("مشاري — هيئة")
    expect(form.get("recap")).toBe("Action Items: ...")
  })

  it("falls back to 'Meeting' when title is empty", () => {
    const form = buildMinutesFormData(file(), { ...OPTIONS, title: "" })
    expect(form.get("title")).toBe("Meeting")
  })
})

describe("generateMinutes", () => {
  afterEach(() => vi.restoreAllMocks())

  it("returns minutes on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ minutes: "## Topic", meta: { backend: "groq", segments: 1 } }), {
          status: 200,
        }),
      ),
    )
    const result = await generateMinutes(file(), OPTIONS)
    expect(result.minutes).toBe("## Topic")
  })

  it("throws the server error message on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ error: "transcript contains no segments" }), { status: 400 }),
      ),
    )
    await expect(generateMinutes(file(), OPTIONS)).rejects.toThrow("no segments")
  })
})

describe("buildDocxFormData", () => {
  it("includes the minutes, default format, and filename", () => {
    const form = buildDocxFormData("## Topic")
    expect(form.get("minutes")).toBe("## Topic")
    expect(form.get("format")).toBe("docx")
    expect(form.get("filename")).toBe("minutes")
    expect(form.get("template")).toBeNull()
  })

  it("includes the uploaded template, chosen format, and filename", () => {
    const template = new File(["PK"], "client.docx")
    const form = buildDocxFormData("## Topic", { template, format: "pdf", filename: "محضر" })
    expect((form.get("template") as File).name).toBe("client.docx")
    expect(form.get("format")).toBe("pdf")
    expect(form.get("filename")).toBe("محضر")
  })
})

describe("exportMinutesDocx", () => {
  afterEach(() => vi.restoreAllMocks())

  it("returns the file blob on success", async () => {
    // jsdom's Response.blob() is flaky, so mock the parts exportMinutesDocx uses.
    const blob = new Blob([new Uint8Array([0x50, 0x4b])])
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, blob: async () => blob })))
    const result = await exportMinutesDocx("## Topic")
    expect(result.size).toBe(2)
  })

  it("throws the server error message on failure", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ error: "invalid or unrenderable .docx template" }), {
          status: 400,
        }),
      ),
    )
    await expect(exportMinutesDocx("## Topic")).rejects.toThrow("unrenderable")
  })
})
