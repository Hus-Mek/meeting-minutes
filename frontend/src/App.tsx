import { useCallback, useEffect, useState } from "react"
import { Loader2, Sparkles } from "lucide-react"
import { toast } from "sonner"
import {
  generateMinutes,
  inspectTranscript,
  type InspectResult,
  type MinutesOptions,
} from "@/lib/api"
import { InputsPane } from "@/components/InputsPane"
import { MinutesPane, type PaneState } from "@/components/MinutesPane"
import { DEFAULT_TEMPLATE_ID } from "@/components/templates/registry"
import { Button } from "@/components/ui/button"
import { ClaudeCodeSetupGuide } from "@/components/ClaudeCodeSetupGuide"
import { isClaudeCodeMissing, isClaudeCodeAuthNeeded } from "@/lib/claudeCode"

function today(): string {
  return new Date().toISOString().slice(0, 10)
}

const DEFAULT_OPTIONS: MinutesOptions = {
  notes: "",
  title: "",
  date: today(),
  time: "",
  location: "",
  attendees: "",
  recap: "",
  backend: "claude-code",
  model: "",
  speakerKey: "speaker",
  startKey: "start",
  endKey: "end",
  textKey: "text",
  speakerMap: "",
}

// Speakers that are not real attendees and should not seed the roster.
const NON_ATTENDEES = new Set(["Unidentified Speaker", "Speaker", ""])

export default function App() {
  const [file, setFile] = useState<File | null>(null)
  const [inspect, setInspect] = useState<InspectResult | null>(null)
  const [inspecting, setInspecting] = useState(false)
  const [inspectError, setInspectError] = useState<string | null>(null)
  const [options, setOptions] = useState<MinutesOptions>(DEFAULT_OPTIONS)
  const [paneState, setPaneState] = useState<PaneState>("input")
  const [minutes, setMinutes] = useState("")
  const [templateId, setTemplateId] = useState(DEFAULT_TEMPLATE_ID)
  const [uploadedTemplate, setUploadedTemplate] = useState<File | null>(null)
  const [setupGuideOpen, setSetupGuideOpen] = useState(false)

  const { speakerKey, startKey, endKey, textKey } = options

  // Re-inspect whenever the file or the field mapping changes.
  useEffect(() => {
    if (!file) {
      setInspect(null)
      setInspectError(null)
      return
    }
    let cancelled = false
    setInspecting(true)
    setInspectError(null)
    inspectTranscript(file, { speakerKey, startKey, endKey, textKey })
      .then((result) => {
        if (cancelled) return
        setInspect(result)
        // Hybrid prefill: seed the roster from speakers (you add organizations),
        // and the title from the detected header — only when those fields are empty.
        setOptions((prev) => {
          const patch: Partial<MinutesOptions> = {}
          if (!prev.attendees.trim()) {
            const roster = result.speakers
              .filter((s) => !NON_ATTENDEES.has(s))
              .join("\n")
            if (roster) patch.attendees = roster
          }
          if (!prev.title.trim() && result.detected.title) patch.title = result.detected.title
          return Object.keys(patch).length ? { ...prev, ...patch } : prev
        })
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setInspect(null)
          setInspectError(err instanceof Error ? err.message : "Could not read file")
        }
      })
      .finally(() => {
        if (!cancelled) setInspecting(false)
      })
    return () => {
      cancelled = true
    }
  }, [file, speakerKey, startKey, endKey, textKey])

  const onChange = useCallback((patch: Partial<MinutesOptions>) => {
    setOptions((prev) => ({ ...prev, ...patch }))
  }, [])

  async function onGenerate() {
    if (!file) {
      toast.error("Add a transcript file first")
      return
    }
    setPaneState("loading")
    try {
      const result = await generateMinutes(file, options)
      setMinutes(result.minutes)
      setPaneState("result")
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "Generation failed"
      // If Claude Code isn't installed OR just needs a login, open the illustrated
      // setup guide instead of a terse toast — it covers install, the one-time login,
      // and the no-setup Cowork fallback.
      if (isClaudeCodeMissing(message) || isClaudeCodeAuthNeeded(message)) {
        setSetupGuideOpen(true)
      } else {
        toast.error(message)
      }
      setPaneState(minutes ? "result" : "input")
    }
  }

  const busy = paneState === "loading"
  const canGenerate = Boolean(file) && !busy && (!inspect || inspect.segment_count > 0)

  return (
    <div className="flex h-screen flex-col bg-paper text-foreground">
      <header className="no-print flex h-14 shrink-0 items-center justify-between border-b border-line px-5">
        <div className="flex items-center gap-2.5">
          <img src="/hawaz-logo.svg" alt="Hawaz" className="h-6 w-auto dark:hidden" />
          <img src="/hawaz-logo-cream.svg" alt="Hawaz" className="hidden h-6 w-auto dark:block" />
          <span className="border-r border-line pr-2.5 text-base font-semibold tracking-tight text-foreground" dir="rtl">
            محضر الاجتماعات
          </span>
        </div>
        <Button onClick={onGenerate} disabled={!canGenerate} className="gap-2">
          {busy ? <Loader2 className="size-4 animate-spin" /> : <Sparkles className="size-4" />}
          {busy ? "Generating…" : "Generate minutes"}
        </Button>
      </header>

      <main className="grid min-h-0 flex-1 grid-cols-1 md:grid-cols-[minmax(0,420px)_1fr]">
        <section className="no-print overflow-y-auto border-b border-line px-5 py-6 md:border-b-0 md:border-r">
          <InputsPane
            file={file}
            onSelectFile={setFile}
            inspect={inspect}
            inspecting={inspecting}
            inspectError={inspectError}
            options={options}
            onChange={onChange}
            templateId={templateId}
            onTemplateIdChange={setTemplateId}
            uploadedTemplate={uploadedTemplate}
            onUploadedTemplateChange={setUploadedTemplate}
            onOpenSetupGuide={() => setSetupGuideOpen(true)}
          />
        </section>
        <section className="min-h-0 overflow-hidden bg-paper">
          <MinutesPane
            state={paneState}
            minutes={minutes}
            title={options.title}
            templateId={templateId}
            uploadedTemplate={uploadedTemplate}
          />
        </section>
      </main>

      <ClaudeCodeSetupGuide
        open={setupGuideOpen}
        onOpenChange={setSetupGuideOpen}
        onUseCowork={() => {
          onChange({ backend: "handoff" })
          setSetupGuideOpen(false)
          toast.success("Switched to Cowork — click Generate again")
        }}
      />
    </div>
  )
}
