"""Tests for the Claude Code CLI backend. The subprocess is fully mocked — no real
`claude` invocation, no network, no subscription use.
"""

from __future__ import annotations

import os
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


# A realistic-enough `claude --help` excerpt: a flag counts as "advertised" iff its
# literal string appears here, mirroring how _supports() probes the real CLI.
_FAKE_HELP = """\
Usage: claude [options] [command]

Options:
  -p, --print                  Print response and exit (headless)
  --output-format <format>     Output format (text, json, stream-json)
  --mcp-config <configs...>    Load MCP servers from JSON files or strings
  --strict-mcp-config          Only use MCP servers from --mcp-config
  --setting-sources <sources>  Comma-separated list of setting sources to load
  --model <model>              Model for the session
  --version                    Output the version number
"""


def _make_run(
    *,
    gen_stdout="ok",
    gen_stderr="",
    gen_returncode=0,
    help_text=_FAKE_HELP,
    reject=(),
):
    """Build a fake ``subprocess.run`` that answers ``--help`` with *help_text* and
    every generation call with the given result — except it rejects any flag in
    *reject* with commander's exact "unknown option" error (until generate strips it).
    Records each invoked cmd on ``run.calls``; generation cmds on ``run.gen_calls``.
    """

    def run(cmd, input=None, capture_output=None, text=None, timeout=None, cwd=None, **kwargs):
        run.calls.append(cmd)
        if "--help" in cmd:
            return _Proc(stdout=help_text)
        run.gen_calls.append(cmd)
        for flag in reject:
            if flag in cmd:
                return _Proc(stderr=f"error: unknown option '{flag}'", returncode=1)
        return _Proc(stdout=gen_stdout, stderr=gen_stderr, returncode=gen_returncode)

    run.calls = []
    run.gen_calls = []
    return run


def _patch_which(monkeypatch, path="/usr/local/bin/claude"):
    monkeypatch.setattr("shutil.which", lambda _name: path)


@pytest.fixture(autouse=True)
def _clear_cli_caches():
    """Class-level help / unsupported-flag caches are keyed by binary path and would
    otherwise leak across tests that share a path. Reset around every test."""
    ClaudeCodeClient._help_cache.clear()
    ClaudeCodeClient._unsupported_flags.clear()
    yield
    ClaudeCodeClient._help_cache.clear()
    ClaudeCodeClient._unsupported_flags.clear()


class TestClaudeCodeClient:
    def test_missing_cli_raises_helpful_error(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_BIN", raising=False)
        monkeypatch.setattr("shutil.which", lambda _name: None)
        monkeypatch.setattr("os.path.isfile", lambda _p: False)  # no fallback path exists
        with pytest.raises(RuntimeError, match="not found"):
            ClaudeCodeClient()

    def test_resolves_fallback_path_when_not_on_PATH(self, monkeypatch):
            monkeypatch.delenv("CLAUDE_CODE_BIN", raising=False)
            monkeypatch.setattr("shutil.which", lambda _name: None)  # not on PATH
            home_claude = os.path.expanduser("~/.local/bin/claude")
            monkeypatch.setattr("os.path.isfile", lambda p: p == home_claude)
            monkeypatch.setattr("os.access", lambda p, _mode: p == home_claude)
            assert ClaudeCodeClient()._path == home_claude

    def test_resolves_windows_npm_shim(self, monkeypatch):
        # Windows: claude installed as an npm .cmd shim, not on PATH.
        monkeypatch.delenv("CLAUDE_CODE_BIN", raising=False)
        monkeypatch.setattr("shutil.which", lambda _name: None)
        win_cmd = os.path.expanduser("~/AppData/Roaming/npm/claude.cmd")
        monkeypatch.setattr("os.path.isfile", lambda p: p == win_cmd)
        monkeypatch.setattr("os.access", lambda p, _mode: p == win_cmd)
        assert ClaudeCodeClient()._path == win_cmd

    def test_env_override_full_path(self, monkeypatch):
        monkeypatch.setenv("CLAUDE_CODE_BIN", "/custom/claude")
        monkeypatch.setattr("os.path.isfile", lambda p: p == "/custom/claude")
        monkeypatch.setattr("os.access", lambda p, _mode: True)
        assert ClaudeCodeClient()._path == "/custom/claude"

    def test_generate_pipes_prompt_and_returns_stdout(self, monkeypatch):
        _patch_which(monkeypatch)
        run = _make_run(gen_stdout="## محضر اجتماع\nمحتوى")
        monkeypatch.setattr(subprocess, "run", run)

        out = ClaudeCodeClient().generate("SYS contract", "USER transcript", model="")
        assert out == "## محضر اجتماع\nمحتوى"

        cmd = run.gen_calls[-1]
        # headless print mode, text output, prompt piped via stdin (not argv)
        assert cmd[1] == "-p"
        assert "--output-format" in cmd and "text" in cmd
        assert "--model" in cmd and "opus" in cmd  # empty model => Opus tier (not CC default)
        # lean invocation: no MCP servers, no user hooks/rules
        assert "--strict-mcp-config" in cmd
        assert "--setting-sources" in cmd and "project,local" in cmd

    def test_generate_passes_prompt_via_stdin_in_isolated_cwd(self, monkeypatch):
        _patch_which(monkeypatch)
        captured = {}
        base = _make_run(gen_stdout="ok")

        def run(cmd, input=None, cwd=None, **kwargs):
            if "--help" not in cmd:
                captured.update(input=input, cwd=cwd)
            return base(cmd, input=input, cwd=cwd, **kwargs)

        monkeypatch.setattr(subprocess, "run", run)
        ClaudeCodeClient().generate("SYS contract", "USER transcript")
        assert "SYS contract" in captured["input"] and "USER transcript" in captured["input"]
        assert captured["cwd"] is not None  # isolated temp cwd, no project CLAUDE.md

    def test_generate_defaults_to_opus_tier(self, monkeypatch):
        _patch_which(monkeypatch)
        run = _make_run(gen_stdout="ok")
        monkeypatch.setattr(subprocess, "run", run)
        ClaudeCodeClient().generate("s", "u", model="")  # no preference
        cmd = run.gen_calls[-1]
        assert "--model" in cmd and "opus" in cmd and "sonnet" not in cmd

    def test_explicit_sonnet_request_uses_sonnet(self, monkeypatch):
        _patch_which(monkeypatch)
        run = _make_run(gen_stdout="ok")
        monkeypatch.setattr(subprocess, "run", run)
        ClaudeCodeClient().generate("s", "u", model="claude-sonnet-4-6")
        cmd = run.gen_calls[-1]
        assert "--model" in cmd and "sonnet" in cmd  # honoured, still within Opus/Sonnet

    def test_non_opus_non_sonnet_request_is_forced_to_opus(self, monkeypatch):
        """'nothing else': a Haiku/Groq/garbage model id collapses onto the Opus tier."""
        _patch_which(monkeypatch)
        for bad_model in ("haiku", "llama-3.3-70b-versatile", "gpt-4o"):
            run = _make_run(gen_stdout="ok")
            monkeypatch.setattr(subprocess, "run", run)
            ClaudeCodeClient().generate("s", "u", model=bad_model)
            cmd = run.gen_calls[-1]
            assert "opus" in cmd and "haiku" not in cmd and bad_model not in cmd

    def test_falls_back_to_sonnet_when_opus_unavailable(self, monkeypatch):
        """Opus not on the account's plan → retry with Sonnet, never anything else."""
        _patch_which(monkeypatch)

        def run(cmd, input=None, **kwargs):
            run.calls.append(cmd)
            if "--help" in cmd:
                return _Proc(stdout=_FAKE_HELP)
            run.gen_calls.append(cmd)
            if "opus" in cmd:
                return _Proc(
                    stderr="There's an issue with the selected model (opus). "
                    "It may not exist or you may not have access to it.",
                    returncode=1,
                )
            return _Proc(stdout="via sonnet")

        run.calls, run.gen_calls = [], []
        monkeypatch.setattr(subprocess, "run", run)

        out = ClaudeCodeClient().generate("s", "u")
        assert out == "via sonnet"
        assert len(run.gen_calls) == 2  # opus rejected, sonnet succeeded
        assert "sonnet" in run.gen_calls[-1] and "opus" not in run.gen_calls[-1]

    def test_generic_access_error_does_not_trigger_tier_switch(self, monkeypatch):
        """A non-model 'no access' error (auth/MCP/org) must surface, NOT be mistaken
        for an Opus-unavailable error and waste a Sonnet retry."""
        _patch_which(monkeypatch)
        run = _make_run(
            gen_stderr="You may not have access to this MCP server. Please log in.",
            gen_returncode=1,
        )
        monkeypatch.setattr(subprocess, "run", run)
        with pytest.raises(RuntimeError, match="MCP server"):
            ClaudeCodeClient().generate("s", "u")
        assert len(run.gen_calls) == 1  # no spurious tier switch

    def test_unstrippable_unknown_option_raises_immediately(self, monkeypatch):
        """An 'unknown option' for a flag we didn't inject (not in optional, not
        --model) must raise at once — never fall through to the model-tier check,
        even if the same stderr also contains model-availability wording."""
        _patch_which(monkeypatch)
        run = _make_run(
            gen_stderr="error: unknown option '--frobnicate'; you may not have access to it",
            gen_returncode=1,
        )
        monkeypatch.setattr(subprocess, "run", run)
        with pytest.raises(RuntimeError, match="frobnicate"):
            ClaudeCodeClient().generate("s", "u")
        assert len(run.gen_calls) == 1  # no tier switch, no loop

    def test_both_tiers_unavailable_raises(self, monkeypatch):
        """If neither Opus nor Sonnet is available, surface an error — try nothing else."""
        _patch_which(monkeypatch)
        run = _make_run(
            gen_stderr="issue with the selected model. you may not have access to it.",
            gen_returncode=1,
        )
        monkeypatch.setattr(subprocess, "run", run)
        with pytest.raises(RuntimeError, match="selected model|exit 1"):
            ClaudeCodeClient().generate("s", "u")
        # tried exactly the two allowed tiers, then gave up — no third attempt
        assert len(run.gen_calls) == 2
        tiers = {("opus" in c, "sonnet" in c) for c in run.gen_calls}
        assert (True, False) in tiers and (False, True) in tiers

    def test_nonzero_exit_raises_with_stderr(self, monkeypatch):
        _patch_which(monkeypatch)
        # A genuine failure (not a flag problem) must still surface, not loop forever.
        run = _make_run(gen_stderr="not logged in", gen_returncode=1)
        monkeypatch.setattr(subprocess, "run", run)
        with pytest.raises(RuntimeError, match="not logged in"):
            ClaudeCodeClient().generate("s", "u")

    def test_empty_output_raises(self, monkeypatch):
        _patch_which(monkeypatch)
        run = _make_run(gen_stdout="   ")
        monkeypatch.setattr(subprocess, "run", run)
        with pytest.raises(RuntimeError, match="empty output"):
            ClaudeCodeClient().generate("s", "u")

    def test_timeout_raises_clean_message(self, monkeypatch):
        _patch_which(monkeypatch)

        def boom(cmd, **k):
            if "--help" in cmd:
                return _Proc(stdout=_FAKE_HELP)
            raise subprocess.TimeoutExpired(cmd="claude", timeout=600)

        monkeypatch.setattr(subprocess, "run", boom)
        with pytest.raises(RuntimeError, match="timed out"):
            ClaudeCodeClient(timeout=600).generate("s", "u")

    # ---- CLI-version robustness ------------------------------------------------

    def test_drops_flag_the_help_does_not_advertise(self, monkeypatch):
        """An older CLI whose --help lacks --setting-sources: we never pass it (no
        wasted failing call), keep the flags it does advertise, and still generate."""
        _patch_which(monkeypatch)
        help_without = _FAKE_HELP.replace(
            "  --setting-sources <sources>  Comma-separated list of setting sources to load\n",
            "",
        )
        run = _make_run(gen_stdout="ok", help_text=help_without)
        monkeypatch.setattr(subprocess, "run", run)

        out = ClaudeCodeClient().generate("s", "u")
        assert out == "ok"
        assert len(run.gen_calls) == 1  # no failed first attempt
        cmd = run.gen_calls[-1]
        assert "--setting-sources" not in cmd  # unadvertised → dropped
        assert "--strict-mcp-config" in cmd  # advertised → kept

    def test_retries_when_cli_rejects_unknown_option(self, monkeypatch):
        """The flag is advertised in --help but the CLI rejects it at runtime: the
        safety net strips it and retries, so generation still succeeds."""
        _patch_which(monkeypatch)
        run = _make_run(gen_stdout="recovered", reject=("--setting-sources",))
        monkeypatch.setattr(subprocess, "run", run)

        out = ClaudeCodeClient().generate("s", "u")
        assert out == "recovered"
        assert len(run.gen_calls) == 2  # first rejected, retry succeeded
        assert "--setting-sources" not in run.gen_calls[-1]  # stripped on retry
        assert "--strict-mcp-config" in run.gen_calls[-1]  # unrelated flag preserved

    def test_unsupported_flag_cached_across_calls(self, monkeypatch):
        """Once a flag is rejected, later generate() calls skip it outright — no
        repeated failing attempts (matters: map-reduce calls generate() many times)."""
        _patch_which(monkeypatch)
        run = _make_run(gen_stdout="ok", reject=("--setting-sources",))
        monkeypatch.setattr(subprocess, "run", run)

        client = ClaudeCodeClient()
        client.generate("s", "u")  # learns the flag is unsupported (2 gen calls)
        run.gen_calls.clear()
        client.generate("s", "u2")  # second call: no rejection, single attempt
        assert len(run.gen_calls) == 1
        assert "--setting-sources" not in run.gen_calls[-1]

    def test_unsupported_flag_cached_across_client_instances(self, monkeypatch):
        """The cache is keyed by binary path, so a fresh client (each request builds
        one via the backend registry) reuses what an earlier one learned."""
        _patch_which(monkeypatch)
        run = _make_run(gen_stdout="ok", reject=("--setting-sources",))
        monkeypatch.setattr(subprocess, "run", run)

        ClaudeCodeClient().generate("s", "u")  # first instance learns
        run.gen_calls.clear()
        ClaudeCodeClient().generate("s", "u")  # new instance, same path
        assert len(run.gen_calls) == 1
        assert "--setting-sources" not in run.gen_calls[-1]

    def test_help_unreadable_keeps_flags_then_retry_strips(self, monkeypatch):
        """If --help can't be read we don't pre-drop anything; the runtime retry net
        still strips a rejected flag so a version mismatch never breaks generation."""
        _patch_which(monkeypatch)

        def run(cmd, input=None, **kwargs):
            run.calls.append(cmd)
            if "--help" in cmd:
                raise OSError("help blew up")  # unreadable help
            run.gen_calls.append(cmd)
            if "--strict-mcp-config" in cmd:
                return _Proc(stderr="error: unknown option '--strict-mcp-config'", returncode=1)
            return _Proc(stdout="ok")

        run.calls, run.gen_calls = [], []
        monkeypatch.setattr(subprocess, "run", run)

        out = ClaudeCodeClient().generate("s", "u")
        assert out == "ok"
        assert "--strict-mcp-config" not in run.gen_calls[-1]
        # flags we never had trouble with are still present
        assert "--setting-sources" in run.gen_calls[-1]

    def test_old_cli_rejecting_every_flag_still_generates(self, monkeypatch):
        """Worst case: a CLI that advertises the flags in --help but rejects each one
        at runtime. The retry loop must strip them one by one and converge to the bare
        `-p` invocation — never looping forever."""
        _patch_which(monkeypatch)
        run = _make_run(
            gen_stdout="bare",
            reject=("--strict-mcp-config", "--mcp-config", "--setting-sources"),
        )
        monkeypatch.setattr(subprocess, "run", run)

        out = ClaudeCodeClient().generate("s", "u", model="opus")
        assert out == "bare"
        assert len(run.gen_calls) == 4  # 3 rejects (one per flag) then success
        final = run.gen_calls[-1]
        for flag in ("--strict-mcp-config", "--mcp-config", "--setting-sources"):
            assert flag not in final
        assert final[1] == "-p"  # core invocation intact
        assert "--model" in final and "opus" in final  # a working flag is preserved

    def test_recovers_from_backtick_and_uppercase_error_dialects(self, monkeypatch):
        """Different commander.js versions quote the bad flag differently (backtick,
        no quote) and may capitalise. The retry net must recognise them all."""
        _patch_which(monkeypatch)

        def run(cmd, input=None, **kwargs):
            run.calls.append(cmd)
            if "--help" in cmd:
                return _Proc(stdout=_FAKE_HELP)
            run.gen_calls.append(cmd)
            if "--setting-sources" in cmd:
                # backtick-open / apostrophe-close form, capitalised — a real dialect
                return _Proc(stderr="error: Unknown option `--setting-sources'", returncode=1)
            return _Proc(stdout="ok")

        run.calls, run.gen_calls = [], []
        monkeypatch.setattr(subprocess, "run", run)

        out = ClaudeCodeClient().generate("s", "u")
        assert out == "ok"
        assert "--setting-sources" not in run.gen_calls[-1]

    def test_help_probe_ignores_flag_named_only_in_a_description(self, monkeypatch):
        """--mcp-config appears only inside --strict-mcp-config's description prose, not
        as its own option line. The probe must treat it as unsupported (boundary match,
        not substring) and drop it WITHOUT a wasted failing call."""
        _patch_which(monkeypatch)
        help_text = (
            "Usage: claude [options]\n"
            "  -p, --print                  Print response and exit\n"
            "  --output-format <format>     Output format\n"
            "  --strict-mcp-config          Only use MCP servers from --mcp-config, nothing else\n"
            "  --setting-sources <sources>  Setting sources to load\n"
        )
        run = _make_run(gen_stdout="ok", help_text=help_text)
        monkeypatch.setattr(subprocess, "run", run)

        ClaudeCodeClient().generate("s", "u")
        assert len(run.gen_calls) == 1  # no failing first attempt
        cmd = run.gen_calls[-1]
        assert "--mcp-config" not in cmd  # only in prose → not advertised → dropped
        assert "--strict-mcp-config" in cmd and "--setting-sources" in cmd  # real entries

    def test_unknown_option_echoed_in_stdout_does_not_trigger_strip(self, monkeypatch):
        """A genuine non-flag failure whose stdout merely echoes "unknown option" must
        surface as an error, not silently strip a flag and retry (we scan stderr only)."""
        _patch_which(monkeypatch)
        run = _make_run(
            gen_stdout="the transcript said: unknown option '--setting-sources'",
            gen_stderr="fatal: not logged in",
            gen_returncode=1,
        )
        monkeypatch.setattr(subprocess, "run", run)

        with pytest.raises(RuntimeError, match="not logged in"):
            ClaudeCodeClient().generate("s", "u")
        assert len(run.gen_calls) == 1  # no spurious retry

    def test_registered_in_backends(self, monkeypatch):
        _patch_which(monkeypatch)
        from meeting_minutes.llm import get_client

        assert isinstance(get_client("claude-code"), ClaudeCodeClient)
        assert L.default_model_for("claude-code") == "opus"  # Opus tier, not CC's default
