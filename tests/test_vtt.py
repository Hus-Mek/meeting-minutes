"""Tests for the WebVTT (Microsoft Teams) transcript adapter."""

import pytest

from meeting_minutes.transcript import (
    Segment,
    looks_like_vtt,
    parse_any,
    parse_vtt,
)

SAMPLE_VTT = """WEBVTT

00:00:00.000 --> 00:00:05.000
<v Alice>Hello everyone, let's begin.</v>

00:00:05.000 --> 00:00:09.500
<v Bob>Thanks Alice. The budget is ready.</v>
"""

# Teams emits a GUID cue identifier on its own line before the timing line.
SAMPLE_WITH_IDS = """WEBVTT

f7c1/1-0
00:00:01.000 --> 00:00:03.250
<v Mishari Al-Otaibi>السلام عليكم، نبدأ الاجتماع.</v>

f7c1/2-0
00:00:03.250 --> 00:00:06.000
<v Obada>تم استعراض المصفوفة.</v>
"""


def test_parse_vtt_returns_segments_with_speakers_text_and_times():
    # Arrange / Act
    segments = parse_vtt(SAMPLE_VTT)

    # Assert
    assert len(segments) == 2
    assert segments[0] == Segment(
        speaker="Alice",
        start_seconds=0.0,
        end_seconds=5.0,
        text="Hello everyone, let's begin.",
    )
    assert segments[1].speaker == "Bob"
    assert segments[1].end_seconds == 9.5
    assert segments[1].text == "Thanks Alice. The budget is ready."


def test_parse_vtt_strips_voice_tags_from_text():
    segments = parse_vtt(SAMPLE_VTT)
    assert "<v" not in segments[0].text
    assert "</v>" not in segments[0].text


def test_parse_vtt_handles_cue_identifier_lines_and_arabic():
    segments = parse_vtt(SAMPLE_WITH_IDS)
    assert len(segments) == 2
    assert segments[0].speaker == "Mishari Al-Otaibi"
    assert segments[0].text == "السلام عليكم، نبدأ الاجتماع."
    assert segments[0].start_seconds == 1.0
    assert segments[1].start_seconds == pytest.approx(3.25)


def test_parse_vtt_supports_mm_ss_short_timestamps():
    vtt = "WEBVTT\n\n01:02.500 --> 01:05.000\n<v X>hi</v>\n"
    segments = parse_vtt(vtt)
    assert segments[0].start_seconds == pytest.approx(62.5)
    assert segments[0].end_seconds == pytest.approx(65.0)


def test_parse_vtt_skips_note_and_style_blocks():
    vtt = (
        "WEBVTT\n\n"
        "NOTE this is a comment block\nwith two lines\n\n"
        "00:00:00.000 --> 00:00:01.000\n<v A>only cue</v>\n"
    )
    segments = parse_vtt(vtt)
    assert len(segments) == 1
    assert segments[0].text == "only cue"


def test_parse_vtt_falls_back_to_unknown_speaker_when_no_voice_tag():
    vtt = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nplain caption text\n"
    segments = parse_vtt(vtt)
    assert segments[0].speaker == "Unknown"
    assert segments[0].text == "plain caption text"


def test_parse_vtt_sorts_out_of_order_cues_chronologically():
    vtt = (
        "WEBVTT\n\n"
        "00:00:10.000 --> 00:00:12.000\n<v B>second</v>\n\n"
        "00:00:01.000 --> 00:00:03.000\n<v A>first</v>\n"
    )
    segments = parse_vtt(vtt)
    assert [s.text for s in segments] == ["first", "second"]


def test_parse_vtt_raises_when_no_timed_cues():
    with pytest.raises(ValueError, match="WebVTT"):
        parse_vtt("WEBVTT\n\nNOTE nothing but a comment\n")


def test_looks_like_vtt_detects_header_case_insensitively():
    assert looks_like_vtt(SAMPLE_VTT) is True
    assert looks_like_vtt("  webvtt\n\n...") is True
    assert looks_like_vtt('[{"speaker": "A"}]') is False
    assert looks_like_vtt("0:05 - Alice\nhello") is False


def test_parse_any_routes_webvtt_to_vtt_parser():
    segments = parse_any(SAMPLE_VTT)
    assert len(segments) == 2
    assert segments[0].speaker == "Alice"
