import { describe, expect, it } from "vitest"
import { isClaudeCodeMissing } from "./claudeCode"

const BACKEND_NOT_FOUND_MESSAGE =
  "Claude Code was not found on this computer.\n" +
  "Quick option — no setup: in the 'Model backend' menu, switch to 'Cowork' to " +
  "copy the prompt into Claude yourself."

describe("isClaudeCodeMissing", () => {
  it("returns true for the exact backend 'not found' message", () => {
    // Arrange
    const message = BACKEND_NOT_FOUND_MESSAGE

    // Act
    const result = isClaudeCodeMissing(message)

    // Assert
    expect(result).toBe(true)
  })

  it("returns false for a generic generation failure message", () => {
    // Arrange
    const message = "Generation failed"

    // Act
    const result = isClaudeCodeMissing(message)

    // Assert
    expect(result).toBe(false)
  })

  it("returns false for an empty string", () => {
    // Arrange
    const message = ""

    // Act
    const result = isClaudeCodeMissing(message)

    // Assert
    expect(result).toBe(false)
  })

  it("returns true for a mixed-case variant containing 'Claude Code' and 'not found'", () => {
    // Arrange
    const message = "Error: the Claude Code CLI was NOT FOUND on your PATH"

    // Act
    const result = isClaudeCodeMissing(message)

    // Assert
    expect(result).toBe(true)
  })

  it("returns false for an unrelated 502/timeout-style message", () => {
    // Arrange
    const message = "502 Bad Gateway: upstream request timed out after 30s"

    // Act
    const result = isClaudeCodeMissing(message)

    // Assert
    expect(result).toBe(false)
  })
})
