"""Tests for the Claude Code CLI backend. The subprocess is fully mocked — no real
`claude` invocation, no network, no subscription use.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from meeting_minutes import llm as L  # noqa: E402
from meeting_minutes.llm import ClaudeCodeClient  # noqa: E402


class _Proc:
    def __init__(self, stdout="", stderr="", returncode=0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


def _patch_which(monkeypatch, path="/usr/local/bin/claude"):
    monkeypatch.setattr("shutil.which", lambda _name: path)


class TestClaudeCodeClient:
    def test_missing_cli_raises_helpful_error(self, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda _name: None)
        with pytest.raises(RuntimeError, match="not found on PATH"):
            ClaudeCodeClient()

    def test_generate_pipes_prompt_and_returns_stdout(self, monkeypatch):
        _patch_which(monkeypatch)
        captured = {}

        def fake_run(cmd, input=None, capture_output=None, text=None, timeout=None, cwd=None):
            captured.update(cmd=cmd, input=input, timeout=timeout, cwd=cwd)
            return _Proc(stdout="## محضر اجتماع\nمحتوى")

        monkeypatch.setattr(subprocess, "run", fake_run)
        out = ClaudeCodeClient().generate("SYS contract", "USER transcript", model="")
        assert out == "## محضر اجتماع\nمحتوى"
        # headless print mode, text output, prompt piped via stdin (not argv)
        assert captured["cmd"][1] == "-p"
        assert "--output-format" in captured["cmd"] and "text" in captured["cmd"]
        assert "--model" not in captured["cmd"]  # empty model => CC default
        assert "SYS contract" in captured["input"] and "USER transcript" in captured["input"]
        # lean invocation: no MCP servers, no user hooks/rules, isolated cwd
        assert "--strict-mcp-config" in captured["cmd"]
        assert "--setting-sources" in captured["cmd"] and "project,local" in captured["cmd"]
        assert captured["cwd"] is not None

    def test_generate_passes_model_when_set(self, monkeypatch):
        _patch_which(monkeypatch)
        captured = {}
        monkeypatch.setattr(
            subprocess, "run",
            lambda cmd, **k: captured.update(cmd=cmd) or _Proc(stdout="ok"),
        )
        ClaudeCodeClient().generate("s", "u", model="opus")
        assert "--model" in captured["cmd"] and "opus" in captured["cmd"]

    def test_nonzero_exit_raises_with_stderr(self, monkeypatch):
        _patch_which(monkeypatch)
        monkeypatch.setattr(
            subprocess, "run", lambda *a, **k: _Proc(stderr="not logged in", returncode=1)
        )
        with pytest.raises(RuntimeError, match="not logged in"):
            ClaudeCodeClient().generate("s", "u")

    def test_empty_output_raises(self, monkeypatch):
        _patch_which(monkeypatch)
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: _Proc(stdout="   "))
        with pytest.raises(RuntimeError, match="empty output"):
            ClaudeCodeClient().generate("s", "u")

    def test_timeout_raises_clean_message(self, monkeypatch):
        _patch_which(monkeypatch)

        def boom(*a, **k):
            raise subprocess.TimeoutExpired(cmd="claude", timeout=600)

        monkeypatch.setattr(subprocess, "run", boom)
        with pytest.raises(RuntimeError, match="timed out"):
            ClaudeCodeClient(timeout=600).generate("s", "u")

    def test_registered_in_backends(self, monkeypatch):
        _patch_which(monkeypatch)
        from meeting_minutes.llm import get_client

        assert isinstance(get_client("claude-code"), ClaudeCodeClient)
        assert L.default_model_for("claude-code") == ""
