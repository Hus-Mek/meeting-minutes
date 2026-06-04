"""Tests for the one-click desktop launcher (``meeting_minutes.desktop``).

The pure helpers (port/URL/health) are unit-tested on headless CI with no display
and nothing listening. A single ``@pytest.mark.integration`` test boots the real
FastAPI app in a daemon thread and probes it over loopback — no network, no LLM.
"""

from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import urllib.request

import pytest

from meeting_minutes.desktop import (
    HOST,
    app_url,
    build_server,
    find_free_port,
    health_url,
    wait_for_health,
)


class TestFindFreePort:
    def test_returns_int_in_user_range(self):
        # Act
        port = find_free_port()

        # Assert
        assert isinstance(port, int)
        assert 1024 <= port <= 65535

    def test_returned_port_is_actually_bindable(self):
        # Arrange
        port = find_free_port()

        # Act / Assert — binding the reported port must succeed.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind((HOST, port))
            assert sock.getsockname()[1] == port


class TestUrlBuilders:
    def test_app_url_is_loopback_root(self):
        # Act / Assert
        assert app_url(8080) == "http://127.0.0.1:8080/"

    def test_health_url_targets_api_health(self):
        # Act / Assert
        assert health_url(8080) == "http://127.0.0.1:8080/api/health"


class TestWaitForHealth:
    def test_returns_false_when_nothing_is_listening(self):
        # Arrange — a free port with no server bound to it.
        url = health_url(find_free_port())

        # Act
        result = wait_for_health(url, timeout=0.5)

        # Assert
        assert result is False

    def test_gives_up_within_the_timeout(self):
        # Arrange
        url = health_url(find_free_port())

        # Act
        started = time.monotonic()
        wait_for_health(url, timeout=0.5)
        elapsed = time.monotonic() - started

        # Assert — a short timeout must not block for long.
        assert elapsed < 3.0


@pytest.mark.integration
class TestRealServerBoot:
    def test_boots_app_and_serves_health_and_spa(self):
        # Arrange — pick a port, build the threaded uvicorn server, run it.
        port = find_free_port()
        server = build_server(port)
        thread = threading.Thread(target=server.run, name="uvicorn-test", daemon=True)
        thread.start()
        try:
            # Act / Assert — the server must answer the health probe in time.
            assert wait_for_health(health_url(port), timeout=15) is True

            with urllib.request.urlopen(health_url(port), timeout=5) as resp:  # noqa: S310
                assert resp.status == 200
                health_body = json.loads(resp.read().decode("utf-8"))
            assert health_body == {"status": "ok"}

            with urllib.request.urlopen(app_url(port), timeout=5) as resp:  # noqa: S310
                assert resp.status == 200
                content_type = resp.headers.get("content-type", "")
                root_body = resp.read().decode("utf-8")
            assert "html" in content_type.lower()
            assert "<" in root_body
        finally:
            # Cleanup — ask the server to stop and let the thread wind down.
            server.should_exit = True
            thread.join(timeout=10)


class TestEnsureClaudeRuntime:
    """The launcher must PREFER a claude the user already has and only fall back to
    the bundled Node + CLI when none is found."""

    def test_prefers_an_existing_claude_and_leaves_env_untouched(self, monkeypatch):
        # Arrange — a claude is already resolvable; nothing should be bundled-wired.
        from meeting_minutes import desktop
        from meeting_minutes.llm import ClaudeCodeClient

        monkeypatch.delenv("CLAUDE_CODE_BIN", raising=False)
        monkeypatch.setattr(
            ClaudeCodeClient,
            "_resolve_binary",
            classmethod(lambda cls, binary=None: "/usr/bin/claude"),
        )

        # Act
        desktop._ensure_claude_runtime()

        # Assert — no bundled override applied.
        assert "CLAUDE_CODE_BIN" not in os.environ

    def test_falls_back_to_bundled_when_none_found(self, monkeypatch, tmp_path):
        # Arrange — no claude resolvable; a bundled vendor/node/claude.cmd exists.
        from meeting_minutes import desktop
        from meeting_minutes.llm import ClaudeCodeClient

        node_dir = tmp_path / "vendor" / "node"
        node_dir.mkdir(parents=True)
        claude_cmd = node_dir / "claude.cmd"
        claude_cmd.write_text("@echo off\n", encoding="utf-8")

        monkeypatch.delenv("CLAUDE_CODE_BIN", raising=False)
        monkeypatch.setenv("PATH", os.environ.get("PATH", ""))  # let monkeypatch restore PATH
        monkeypatch.setattr(
            ClaudeCodeClient,
            "_resolve_binary",
            classmethod(lambda cls, binary=None: None),
        )
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

        # Act
        desktop._ensure_claude_runtime()

        # Assert — CLAUDE_CODE_BIN points at the bundled shim and node dir leads PATH.
        assert os.environ.get("CLAUDE_CODE_BIN") == str(claude_cmd)
        assert os.environ.get("PATH", "").split(os.pathsep)[0] == str(node_dir)
