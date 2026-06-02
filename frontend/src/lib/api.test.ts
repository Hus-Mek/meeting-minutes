import { afterEach, describe, expect, it, vi } from "vitest"
import { buildMinutesFormData, generateMinutes, type MinutesOptions } from "./api"

const OPTIONS: MinutesOptions = {
  notes: "budget",
  title: "Weekly Sync",
  date: "2026-06-01",
  includeActions: true,
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

  it("serializes include_actions as a string boolean", () => {
    const form = buildMinutesFormData(file(), { ...OPTIONS, includeActions: false })
    expect(form.get("include_actions")).toBe("false")
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
