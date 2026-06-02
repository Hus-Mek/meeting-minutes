import type { InspectResult, MinutesOptions } from "@/lib/api"
import { Dropzone } from "@/components/Dropzone"
import { Label } from "@/components/ui/label"
import { Input } from "@/components/ui/input"
import { Textarea } from "@/components/ui/textarea"
import { Switch } from "@/components/ui/switch"
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion"

interface InputsPaneProps {
  file: File | null
  onSelectFile: (file: File | null) => void
  inspect: InspectResult | null
  inspecting: boolean
  inspectError: string | null
  options: MinutesOptions
  onChange: (patch: Partial<MinutesOptions>) => void
}

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
        <Label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Transcript
        </Label>
        <Dropzone
          file={file}
          onSelect={onSelectFile}
          inspect={inspect}
          inspecting={inspecting}
          inspectError={inspectError}
        />
      </section>

      <section className="flex flex-col gap-2">
        <Label htmlFor="notes" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Notes
        </Label>
        <Textarea
          id="notes"
          value={options.notes}
          onChange={(e) => onChange({ notes: e.target.value })}
          placeholder="Your rough notes — what mattered, decisions, owners. The transcript fills in the detail."
          className="min-h-32 resize-y bg-card font-sans text-sm leading-relaxed"
        />
        <p className="text-xs text-muted-foreground">
          The spine: these set which topics matter and how they're weighted.
        </p>
      </section>

      <section className="grid grid-cols-2 gap-3">
        <div className="flex flex-col gap-2">
          <Label htmlFor="title" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Title
          </Label>
          <Input
            id="title"
            value={options.title}
            onChange={(e) => onChange({ title: e.target.value })}
            placeholder="Weekly Sync"
            className="bg-card"
          />
        </div>
        <div className="flex flex-col gap-2">
          <Label htmlFor="date" className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Date
          </Label>
          <Input
            id="date"
            type="date"
            value={options.date}
            onChange={(e) => onChange({ date: e.target.value })}
            className="bg-card"
          />
        </div>
      </section>

      <div className="flex items-center justify-between rounded-md border border-border bg-card px-3.5 py-3">
        <div>
          <Label htmlFor="actions" className="text-sm font-medium text-foreground">
            Decisions & action items
          </Label>
          <p className="text-xs text-muted-foreground">Append owners, decisions, and due dates.</p>
        </div>
        <Switch
          id="actions"
          checked={options.includeActions}
          onCheckedChange={(v) => onChange({ includeActions: v })}
        />
      </div>

      <Accordion type="single" collapsible className="border-t border-border">
        <AccordionItem value="advanced" className="border-b-0">
          <AccordionTrigger className="text-xs font-semibold uppercase tracking-wide text-muted-foreground hover:no-underline">
            Advanced
          </AccordionTrigger>
          <AccordionContent className="flex flex-col gap-4 pt-1">
            <div className="grid grid-cols-2 gap-3">
              <Field label="Speaker key" value={options.speakerKey} onChange={(v) => onChange({ speakerKey: v })} />
              <Field label="Text key" value={options.textKey} onChange={(v) => onChange({ textKey: v })} />
              <Field label="Start key" value={options.startKey} onChange={(v) => onChange({ startKey: v })} />
              <Field label="End key" value={options.endKey} onChange={(v) => onChange({ endKey: v })} />
            </div>
            <Field
              label="Speaker map"
              value={options.speakerMap}
              onChange={(v) => onChange({ speakerMap: v })}
              placeholder="SPEAKER_00=Alice, SPEAKER_01=Bob"
            />
            <Field
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

interface FieldProps {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
}

function Field({ label, value, onChange, placeholder }: FieldProps) {
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
