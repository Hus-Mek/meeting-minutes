import type { InspectResult, MinutesOptions } from "@/lib/api"
import { Dropzone } from "@/components/Dropzone"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"

interface InputsPaneProps {
  file: File | null
  onSelectFile: (file: File | null) => void
  inspect: InspectResult | null
  inspecting: boolean
  inspectError: string | null
  options: MinutesOptions
  onChange: (patch: Partial<MinutesOptions>) => void
}

const SECTION_LABEL = "text-xs font-semibold uppercase tracking-wide text-muted-foreground"

export function InputsPane({
  file,
  onSelectFile,
  inspect,
  inspecting,
  inspectError,
  options,
  onChange,
}: InputsPaneProps) {
  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-2">
        <Label className={SECTION_LABEL}>Transcript</Label>
        <Dropzone
          file={file}
          onSelect={onSelectFile}
          inspect={inspect}
          inspecting={inspecting}
          inspectError={inspectError}
        />
      </section>

      <section className="flex flex-col gap-2">
        <Label htmlFor="title" className={SECTION_LABEL}>
          عنوان الاجتماع · Title
        </Label>
        <Input
          id="title"
          dir="auto"
          value={options.title}
          onChange={(e) => onChange({ title: e.target.value })}
          placeholder="اجتماع متابعة…"
          className="bg-card"
        />
      </section>

      <section className="grid grid-cols-3 gap-3">
        <LabeledInput
          id="date"
          label="التاريخ · Date"
          value={options.date}
          onChange={(v) => onChange({ date: v })}
          placeholder="11/5/2026"
        />
        <LabeledInput
          id="time"
          label="الوقت · Time"
          value={options.time}
          onChange={(v) => onChange({ time: v })}
          placeholder="11:30–12:30"
        />
        <LabeledInput
          id="location"
          label="الموقع · Location"
          value={options.location}
          onChange={(v) => onChange({ location: v })}
          placeholder="عن بعد"
          rtl
        />
      </section>

      <section className="flex flex-col gap-2">
        <Label htmlFor="attendees" className={SECTION_LABEL}>
          قائمة الحضور · Attendees
        </Label>
        <Textarea
          id="attendees"
          dir="auto"
          value={options.attendees}
          onChange={(e) => onChange({ attendees: e.target.value })}
          placeholder={"مشاري الزنبقي — هيئة الحكومة الرقمية\nمحمد جركس — شركة هوّز"}
          className="min-h-24 resize-y bg-card text-sm leading-relaxed"
        />
        <p className="text-xs text-muted-foreground">
          Auto-filled from speakers — add each one's الجهة (organization). One per line.
        </p>
      </section>

      <section className="flex flex-col gap-2">
        <Label htmlFor="notes" className={SECTION_LABEL}>
          ملاحظات · Notes
        </Label>
        <Textarea
          id="notes"
          dir="auto"
          value={options.notes}
          onChange={(e) => onChange({ notes: e.target.value })}
          placeholder="ملاحظاتك حول ما يهم والقرارات — النص يملأ التفاصيل."
          className="min-h-28 resize-y bg-card text-sm leading-relaxed"
        />
        <p className="text-xs text-muted-foreground">
          The spine: sets which points matter and how they're weighted.
        </p>
      </section>

      <section className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <Label htmlFor="recap" className={SECTION_LABEL}>
            ملخص read.ai · Recap <span className="lowercase">(optional)</span>
          </Label>
          <label className="cursor-pointer text-xs text-oxide hover:underline">
            Load file
            <input
              type="file"
              accept=".txt,.md,text/plain"
              className="sr-only"
              onChange={async (e) => {
                const f = e.target.files?.[0]
                if (f) onChange({ recap: await f.text() })
                e.target.value = ""
              }}
            />
          </label>
        </div>
        <Textarea
          id="recap"
          dir="auto"
          value={options.recap}
          onChange={(e) => onChange({ recap: e.target.value })}
          placeholder="الصق ملخص read.ai هنا (اختياري) — يساعد على التفاصيل واكتشاف المهام."
          className="min-h-20 resize-y bg-card text-sm leading-relaxed"
        />
        <p className="text-xs text-muted-foreground">
          Partial &amp; approximate — used as a hint for detail/structure, never as fact.
        </p>
      </section>

      <Accordion type="single" collapsible className="border-t border-border">
        <AccordionItem value="advanced" className="border-b-0">
          <AccordionTrigger className={`${SECTION_LABEL} hover:no-underline`}>
            Advanced
          </AccordionTrigger>
          <AccordionContent className="flex flex-col gap-4 pt-1">
            <div className="flex flex-col gap-1.5">
              <Label className="text-xs text-muted-foreground">Model backend</Label>
              <Select value={options.backend} onValueChange={(v) => onChange({ backend: v })}>
                <SelectTrigger className="h-9 bg-card text-sm">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="openrouter">OpenRouter — Sonnet 4.6 (best Arabic)</SelectItem>
                  <SelectItem value="groq">Groq — Llama 3.3 70B (fast, free)</SelectItem>
                  <SelectItem value="lmstudio">LM Studio — local (free, private)</SelectItem>
                  <SelectItem value="ollama">Ollama — local (free, private)</SelectItem>
                </SelectContent>
              </Select>
              <p className="text-xs text-muted-foreground">
                OpenRouter needs OPENROUTER_API_KEY. Local backends need a running
                LM Studio / Ollama server + a model id below (see docs/LOCAL_MODELS.md).
              </p>
            </div>
            <p className="text-xs text-muted-foreground">JSON transcripts only — field mapping:</p>
            <div className="grid grid-cols-2 gap-3">
              <MonoField label="Speaker key" value={options.speakerKey} onChange={(v) => onChange({ speakerKey: v })} />
              <MonoField label="Text key" value={options.textKey} onChange={(v) => onChange({ textKey: v })} />
              <MonoField label="Start key" value={options.startKey} onChange={(v) => onChange({ startKey: v })} />
              <MonoField label="End key" value={options.endKey} onChange={(v) => onChange({ endKey: v })} />
            </div>
            <MonoField
              label="Speaker map"
              value={options.speakerMap}
              onChange={(v) => onChange({ speakerMap: v })}
              placeholder="SPEAKER_00=Alice, SPEAKER_01=Bob"
            />
            <MonoField
              label="Model (optional)"
              value={options.model}
              onChange={(v) => onChange({ model: v })}
              placeholder="llama-3.3-70b-versatile"
            />
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </div>
  )
}

interface LabeledInputProps {
  id: string
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  rtl?: boolean
}

function LabeledInput({ id, label, value, onChange, placeholder, rtl }: LabeledInputProps) {
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id} className={SECTION_LABEL}>
        {label}
      </Label>
      <Input
        id={id}
        dir={rtl ? "auto" : undefined}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="bg-card"
      />
    </div>
  )
}

interface MonoFieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
}

function MonoField({ label, value, onChange, placeholder }: MonoFieldProps) {
  const id = `f-${label.replace(/\s+/g, "-").toLowerCase()}`
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        {label}
      </Label>
      <Input
        id={id}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
        className="h-9 bg-card font-mono text-xs"
      />
    </div>
  )
}
