"""Unit tests for transcript loading and formatting."""

from __future__ import annotations

import json

import pytest

from meeting_minutes import transcript as T
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
            (360000, "100:00:00"),  # hours grow unbounded
        ],
    )
    def test_formats_correctly(self, seconds, expected):
        assert seconds_to_hms(seconds) == expected

    def test_rejects_negative(self):
        with pytest.raises(ValueError, match="non-negative"):
            seconds_to_hms(-1)

    @pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan")])
    def test_rejects_non_finite(self, bad):
        with pytest.raises(ValueError, match="finite"):
            seconds_to_hms(bad)


class TestParseTranscript:
    def test_parses_default_fields(self):
        data = [
            {"speaker": "Alice", "start": 0.0, "end": 2.5, "text": "  Hello  "},
            {"speaker": "Bob", "start": 2.5, "end": 4.0, "text": "Hi"},
        ]
        segments = parse_transcript(data)
        assert segments == (
            Segment("Alice", 0.0, 2.5, "Hello"),  # text stripped
            Segment("Bob", 2.5, 4.0, "Hi"),
        )

    def test_maps_alternate_field_names(self):
        data = [{"spk": "Alice", "begin": "1", "stop": "3", "content": "Hey"}]
        fields = FieldMap(speaker="spk", start="begin", end="stop", text="content")
        segments = parse_transcript(data, fields=fields)
        assert segments[0] == Segment("Alice", 1.0, 3.0, "Hey")

    def test_sorts_out_of_order_segments(self):
        data = [
            {"speaker": "B", "start": 10, "end": 12, "text": "late"},
            {"speaker": "A", "start": 0, "end": 2, "text": "early"},
        ]
        segments = parse_transcript(data)
        assert [s.text for s in segments] == ["early", "late"]

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

    def test_rejects_non_finite_timestamp(self):
        data = [{"speaker": "A", "start": "inf", "end": 1, "text": "x"}]
        with pytest.raises(ValueError, match="non-finite"):
            parse_transcript(data)

    def test_preserves_unicode_and_rtl(self):
        data = [{"speaker": "علي", "start": 0, "end": 1, "text": "مرحبا 🌍"}]
        segments = parse_transcript(data)
        assert segments[0].speaker == "علي"
        assert segments[0].text == "مرحبا 🌍"


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

    def test_rejects_oversized_file(self, tmp_path, monkeypatch):
        path = tmp_path / "big.json"
        path.write_text(json.dumps([{"speaker": "A", "start": 0, "end": 1, "text": "hi"}]))
        monkeypatch.setattr(T, "MAX_TRANSCRIPT_BYTES", 1)
        with pytest.raises(ValueError, match="ceiling"):
            load_transcript(path)


class TestFormatForPrompt:
    def test_renders_timestamp_ranges_with_pause_marker(self):
        segments = (
            Segment("Alice", 0.0, 2.0, "Morning"),
            Segment("Bob", 65.0, 70.0, "Hello"),  # 63s gap -> pause marker
        )
        result = format_for_prompt(segments)
        assert result == (
            "[00:00:00–00:00:02] Alice: Morning\n"
            "[... 00:01:03 pause ...]\n"
            "[00:01:05–00:01:10] Bob: Hello"
        )

    def test_no_pause_marker_for_short_gap(self):
        segments = (
            Segment("Alice", 0.0, 2.0, "Hi"),
            Segment("Bob", 3.0, 5.0, "Yo"),
        )
        result = format_for_prompt(segments)
        assert "pause" not in result


class TestEstimateTokens:
    def test_approximates_four_chars_per_token(self):
        assert estimate_tokens("a" * 400) == 100
