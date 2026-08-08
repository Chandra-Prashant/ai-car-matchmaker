"""Phase machine and per-phase tool scoping.

Serves T020, T021, FR-001, FR-023 and Constitution III.

THE CENTRAL IDEA
----------------
The agent proposes transitions; the orchestrator authorises them. The model
may call `advance_phase` whenever it believes the interview is done, but this
module decides whether it actually is — by inspecting `SessionState`, not by
trusting the model's claim.

When a transition is refused, the refusal is returned to the model as a tool
result naming exactly what is missing. The agent then self-corrects and asks
the user for it. That is better than blocking silently, and it is why the
guard returns a structured `Decision` rather than raising.

WHY TOOL SCOPING MATTERS
------------------------
FR-001 says research must not begin before the five required slots are
filled. A prompt instruction saying so is a request. Removing the search
tools from the model's tool list during the interview is a guarantee — the
model cannot search early because searching is not available to it. This is
the difference between a rule and a hope.

This module imports nothing from any agent SDK and makes no network calls,
so every rule here is unit-testable without an API key.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.state.models import Phase, SessionState

# --------------------------------------------------------------------------
# Tool scoping — T021
# --------------------------------------------------------------------------

#: Tools the model may call in each phase. Anything absent is not merely
#: discouraged; it is not advertised to the model at all.
TOOLS_BY_PHASE: dict[Phase, tuple[str, ...]] = {
    Phase.INTERVIEW: (
        "update_slots",
        "flag_conflict",
        "resolve_conflict",
        "revise_constraints",
        "list_facet_values",
        "advance_phase",
    ),
    Phase.RESEARCH: (
        "search_listings",
        "check_availability",
        "list_facet_values",
        "set_shortlist",
        "revise_constraints",
        "advance_phase",
    ),
    Phase.RECOMMEND: (
        "compare_listings",
        "rank_shortlist",
        "compute_tco",
        "revise_constraints",
        "advance_phase",
    ),
    Phase.BOOK: (
        "open_booking_form",
        "open_checkout",
        "record_booking",
        "compare_listings",
        "advance_phase",
    ),
    Phase.COMPLETE: (),
}

#: Turn caps per phase. Generous enough never to fire in normal use, present
#: so a looping agent terminates rather than spinning in front of a user.
TURN_CAPS: dict[Phase, int] = {
    Phase.INTERVIEW: 14,
    Phase.RESEARCH: 8,
    Phase.RECOMMEND: 6,
    Phase.BOOK: 10,
    Phase.COMPLETE: 0,
}

#: The only transitions that exist. Anything else is rejected outright,
#: including skipping a phase.
ALLOWED_TRANSITIONS: dict[Phase, tuple[Phase, ...]] = {
    Phase.INTERVIEW: (Phase.RESEARCH,),
    Phase.RESEARCH: (Phase.RECOMMEND, Phase.INTERVIEW),
    Phase.RECOMMEND: (Phase.BOOK, Phase.RESEARCH, Phase.INTERVIEW),
    Phase.BOOK: (Phase.COMPLETE, Phase.RECOMMEND),
    Phase.COMPLETE: (),
}


# --------------------------------------------------------------------------
# Decisions
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Decision:
    """The outcome of asking to advance.

    `message` is written for the model to read and act on, so it names the
    specific obstacle rather than saying no.
    """

    allowed: bool
    message: str
    missing: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def yes(cls, message: str) -> Decision:
        return cls(allowed=True, message=message)

    @classmethod
    def no(cls, message: str, missing: tuple[str, ...] = ()) -> Decision:
        return cls(allowed=False, message=message, missing=missing)


# --------------------------------------------------------------------------
# Guards
# --------------------------------------------------------------------------


def _guard_interview_to_research(state: SessionState) -> Decision:
    """FR-001: all five required slots, and no unresolved conflicts."""
    missing = state.constraints.missing_required()
    if missing:
        return Decision.no(
            "Cannot search yet — still missing: "
            + ", ".join(missing)
            + ". Ask the user for these before advancing.",
            missing=tuple(missing),
        )

    open_conflicts = state.open_conflicts
    if open_conflicts:
        descriptions = "; ".join(c.description for c in open_conflicts)
        return Decision.no(
            "Cannot search while constraints conflict: "
            + descriptions
            + ". Ask the user which to relax.",
            missing=tuple(
                f for conflict in open_conflicts for f in conflict.fields
            ),
        )

    return Decision.yes("Interview complete; research may begin.")


def _guard_research_to_recommend(state: SessionState) -> Decision:
    """FR-011: a shortlist exists and is small enough to reason about."""
    if not state.shortlist:
        return Decision.no(
            "Cannot recommend without a shortlist. Search first, then call "
            "set_shortlist with the candidates worth ranking."
        )
    if len(state.shortlist) > 10:
        return Decision.no(
            f"Shortlist has {len(state.shortlist)} listings; narrow it to at "
            "most 10 before ranking."
        )
    return Decision.yes(f"Shortlist of {len(state.shortlist)} ready to rank.")


def _guard_recommend_to_book(state: SessionState) -> Decision:
    """Constitution IV: nothing is offered for booking without an explanation."""
    if not state.reasoning_log:
        return Decision.no(
            "Rank the shortlist before booking — every recommendation needs "
            "its reasoning recorded first."
        )
    ranked = {record.listing_id for record in state.reasoning_log}
    unexplained = [x for x in state.shortlist if x not in ranked]
    if unexplained:
        return Decision.no(
            "These listings have no reasoning recorded: "
            + ", ".join(unexplained)
            + ". Rank them or drop them from the shortlist.",
            missing=tuple(unexplained),
        )
    return Decision.yes("Recommendations explained; booking may proceed.")


def _guard_book_to_complete(state: SessionState) -> Decision:
    """FR-022: completion means a confirmation record exists."""
    if not state.booking_id:
        return Decision.no("No booking has been created yet.")
    if not state.confirmation_reference:
        return Decision.no(
            f"Booking {state.booking_id} exists but has no confirmation "
            "reference — checkout has not completed."
        )
    return Decision.yes(
        f"Confirmed: {state.confirmation_reference}."
    )


def _guard_backward(state: SessionState, target: Phase) -> Decision:
    """Going back is always permitted.

    A user changing their mind (Scenario C) must never be blocked by a
    forward-only state machine. Going back discards work that no longer
    applies, which the caller handles.
    """
    return Decision.yes(f"Returning to {target.value} at the user's direction.")


_FORWARD_GUARDS = {
    (Phase.INTERVIEW, Phase.RESEARCH): _guard_interview_to_research,
    (Phase.RESEARCH, Phase.RECOMMEND): _guard_research_to_recommend,
    (Phase.RECOMMEND, Phase.BOOK): _guard_recommend_to_book,
    (Phase.BOOK, Phase.COMPLETE): _guard_book_to_complete,
}

_PHASE_ORDER = [
    Phase.INTERVIEW, Phase.RESEARCH, Phase.RECOMMEND, Phase.BOOK, Phase.COMPLETE
]


def is_backward(current: Phase, target: Phase) -> bool:
    return _PHASE_ORDER.index(target) < _PHASE_ORDER.index(current)


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def available_tools(state: SessionState) -> tuple[str, ...]:
    """Tools the model may be offered right now."""
    return TOOLS_BY_PHASE[state.phase]


def is_tool_allowed(state: SessionState, tool_name: str) -> bool:
    return tool_name in TOOLS_BY_PHASE[state.phase]


def can_advance(state: SessionState, target: Phase) -> Decision:
    """Whether the state may move to `target`. Pure — mutates nothing."""
    if target == state.phase:
        return Decision.no(f"Already in {target.value}.")

    if target not in ALLOWED_TRANSITIONS[state.phase]:
        allowed = ALLOWED_TRANSITIONS[state.phase]
        return Decision.no(
            f"Cannot move from {state.phase.value} to {target.value}. "
            + (
                "Allowed: " + ", ".join(p.value for p in allowed)
                if allowed
                else "This session is finished."
            )
        )

    if is_backward(state.phase, target):
        return _guard_backward(state, target)

    guard = _FORWARD_GUARDS.get((state.phase, target))
    if guard is None:  # pragma: no cover - defensive
        return Decision.no("No guard defined for that transition.")
    return guard(state)


def advance(state: SessionState, target: Phase) -> Decision:
    """Attempt a transition, applying it only if the guard permits.

    Returns the decision either way. On refusal the state is untouched and
    the message tells the model what to do about it.
    """
    decision = can_advance(state, target)
    if not decision.allowed:
        return decision

    if is_backward(state.phase, target):
        _discard_downstream_work(state, target)

    state.transition_to(target, decision.message)
    return decision


def _discard_downstream_work(state: SessionState, target: Phase) -> None:
    """Clear results that no longer apply when moving backwards.

    Keeping a stale shortlist after the user reopens the interview would let
    outdated recommendations resurface as if they still matched.
    """
    if target in (Phase.INTERVIEW, Phase.RESEARCH):
        state.reasoning_log = []
        state.inferred_weights = {}
    if target == Phase.INTERVIEW:
        state.shortlist = []


def turn_cap_reached(state: SessionState) -> bool:
    return state.turns_in_phase >= TURN_CAPS[state.phase]


def phase_status(state: SessionState) -> dict:
    """Everything the progress UI needs about where the session stands."""
    next_phases = ALLOWED_TRANSITIONS[state.phase]
    forward = [p for p in next_phases if not is_backward(state.phase, p)]
    blocking = can_advance(state, forward[0]) if forward else None

    return {
        "phase": state.phase.value,
        "turns_in_phase": state.turns_in_phase,
        "turn_cap": TURN_CAPS[state.phase],
        "tools": list(available_tools(state)),
        "next_phase": forward[0].value if forward else None,
        "can_advance": blocking.allowed if blocking else False,
        "blocked_by": None if not blocking or blocking.allowed else blocking.message,
    }
