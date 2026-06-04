"""Tests for the GitHub-releases update checker (``meeting_minutes.update``).

The network call is stubbed via ``_fetch_latest_release`` so these tests never
touch GitHub. The checker must fail SILENTLY (report "no update") on any error so
a transient hiccup never blocks the user.
"""

from __future__ import annotations

import pytest

from meeting_minutes import update


# --- parse_version ----------------------------------------------------------


@pytest.mark.parametrize(
    ("tag", "expected"),
    [
        ("1.0.4", (1, 0, 4)),
        ("v1.0.4", (1, 0, 4)),
        ("V2.10.0", (2, 10, 0)),
        ("1.2.3-beta.1", (1, 2, 3)),  # numeric prefixes only
        ("v1.0", (1, 0)),
    ],
)
def test_parse_version_strips_prefix_and_suffix(tag, expected):
    assert update.parse_version(tag) == expected


def test_parse_version_tolerates_garbage():
    # Non-numeric junk parses to an empty tuple rather than raising.
    assert update.parse_version("nightly") == ()
    assert update.parse_version("") == ()


# --- is_newer ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("latest", "current", "expected"),
    [
        ("1.0.4", "1.0.3", True),
        ("v1.0.4", "1.0.4", False),  # equal
        ("1.0.3", "1.0.4", False),  # older
        ("1.1.0", "1.0.9", True),
        ("2.0.0", "1.9.9", True),
        ("1.0.4", "1.0.4.0", False),  # zero-padded equal
        ("1.0.10", "1.0.9", True),  # numeric, not lexical, compare
        ("1.0.0", "nightly", False),  # unparseable current → never "newer"
        ("nightly", "1.0.0", False),  # unparseable latest → never "newer"
    ],
)
def test_is_newer(latest, current, expected):
    assert update.is_newer(latest, current) is expected


# --- check_for_update -------------------------------------------------------


def _release(tag="v1.0.4", *, asset_name="MeetingMinutes-Setup.exe"):
    return {
        "tag_name": tag,
        "html_url": f"https://github.com/Hus-Mek/meeting-minutes/releases/tag/{tag}",
        "assets": [
            {"name": "source.zip", "browser_download_url": "https://example/source.zip"},
            {
                "name": asset_name,
                "browser_download_url": f"https://github.com/Hus-Mek/meeting-minutes/releases/download/{tag}/{asset_name}",
            },
        ],
    }


def test_reports_update_when_newer(monkeypatch):
    # Arrange
    monkeypatch.setattr(update, "_fetch_latest_release", lambda **_: _release("v1.0.4"))

    # Act
    info = update.check_for_update(current="1.0.3")

    # Assert
    assert info.update_available is True
    assert info.latest == "v1.0.4"
    assert info.current == "1.0.3"
    assert info.download_url.endswith("MeetingMinutes-Setup.exe")
    assert info.html_url.endswith("/tag/v1.0.4")


def test_no_update_when_running_latest(monkeypatch):
    monkeypatch.setattr(update, "_fetch_latest_release", lambda **_: _release("v1.0.4"))
    info = update.check_for_update(current="1.0.4")
    assert info.update_available is False
    assert info.latest == "v1.0.4"


def test_falls_back_to_html_url_when_no_installer_asset(monkeypatch):
    monkeypatch.setattr(
        update, "_fetch_latest_release", lambda **_: _release("v2.0.0", asset_name="notes.txt")
    )
    info = update.check_for_update(current="1.0.4")
    assert info.update_available is True
    # No .exe asset → the download link points at the release page.
    assert info.download_url == info.html_url


def test_silent_when_fetch_fails(monkeypatch):
    # Arrange — network/parse failure surfaces as None, never an exception.
    monkeypatch.setattr(update, "_fetch_latest_release", lambda **_: None)

    # Act
    info = update.check_for_update(current="1.0.3")

    # Assert — degrades to "no update", current preserved.
    assert info.update_available is False
    assert info.latest is None
    assert info.download_url is None
    assert info.current == "1.0.3"


def test_defaults_current_to_package_version(monkeypatch):
    monkeypatch.setattr(update, "_fetch_latest_release", lambda **_: None)
    info = update.check_for_update()
    assert info.current == update.__version__


def test_never_raises_on_corrupt_payload(monkeypatch):
    # Arrange — a malformed/spoofed payload: non-string tag_name + junk assets.
    # parse_version("strip") would crash on a non-string, so this guards the contract.
    monkeypatch.setattr(
        update,
        "_fetch_latest_release",
        lambda **_: {"tag_name": 123, "html_url": 456, "assets": "not-a-list"},
    )

    # Act — must NOT raise.
    info = update.check_for_update(current="1.0.3")

    # Assert — degrades safely to "no update".
    assert info.update_available is False
    assert info.latest is None
    assert info.html_url is None
    assert info.download_url is None


def test_rejects_non_https_download_url(monkeypatch):
    # Arrange — a newer release whose installer asset URL is NOT https (spoofed/MITM).
    monkeypatch.setattr(
        update,
        "_fetch_latest_release",
        lambda **_: {
            "tag_name": "v2.0.0",
            "html_url": "https://github.com/Hus-Mek/meeting-minutes/releases/tag/v2.0.0",
            "assets": [
                {
                    "name": "MeetingMinutes-Setup.exe",
                    "browser_download_url": "http://evil.example/MeetingMinutes-Setup.exe",
                }
            ],
        },
    )

    # Act
    info = update.check_for_update(current="1.0.4")

    # Assert — the non-https asset is rejected; falls back to the https release page.
    assert info.update_available is True
    assert info.download_url == info.html_url
    assert info.download_url.startswith("https://")


def test_as_dict_is_json_serializable(monkeypatch):
    import json

    monkeypatch.setattr(update, "_fetch_latest_release", lambda **_: _release("v1.0.4"))
    info = update.check_for_update(current="1.0.3")
    payload = info.as_dict()
    # Round-trips through JSON (the web layer returns this verbatim).
    assert json.loads(json.dumps(payload))["update_available"] is True
    assert set(payload) == {
        "current",
        "latest",
        "update_available",
        "html_url",
        "download_url",
    }
