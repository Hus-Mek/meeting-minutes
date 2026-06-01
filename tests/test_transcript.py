"""Unit tests for transcript loading and formatting."""

from __future__ import annotations

import json

import pytest

from meeting_minutes.transcript import (
    FieldMap,
    Segment,
    estimate_tokens,
    format_for_prompt,
    load_transcript,
    parse_transcript,
    seconds_to_hms,
)


class TestSecondsToHms:
    @pytest.mark.parametrize(
        "seconds,expected",
        [
            (0, "00:00:00"),
            (59, "00:00:59"),
            (60, "00:01:00"),
            (3599, "00:59:59"),
            (3600, "01:00:00"),
            (3661, "01:01:01"),
            (90, "00:01:30"),
            (45.9, "00:00:45"),  # truncates, does not round
        ],
    )
    def test_formats_correctly(self, seconds, expected):
        assert seconds_to_hms(seconds) == expected

    def test_rejects_negative(self):
        with pytest.raises(ValueError, match="non-negative"):
            seconds_to_hms(-1)


class TestParseTranscript:
    def test_parses_default_fields(self):
        # Arrange
        data = [
            {"speaker": "Alice", "start": 0.0, "end": 2.5, "text": "  Hello  "},
            {"speaker": "Bob", "start": 2.5, "end": 4.0, "text": "Hi"},
        ]

        # Act
        segments = parse_transcript(data)

        # Assert
        assert segments == (
            Segment("Alice", 0.0, 2.5, "Hello"),  # text is stripped
            Segment("Bob", 2.5, 4.0, "Hi"),
        )

    def test_maps_alternate_field_names(self):
        data = [{"spk": "Alice", "begin": "1", "stop": "3", "content": "Hey"}]
        fields = FieldMap(speaker="spk", start="begin", end="stop", text="content")

        segments = parse_transcript(data, fields=fields)

        assert segments[0] == Segment("Alice", 1.0, 3.0, "Hey")

    def test_returns_immutable_tuple(self):
        segments = parse_transcript([{"speaker": "A", "start": 0, "end": 1, "text": "x"}])
        assert isinstance(segments, tuple)

    def test_rejects_non_list(self):
        with pytest.raises(ValueError, match="must be a list"):
            parse_transcript({"speaker": "A"})  # type: ignore[arg-type]

    def test_rejects_missing_field_with_index(self):
        data = [{"speaker": "A", "start": 0, "end": 1, "text": "ok"}, {"speaker": "B"}]
        with pytest.raises(ValueError, match="segment #1"):
            parse_transcript(data)

    def test_rejects_non_numeric_timestamp(self):
        data = [{"speaker": "A", "start": "soon", "end": 1, "text": "x"}]
        with pytest.raises(ValueError, match="segment #0"):
            parse_transcript(data)


class TestLoadTranscript:
    def test_loads_from_file(self, tmp_path):
        path = tmp_path / "t.json"
        path.write_text(json.dumps([{"speaker": "A", "start": 0, "end": 1, "text": "hi"}]))

        segments = load_transcript(path)

        assert segments[0].speaker == "A"

    def test_rejects_invalid_json(self, tmp_path):
        path = tmp_path / "bad.json"
        path.write_text("{not json")
        with pytest.raises(ValueError, match="not valid JSON"):
            load_transcript(path)


class TestFormatForPrompt:
    def test_renders_timestamped_speaker_lines(self):
        segments = (
            Segment("Alice", 0.0, 2.0, "Morning"),
            Segment("Bob", 65.0, 70.0, "Hello"),
        )
        result = format_for_prompt(segments)
        assert result == "[00:00:00] Alice: Morning\n[00:01:05] Bob: Hello"


class TestEstimateTokens:
    def test_approximates_four_chars_per_token(self):
        assert estimate_tokens("a" * 400) == 100
