"""Tests for the CLI entrypoint. The generator is monkeypatched — no network."""

from __future__ import annotations

from pathlib import Path

import pytest

from meeting_minutes import cli


class TestParser:
    def test_requires_core_args(self):
        parser = cli.build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_parses_all_options(self):
        parser = cli.build_parser()
        args = parser.parse_args(
            [
                "--transcript", "t.json",
                "--notes", "n.md",
                "--out", "o.md",
                "--title", "Sync",
                "--date", "2026-06-01",
                "--backend", "groq",
                "--include-actions",
            ]
        )
        assert args.transcript == "t.json"
        assert args.include_actions is True
        assert args.backend == "groq"


class TestMain:
    def test_success_returns_zero(self, monkeypatch, capsys):
        captured = {}

        def fake_generate(**kwargs):
            captured.update(kwargs)
            return Path("o.md")

        monkeypatch.setattr(cli, "generate_minutes_from_files", fake_generate)

        code = main_argv = cli.main(
            ["--transcript", "t.json", "--notes", "n.md", "--out", "o.md"]
        )

        assert code == 0
        assert "wrote o.md" in capsys.readouterr().out
        assert captured["transcript_path"] == "t.json"

    def test_failure_returns_one_with_message(self, monkeypatch, capsys):
        def boom(**_kwargs):
            raise RuntimeError("GROQ_API_KEY is not set")

        monkeypatch.setattr(cli, "generate_minutes_from_files", boom)

        code = cli.main(["--transcript", "t.json", "--notes", "n.md", "--out", "o.md"])

        assert code == 1
        assert "GROQ_API_KEY is not set" in capsys.readouterr().err
