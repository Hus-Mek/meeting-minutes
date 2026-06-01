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
                "--no-actions",
                "--speaker-key", "spk",
                "--start-key", "begin",
                "--speaker-map", "SPEAKER_00=Alice",
                "--debug",
            ]
        )
        assert args.transcript == "t.json"
        assert args.no_actions is True
        assert args.speaker_key == "spk"
        assert args.start_key == "begin"
        assert args.debug is True

    def test_date_defaults_to_today(self):
        args = cli.build_parser().parse_args(["--transcript", "t", "--notes", "n", "--out", "o"])
        # ISO date: YYYY-MM-DD
        assert len(args.date) == 10 and args.date.count("-") == 2


class TestSpeakerMapParsing:
    def test_parses_pairs(self):
        assert cli._parse_speaker_map("A=Alice, B=Bob") == {"A": "Alice", "B": "Bob"}

    def test_empty_returns_empty(self):
        assert cli._parse_speaker_map(None) == {}
        assert cli._parse_speaker_map("") == {}

    def test_skips_blank_entries(self):
        assert cli._parse_speaker_map("A=Alice,,B=Bob,") == {"A": "Alice", "B": "Bob"}

    def test_rejects_malformed_entry(self):
        with pytest.raises(ValueError, match="LABEL=Name"):
            cli._parse_speaker_map("justaname")


class TestMain:
    def test_success_returns_zero(self, monkeypatch, capsys):
        captured = {}

        def fake_generate(**kwargs):
            captured.update(kwargs)
            return Path("o.md")

        monkeypatch.setattr(cli, "generate_minutes_from_files", fake_generate)

        code = cli.main(["--transcript", "t.json", "--notes", "n.md", "--out", "o.md"])

        assert code == 0
        assert "wrote o.md" in capsys.readouterr().out
        assert captured["transcript_path"] == "t.json"
        assert captured["include_actions"] is True  # on by default
        assert captured["fields"].speaker == "speaker"

    def test_failure_returns_one_with_message(self, monkeypatch, capsys):
        def boom(**_kwargs):
            raise RuntimeError("GROQ_API_KEY is not set")

        monkeypatch.setattr(cli, "generate_minutes_from_files", boom)

        code = cli.main(["--transcript", "t.json", "--notes", "n.md", "--out", "o.md"])

        assert code == 1
        assert "GROQ_API_KEY is not set" in capsys.readouterr().err

    def test_debug_reraises(self, monkeypatch):
        def boom(**_kwargs):
            raise RuntimeError("kaboom")

        monkeypatch.setattr(cli, "generate_minutes_from_files", boom)

        with pytest.raises(RuntimeError, match="kaboom"):
            cli.main(["--transcript", "t", "--notes", "n", "--out", "o", "--debug"])
