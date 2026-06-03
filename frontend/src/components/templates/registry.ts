import type { ComponentType } from "react"
import type { Minutes } from "@/lib/minutes"
import { DefaultTemplate } from "./DefaultTemplate"

// Every template is just a renderer over the same Minutes model (screen + PDF).
// To offer a client's predefined layout, add it here — nothing else changes; it
// becomes selectable in the result toolbar automatically.

export interface TemplateProps {
  minutes: Minutes
  editable?: boolean
  onChange?: (next: Minutes) => void
}

export interface TemplateDef {
  id: string
  name: string
  Component: ComponentType<TemplateProps>
}

export const TEMPLATES: readonly TemplateDef[] = [
  { id: "default", name: "النموذج الافتراضي", Component: DefaultTemplate },
]

export const DEFAULT_TEMPLATE_ID = TEMPLATES[0].id

export function getTemplate(id: string): TemplateDef {
  return TEMPLATES.find((t) => t.id === id) ?? TEMPLATES[0]
}
