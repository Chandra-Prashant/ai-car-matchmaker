"""Phase machine tests.

These prove the FR-001 guarantee — research cannot begin before the interview
is complete — without an API key, a network call, or a model. That is the
point of keeping the state machine free of any agent SDK: the guarantee is
testable rather than asserted.

Doubles as the foundation for the T045 eval suite.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.agent.phases import (
    ALLOWED_TRANSITIONS,
    TOOLS_BY_PHASE,
    TURN_CAPS,
    advance,
    available_tools,
    can_advance,
    is_tool_allowed,
    phase_status,
    turn_cap_reached,
)
from app.models.listing import Mode
from app.state.models import (
    Conflict,
    Phase,
    ReasoningRecord,
    SessionState,
)


def _fresh() -> SessionState:
    return SessionState(session_id="ses-test")


def _interviewed() -> SessionState:
    state = _fresh()
    state.constraints.mode = Mode.BUY
    state.constraints.use_case = "daily commute"
    state.constraints.category = "compact_suv"
    state.constraints.budget_max = 1_500_000
    state.constraints.target_date = date(2026, 10, 1)
    return state


def _researched() -> SessionState:
    state = _interviewed()
    advance(state, Phase.RESEARCH)
    state.shortlist = ["lst-0001", "lst-0002", "lst-0003"]
    return state


def _recommended() -> SessionState:
    state = _researched()
    advance(state, Phase.RECOMMEND)
    state.reasoning_log = [
        ReasoningRecord(listing_id=x, rank=i + 1, total_score=0.9 - i * 0.1)
        for i, x in enumerate(state.shortlist)
    ]
    return state


# --------------------------------------------------------------------------
# FR-001 — no research before the interview is complete
# --------------------------------------------------------------------------


def test_fresh_session_cannot_research():
    decision = can_advance(_fresh(), Phase.RESEARCH)
    assert not decision.allowed
    assert set(decision.missing) == {
        "mode", "use_case", "category", "budget_max", "target_date"
    }


@pytest.mark.parametrize(
    "omit", ["mode", "use_case", "category", "budget_max", "target_date"]
)
def test_any_single_missing_slot_blocks_research(omit):
    state = _interviewed()
    setattr(state.constraints, omit, None)
    decision = can_advance(state, Phase.RESEARCH)
    assert not decision.allowed
    assert omit in decision.missing


def test_complete_interview_may_research():
    assert can_advance(_interviewed(), Phase.RESEARCH).allowed


def test_refusal_names_what_is_missing():
    """The message goes to the model, so it must be actionable."""
    state = _interviewed()
    state.constraints.budget_max = None
    message = can_advance(state, Phase.RESEARCH).message
    assert "budget_max" in message


def test_refused_transition_leaves_state_untouched():
    state = _fresh()
    advance(state, Phase.RESEARCH)
    assert state.phase is Phase.INTERVIEW
    assert state.transitions == []


# --------------------------------------------------------------------------
# FR-006 — open conflicts block progress
# --------------------------------------------------------------------------


def test_open_conflict_blocks_research():
    state = _interviewed()
    state.conflicts.append(
        Conflict(
            kind="budget_vs_category",
            fields=["budget_max", "category"],
            description="No luxury SUV exists under Rs.15 lakh",
        )
    )
    assert not can_advance(state, Phase.RESEARCH).allowed


def test_resolved_conflict_does_not_block():
    state = _interviewed()
    state.conflicts.append(
        Conflict(
            kind="budget_vs_category",
            fields=["budget_max"],
            description="resolved already",
            resolved=True,
        )
    )
    assert can_advance(state, Phase.RESEARCH).allowed


# --------------------------------------------------------------------------
# FR-011 — shortlist bounds
# --------------------------------------------------------------------------


def test_empty_shortlist_blocks_recommend():
    state = _interviewed()
    advance(state, Phase.RESEARCH)
    assert not can_advance(state, Phase.RECOMMEND).allowed


def test_oversized_shortlist_blocks_recommend():
    state = _researched()
    state.shortlist = [f"lst-{i:04d}" for i in range(1, 15)]
    decision = can_advance(state, Phase.RECOMMEND)
    assert not decision.allowed
    assert "10" in decision.message


def test_reasonable_shortlist_may_be_ranked():
    assert can_advance(_researched(), Phase.RECOMMEND).allowed


# --------------------------------------------------------------------------
# Constitution IV — nothing unexplained reaches booking
# --------------------------------------------------------------------------


def test_unranked_shortlist_blocks_booking():
    state = _researched()
    advance(state, Phase.RECOMMEND)
    assert not can_advance(state, Phase.BOOK).allowed


def test_partially_ranked_shortlist_names_the_gaps():
    state = _recommended()
    state.shortlist.append("lst-0099")
    decision = can_advance(state, Phase.BOOK)
    assert not decision.allowed
    assert "lst-0099" in decision.missing


def test_fully_ranked_shortlist_may_book():
    assert can_advance(_recommended(), Phase.BOOK).allowed


# --------------------------------------------------------------------------
# FR-022 — completion requires a confirmation record
# --------------------------------------------------------------------------


def test_booking_without_reference_cannot_complete():
    state = _recommended()
    advance(state, Phase.BOOK)
    state.booking_id = "bkg-1"
    assert not can_advance(state, Phase.COMPLETE).allowed


def test_confirmed_booking_completes():
    state = _recommended()
    advance(state, Phase.BOOK)
    state.booking_id = "bkg-1"
    state.confirmation_reference = "SIM-ABCD1234"
    assert advance(state, Phase.COMPLETE).allowed
    assert state.phase is Phase.COMPLETE


# --------------------------------------------------------------------------
# Structural rules
# --------------------------------------------------------------------------


def test_phases_cannot_be_skipped():
    assert not can_advance(_interviewed(), Phase.BOOK).allowed


def test_advancing_to_the_current_phase_is_refused():
    assert not can_advance(_fresh(), Phase.INTERVIEW).allowed


def test_complete_is_terminal():
    assert ALLOWED_TRANSITIONS[Phase.COMPLETE] == ()
    assert TOOLS_BY_PHASE[Phase.COMPLETE] == ()


def test_every_phase_declares_tools_and_a_cap():
    for phase in Phase:
        assert phase in TOOLS_BY_PHASE
        assert phase in TURN_CAPS
        assert phase in ALLOWED_TRANSITIONS


# --------------------------------------------------------------------------
# Backward movement — Scenario C
# --------------------------------------------------------------------------


def test_user_may_always_go_back():
    assert advance(_recommended(), Phase.INTERVIEW).allowed


def test_going_back_to_interview_discards_shortlist_and_reasoning():
    state = _recommended()
    advance(state, Phase.INTERVIEW)
    assert state.shortlist == []
    assert state.reasoning_log == []


def test_going_back_to_research_keeps_shortlist_but_drops_reasoning():
    state = _recommended()
    advance(state, Phase.RESEARCH)
    assert state.shortlist
    assert state.reasoning_log == []


def test_transitions_are_recorded_for_replay():
    state = _recommended()
    assert [t.to_phase for t in state.transitions] == [
        Phase.RESEARCH, Phase.RECOMMEND
    ]
    assert all(t.reason for t in state.transitions)


# --------------------------------------------------------------------------
# T021 — tool scoping
# --------------------------------------------------------------------------


def test_search_tools_are_absent_during_the_interview():
    """The structural half of FR-001: the model cannot search early because
    searching is not offered to it."""
    state = _fresh()
    assert "search_listings" not in available_tools(state)
    assert not is_tool_allowed(state, "search_listings")


def test_search_tools_appear_in_research():
    assert is_tool_allowed(_researched(), "search_listings")


def test_booking_tools_are_absent_before_the_book_phase():
    for state in (_fresh(), _researched(), _recommended()):
        assert not is_tool_allowed(state, "open_booking_form")
        assert not is_tool_allowed(state, "open_checkout")


def test_slot_updates_are_not_available_after_the_interview():
    assert not is_tool_allowed(_researched(), "update_slots")


def test_revise_constraints_is_available_throughout():
    """The user may change their mind at any point (FR-007)."""
    for state in (_fresh(), _researched(), _recommended()):
        assert is_tool_allowed(state, "revise_constraints")


# --------------------------------------------------------------------------
# Turn caps
# --------------------------------------------------------------------------


def test_turn_cap_not_reached_initially():
    assert not turn_cap_reached(_fresh())


def test_turn_cap_fires_at_the_limit():
    state = _fresh()
    state.turns_in_phase = TURN_CAPS[Phase.INTERVIEW]
    assert turn_cap_reached(state)


def test_turn_counter_resets_on_transition():
    state = _interviewed()
    state.turns_in_phase = 9
    advance(state, Phase.RESEARCH)
    assert state.turns_in_phase == 0


# --------------------------------------------------------------------------
# Status view
# --------------------------------------------------------------------------


def test_status_reports_the_blocking_reason():
    status = phase_status(_fresh())
    assert status["phase"] == "interview"
    assert status["next_phase"] == "research"
    assert status["can_advance"] is False
    assert "missing" in status["blocked_by"]


def test_status_clears_once_unblocked():
    status = phase_status(_interviewed())
    assert status["can_advance"] is True
    assert status["blocked_by"] is None
