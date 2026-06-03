"""Tests for the RBAC access decision — the four combined rules, positive AND
negative. Negative tests matter most: they prove access is denied by default."""

import pytest

from meeting_minutes.access import (
    Meeting,
    OrgChart,
    Role,
    Share,
    User,
    can_view,
    visible_meetings,
)

# --- fixtures: a small org -------------------------------------------------
# ceo -> vp -> manager -> alice ; bob reports to manager too ; carol unrelated.
ORG = OrgChart(
    manager_of={
        "vp": "ceo",
        "manager": "vp",
        "alice": "manager",
        "bob": "manager",
        "carol": "ceo",  # different branch
    }
)

ALICE = User(id="alice", upn="alice@corp.sa", role=Role.MEMBER, department="Eng")
BOB = User(id="bob", upn="bob@corp.sa", role=Role.MEMBER, department="Eng")
CAROL = User(id="carol", upn="carol@corp.sa", role=Role.MEMBER, department="Sales")
MANAGER = User(id="manager", upn="mgr@corp.sa", role=Role.MANAGER, department="Eng")
VP = User(id="vp", upn="vp@corp.sa", role=Role.MANAGER, department="Eng")
CEO = User(id="ceo", upn="ceo@corp.sa", role=Role.ADMIN)

# A meeting alice organized, with bob attending. manager/vp/ceo are above them.
MEETING = Meeting(id="m1", organizer_id="alice", participant_ids=frozenset({"alice", "bob"}))


# --- role tier -------------------------------------------------------------
@pytest.mark.unit
def test_admin_role_sees_any_meeting():
    decision = can_view(CEO, MEETING, org=ORG)
    assert decision.allowed is True
    assert decision.reason == "role:admin"


# --- organizer + attendance ------------------------------------------------
@pytest.mark.unit
def test_organizer_can_view_own_meeting():
    decision = can_view(ALICE, MEETING, org=ORG)
    assert decision.allowed is True
    assert decision.reason == "organizer"


@pytest.mark.unit
def test_attendee_can_view_meeting_they_attended():
    decision = can_view(BOB, MEETING, org=ORG)
    assert decision.allowed is True
    assert decision.reason == "attendance"


# --- manager hierarchy (transitive) ----------------------------------------
@pytest.mark.unit
def test_direct_manager_can_view_reports_meeting():
    decision = can_view(MANAGER, MEETING, org=ORG)
    assert decision.allowed is True
    assert decision.reason.startswith("manager_of:")


@pytest.mark.unit
def test_transitive_manager_can_view_meeting():
    # vp manages manager manages alice/bob -> vp sees it transitively.
    decision = can_view(VP, MEETING, org=ORG)
    assert decision.allowed is True
    assert decision.reason.startswith("manager_of:")


# --- explicit share --------------------------------------------------------
@pytest.mark.unit
def test_explicit_share_grants_access_to_unrelated_user():
    decision = can_view(CAROL, MEETING, org=ORG, shares=[Share("m1", "carol")])
    assert decision.allowed is True
    assert decision.reason == "explicit_share"


@pytest.mark.unit
def test_share_for_a_different_meeting_does_not_grant_access():
    decision = can_view(CAROL, MEETING, org=ORG, shares=[Share("other", "carol")])
    assert decision.allowed is False


@pytest.mark.unit
def test_share_accepts_tuple_form():
    decision = can_view(CAROL, MEETING, shares=[("m1", "carol")])
    assert decision.allowed is True


# --- negative: the default is DENY -----------------------------------------
@pytest.mark.unit
def test_unrelated_member_is_denied():
    decision = can_view(CAROL, MEETING, org=ORG)
    assert decision.allowed is False
    assert decision.reason == "denied"


@pytest.mark.unit
def test_subordinate_cannot_view_managers_unrelated_meeting():
    # A meeting carol's manager (ceo) organized; carol must NOT see it upward.
    boss_meeting = Meeting(id="m2", organizer_id="ceo", participant_ids=frozenset({"ceo"}))
    decision = can_view(CAROL, boss_meeting, org=ORG)
    assert decision.allowed is False


@pytest.mark.unit
def test_peer_cannot_view_via_hierarchy():
    # alice and bob are peers (both report to manager); peers get no hierarchy access.
    bob_only = Meeting(id="m3", organizer_id="bob", participant_ids=frozenset({"bob"}))
    decision = can_view(ALICE, bob_only, org=ORG)
    assert decision.allowed is False


@pytest.mark.unit
def test_without_org_chart_hierarchy_rule_is_skipped_not_errored():
    # manager would normally qualify via hierarchy; with no org chart, denied cleanly.
    decision = can_view(MANAGER, MEETING)  # org=None
    assert decision.allowed is False
    assert decision.reason == "denied"


# --- org chart safety ------------------------------------------------------
@pytest.mark.unit
def test_manager_chain_is_cycle_safe():
    cyclic = OrgChart(manager_of={"a": "b", "b": "a"})
    # Must terminate, not hang.
    assert cyclic.is_manager_of("b", "a") is True
    assert cyclic.is_manager_of("a", "b") is True
    assert cyclic.is_manager_of("c", "a") is False


@pytest.mark.unit
def test_manager_chain_orders_nearest_first():
    assert ORG.manager_chain("alice") == ("manager", "vp", "ceo")


# --- list filtering --------------------------------------------------------
@pytest.mark.unit
def test_visible_meetings_filters_to_authorized_only():
    m_alice = Meeting(id="ma", organizer_id="alice", participant_ids=frozenset({"alice"}))
    m_carol = Meeting(id="mc", organizer_id="carol", participant_ids=frozenset({"carol"}))
    visible = visible_meetings(ALICE, [m_alice, m_carol], org=ORG)
    assert [m.id for m in visible] == ["ma"]


@pytest.mark.unit
def test_visible_meetings_admin_sees_all():
    m_alice = Meeting(id="ma", organizer_id="alice", participant_ids=frozenset({"alice"}))
    m_carol = Meeting(id="mc", organizer_id="carol", participant_ids=frozenset({"carol"}))
    visible = visible_meetings(CEO, [m_alice, m_carol], org=ORG)
    assert {m.id for m in visible} == {"ma", "mc"}


@pytest.mark.unit
def test_access_decision_is_truthy_when_allowed():
    assert bool(can_view(CEO, MEETING)) is True
    assert bool(can_view(CAROL, MEETING)) is False
