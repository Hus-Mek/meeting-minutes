"""Domain objects for access control. All immutable; no DB/framework coupling."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum


class Role(str, Enum):
    """Coarse role tier, mapped from Entra ID groups / app roles.

    ``ADMIN`` is the exec/admin tier (CEO/VP/compliance) that sees every meeting.
    ``MANAGER`` and ``MEMBER`` gain access only through the relationship rules
    (attendance, manager-of-attendee, explicit share).
    """

    ADMIN = "admin"
    MANAGER = "manager"
    MEMBER = "member"


@dataclass(frozen=True)
class User:
    """An authenticated person. ``id`` is the internal/Entra object id; ``upn``
    is their email/UPN (used to match meeting participants)."""

    id: str
    upn: str
    role: Role = Role.MEMBER
    department: str | None = None


@dataclass(frozen=True)
class Meeting:
    """A meeting whose transcript/minutes are access-controlled.

    ``participant_ids`` are the internal user ids of resolved attendees.
    """

    id: str
    organizer_id: str
    participant_ids: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Share:
    """An explicit per-meeting grant of view access to one user."""

    meeting_id: str
    user_id: str


@dataclass(frozen=True)
class OrgChart:
    """The manager hierarchy: each user id maps to their manager's user id.

    Built by syncing ``manager``/``directReports`` from Microsoft Graph. Walks
    are cycle-safe so a corrupt sync cannot hang the request.
    """

    manager_of: Mapping[str, str]

    def manager_chain(self, user_id: str) -> tuple[str, ...]:
        """Return ``user_id``'s managers from nearest to furthest (cycle-safe)."""
        chain: list[str] = []
        seen: set[str] = {user_id}
        current = self.manager_of.get(user_id)
        while current is not None and current not in seen:
            chain.append(current)
            seen.add(current)
            current = self.manager_of.get(current)
        return tuple(chain)

    def is_manager_of(self, manager_id: str, report_id: str) -> bool:
        """True if ``manager_id`` is a (possibly transitive) manager of ``report_id``."""
        return manager_id in self.manager_chain(report_id)
