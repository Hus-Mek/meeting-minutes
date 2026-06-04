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

/**
 * Detects whether a generation error means Claude Code is present but not yet
 * authenticated (the user hasn't logged in). This is the common case once the app
 * bundles the CLI: it resolves fine but `claude` reports it needs a login. The UI
 * uses this to open the guide and point at the one-time login (the Meeting Minutes
 * tray icon → "Log in to Claude") rather than the install steps.
 *
 * @param message - The error text surfaced from a failed generation.
 * @returns `true` when the message indicates a login/authentication is required.
 */
export function isClaudeCodeAuthNeeded(message: string): boolean {
  if (!message) {
    return false
  }

  const text = message.toLowerCase()

  return (
    text.includes("not logged in") ||
    text.includes("logged out") ||
    text.includes("/login") ||
    text.includes("log in to claude") ||
    text.includes("unauthorized") ||
    text.includes("authenticate") ||
    text.includes("invalid api key")
  )
}
