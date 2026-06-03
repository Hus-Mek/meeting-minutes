"""The authorization decision: may a user view a meeting's transcript/minutes?

A user is granted view access if **any** of the configured rules holds (the four
the user asked to combine), checked in this order so the recorded reason is the
strongest applicable one:

1. ``role:admin``       — exec/admin tier sees everything.
2. ``organizer``        — they organized the meeting.
3. ``attendance``       — they attended (their id is in the participant set).
4. ``manager_of:<id>``  — they are a (transitive) manager of the organizer or an attendee.
5. ``explicit_share``   — an owner/admin granted them access to this meeting.

Otherwise access is ``denied``. The function is pure: callers pass the org chart
and the relevant shares, and persist :attr:`AccessDecision.reason` for audit.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .models import Meeting, OrgChart, Role, Share, User


@dataclass(frozen=True)
class AccessDecision:
    """The outcome of an access check, with a machine-readable reason for audit."""

    allowed: bool
    reason: str

    def __bool__(self) -> bool:
        return self.allowed


def _share_keys(shares: Iterable[Share] | Iterable[tuple[str, str]]) -> set[tuple[str, str]]:
    keys: set[tuple[str, str]] = set()
    for share in shares:
        if isinstance(share, Share):
            keys.add((share.meeting_id, share.user_id))
        else:
            keys.add((share[0], share[1]))
    return keys


def can_view(
    user: User,
    meeting: Meeting,
    *,
    org: OrgChart | None = None,
    shares: Iterable[Share] | Iterable[tuple[str, str]] = (),
) -> AccessDecision:
    """Decide whether ``user`` may view ``meeting`` (see module docstring for rules)."""
    if user.role is Role.ADMIN:
        return AccessDecision(True, "role:admin")

    if user.id == meeting.organizer_id:
        return AccessDecision(True, "organizer")

    if user.id in meeting.participant_ids:
        return AccessDecision(True, "attendance")

    if org is not None:
        for related_id in (meeting.organizer_id, *sorted(meeting.participant_ids)):
            if org.is_manager_of(user.id, related_id):
                return AccessDecision(True, f"manager_of:{related_id}")

    if (meeting.id, user.id) in _share_keys(shares):
        return AccessDecision(True, "explicit_share")

    return AccessDecision(False, "denied")


def visible_meetings(
    user: User,
    meetings: Iterable[Meeting],
    *,
    org: OrgChart | None = None,
    shares: Iterable[Share] | Iterable[tuple[str, str]] = (),
) -> list[Meeting]:
    """Filter ``meetings`` to those ``user`` may view (for list endpoints)."""
    share_keys = _share_keys(shares)
    return [
        meeting
        for meeting in meetings
        if can_view(user, meeting, org=org, shares=share_keys).allowed
    ]
