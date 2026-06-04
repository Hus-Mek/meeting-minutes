/**
 * Detects whether a generation error means the Claude Code CLI is missing,
 * so the UI can open the illustrated setup guide instead of a raw error.
 *
 * The backend raises this from `meeting_minutes/llm.py` when the `claude`
 * binary cannot be found, with a message that begins:
 *   "Claude Code was not found on this computer. ..."
 * That file deliberately keeps the words "not found" so the frontend can
 * match on the substring; this helper mirrors that contract.
 *
 * @param message - The error text surfaced from a failed generation.
 * @returns `true` when the message indicates Claude Code is not installed.
 */
export function isClaudeCodeMissing(message: string): boolean {
  if (!message) {
    return false
  }

  const text = message.toLowerCase()

  if (text.includes("claude code was not found")) {
    return true
  }

  return text.includes("claude code") && text.includes("not found")
}
