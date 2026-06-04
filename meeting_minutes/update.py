"""Lightweight "is there a newer version?" check against GitHub Releases.

Compares the running :data:`meeting_minutes.__version__` against the latest
published release of the public repo and reports whether a newer build exists,
plus a direct download link for the installer asset.

Design rules:

- **Never raises to the caller.** Any network/parse/HTTP error degrades to
  "no update available" so a transient GitHub hiccup can't block startup or
  annoy the user. The single seam for that is :func:`_fetch_latest_release`,
  which returns ``None`` on failure (and is monkeypatched in tests).
- **No new dependencies.** Uses the stdlib ``urllib`` (as ``desktop.py`` does)
  rather than pulling httpx into this path.
- **Public repo, no auth needed.** The repo is public, so the unauthenticated
  Releases API works. An optional ``MM_UPDATE_TOKEN`` / ``GITHUB_TOKEN`` is sent
  if present (raises the low anonymous rate limit), but is never required.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass

from . import __version__

# The public repo to check. Kept as a constant (matches the git remote) rather
# than discovered at runtime so the frozen app needs no git/remote access.
REPO = "Hus-Mek/meeting-minutes"
_RELEASES_LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

# The installer asset the user actually wants to download (see installer.iss
# OutputBaseFilename). Matched case-insensitively against release asset names.
_INSTALLER_SUFFIX = ".exe"

_DEFAULT_TIMEOUT_S = 5.0

# Env vars that may carry a GitHub token to lift the anonymous rate limit. Both
# are OPTIONAL — the public Releases API works unauthenticated.
_TOKEN_ENV_VARS = ("MM_UPDATE_TOKEN", "GITHUB_TOKEN")

__all__ = ["UpdateInfo", "check_for_update", "is_newer", "parse_version", "__version__"]


@dataclass(frozen=True)
class UpdateInfo:
    """The result of an update check.

    ``latest``/``html_url``/``download_url`` are ``None`` when the check could not
    reach GitHub (in which case ``update_available`` is always ``False``).
    """

    current: str
    latest: str | None
    update_available: bool
    html_url: str | None
    download_url: str | None

    def as_dict(self) -> dict[str, object]:
        """A plain JSON-serializable dict (returned verbatim by the web layer)."""
        return asdict(self)


def parse_version(tag: str) -> tuple[int, ...]:
    """Turn a version tag into a comparable tuple of ints.

    Strips a leading ``v``/``V`` and keeps only the leading-numeric part of each
    dotted component, so ``"v1.2.3-beta.1"`` -> ``(1, 2, 3)``. Non-numeric junk
    yields ``()`` rather than raising.
    """
    cleaned = tag.strip().lstrip("vV")
    parts: list[int] = []
    for component in cleaned.split("."):
        match = re.match(r"\d+", component)
        if not match:
            break  # no leading digit (e.g. "nightly") — stop here
        parts.append(int(match.group()))
        if match.group() != component:
            break  # a non-numeric suffix (e.g. "3-beta") marks a pre-release boundary
    return tuple(parts)


def is_newer(latest: str, current: str) -> bool:
    """Is ``latest`` a strictly newer version than ``current``?

    Compares numerically (so ``1.0.10 > 1.0.9``) and zero-pads the shorter tuple
    so ``1.0.4`` and ``1.0.4.0`` compare equal. If *either* side is unparseable
    (e.g. ``"nightly"`` -> ``()``), reports "not newer" rather than treating the
    empty tuple as ``(0, 0, ...)`` and falsely flagging an update.
    """
    a = parse_version(latest)
    b = parse_version(current)
    if not a or not b:
        return False
    width = max(len(a), len(b))
    a += (0,) * (width - len(a))
    b += (0,) * (width - len(b))
    return a > b


def _is_https(url: object) -> bool:
    """True only for an ``https://`` string URL (defense-in-depth at the sink)."""
    return isinstance(url, str) and url.lower().startswith("https://")


def _auth_token() -> str | None:
    """An optional GitHub token from the environment (first non-empty wins)."""
    for var in _TOKEN_ENV_VARS:
        value = os.environ.get(var, "").strip()
        if value:
            return value
    return None


def _fetch_latest_release(*, timeout: float = _DEFAULT_TIMEOUT_S) -> dict | None:
    """Fetch the latest-release JSON from GitHub, or ``None`` on any failure.

    This is the only network seam; tests monkeypatch it. It must never raise.
    """
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "MeetingMinutes-UpdateCheck",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = _auth_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(_RELEASES_LATEST_URL, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:  # noqa: S310 — fixed https URL
            if resp.status != 200:
                return None
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _installer_download_url(release: dict, fallback: str | None) -> str | None:
    """The installer (.exe) asset's ``https`` download URL, else the release page URL."""
    assets = release.get("assets")
    if isinstance(assets, list):
        for asset in assets:
            name = (asset or {}).get("name", "")
            if isinstance(name, str) and name.lower().endswith(_INSTALLER_SUFFIX):
                url = asset.get("browser_download_url")
                if _is_https(url):
                    return url
    return fallback


def check_for_update(
    current: str | None = None, *, timeout: float = _DEFAULT_TIMEOUT_S
) -> UpdateInfo:
    """Check whether a newer release than ``current`` is published on GitHub.

    Returns an :class:`UpdateInfo`. Always succeeds: on any failure it reports
    ``update_available=False`` with ``latest=None``.
    """
    running = current if current is not None else __version__
    release = _fetch_latest_release(timeout=timeout)
    if not release:
        return UpdateInfo(
            current=running,
            latest=None,
            update_available=False,
            html_url=None,
            download_url=None,
        )

    # Normalize untrusted fields: a malformed/spoofed payload could carry a
    # non-string tag_name (which would crash parse_version) or a non-https URL.
    raw_latest = release.get("tag_name")
    latest = raw_latest if isinstance(raw_latest, str) else None
    raw_html = release.get("html_url")
    html_url = raw_html if _is_https(raw_html) else None

    # `latest is not None` (not bool(latest)) so mypy narrows str | None -> str for
    # is_newer; an empty string still yields parse_version("") == () -> not newer.
    available = latest is not None and is_newer(latest, running)
    download_url = _installer_download_url(release, html_url) if available else None
    return UpdateInfo(
        current=running,
        latest=latest,
        update_available=available,
        html_url=html_url,
        download_url=download_url,
    )
