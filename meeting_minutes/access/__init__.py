"""Access control (RBAC) for meetings, transcripts, and minutes.

The authorization decision is pure logic over plain domain objects (no database
or framework coupling) so it is exhaustively unit-testable. The persistence and
FastAPI layers adapt their rows/identities into these objects and record the
returned :class:`AccessDecision.reason` in the audit log.
"""

from .authz import AccessDecision, can_view, visible_meetings
from .models import Meeting, OrgChart, Role, Share, User

__all__ = [
    "AccessDecision",
    "Meeting",
    "OrgChart",
    "Role",
    "Share",
    "User",
    "can_view",
    "visible_meetings",
]
