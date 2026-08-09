"""A scripted agent runner.

Not a mock in the throwaway sense — this is a permanent fixture with two
jobs:

1. It lets the transport, the API and the whole frontend be built and
   verified before the model loop exists. Everything downstream of the event
   stream can be developed against something deterministic.
2. It is what the T044 eval harness drives. Asserting agent behaviour
   against a real model is slow, costly and flaky; asserting that the
   *machinery* behaves given a known sequence of tool calls is fast and
   exact. The model-driven evals then only have to check the model's
   choices, not the plumbing.

It calls the same tool registry the real runner will, so the state
transitions it produces are genuine — only the decision of which tool to
call next is scripted rather than inferred. That means the guards in
phases.py apply here too: a script that skips a required step gets refused
exactly as a model would.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.agent import tools
from app.a2ui import surfaces as a2ui
from app.agent.runner import UI_TOOLS, _call_ui_tool, _surfaces_for
from app.api.events import (
    AgentEvent,
    done_event,
    message,
    phase_event,
    progress,
    a2ui_message,
    state_event,
    tool_finished,
    ui_frame,
    tool_started,
)
from app.state.models import SessionState


@dataclass(frozen=True)
class ScriptedStep:
    """One tool call, optionally with something for the agent to say around it.

    `derive_arguments` exists because a script cannot know every argument in
    advance: shortlisting requires the listing ids the search just returned.
    It receives the previous tool's result and returns arguments to merge
    over `arguments`.
    """

    tool: str
    arguments: dict[str, Any] = field(default_factory=dict)
    derive_arguments: Callable[[dict[str, Any]], dict[str, Any]] | None = None
    say_before: str | None = None
    say_after: str | None = None

    def resolve(self, previous: dict[str, Any] | None) -> dict[str, Any]:
        if self.derive_arguments is None or previous is None:
            return dict(self.arguments)
        return {**self.arguments, **self.derive_arguments(previous)}


class ScriptedRunner:
    """Runs a fixed sequence of tool calls, emitting real events throughout."""

    def __init__(
        self,
        session: Session,
        steps: Sequence[ScriptedStep],
        delay: float = 0.0,
    ) -> None:
        self._session = session
        self._steps = list(steps)
        self._delay = delay

    async def run_turn(
        self, state: SessionState, user_message: str
    ) -> AsyncIterator[AgentEvent]:
        state.record_turn("user", user_message)
        yield state_event(state)

        yield a2ui_message(a2ui.delete_surface(a2ui.CONSTRAINTS_SURFACE), "panel")
        yield a2ui_message(a2ui.constraints_surface(state), "panel")

        previous: dict[str, Any] | None = None

        for index, step in enumerate(self._steps):
            if step.say_before:
                yield message(step.say_before)

            arguments = step.resolve(previous)

            yield tool_started(step.tool, arguments)
            if self._delay:
                await asyncio.sleep(self._delay)

            if step.tool in UI_TOOLS:
                result, frame = await _call_ui_tool(step.tool, arguments)
                if frame:
                    yield ui_frame(frame, surface="inline")
            else:
                result = tools.call(self._session, state, step.tool, arguments)
            previous = result
            summary = str(result.get("summary", ""))
            yield tool_finished(step.tool, summary, result)

            # Tools that change phase or narrow candidates carry information
            # the UI needs beyond the tool result itself.
            if step.tool == "advance_phase":
                yield phase_event(
                    phase=state.phase.value,
                    allowed=bool(result.get("allowed")),
                    message=summary,
                    missing=list(result.get("missing", [])),
                )
            if step.tool == "search_listings" and not result.get("empty"):
                yield progress(
                    "Narrowing candidates",
                    remaining=int(result.get("total_matched", 0)),
                )

            for envelope in _surfaces_for(step.tool, result, state, index):
                yield a2ui_message(envelope, "inline")

            yield a2ui_message(a2ui.constraints_update(state), "panel")
            yield state_event(state)

            if step.say_after:
                yield message(step.say_after)

        state.record_turn("assistant", "(scripted turn complete)")
        yield done_event(state)


# --------------------------------------------------------------------------
# Argument derivations
# --------------------------------------------------------------------------


def _shortlist_from_search(previous: dict[str, Any]) -> dict[str, Any]:
    """Take up to five listing ids from the preceding search result."""
    listings = previous.get("listings") or []
    return {"listing_ids": [row["id"] for row in listings[:5]]}


def _book_first_ranked(previous: dict[str, Any]) -> dict[str, Any]:
    """Open the booking form for whichever listing ranked first."""
    rankings = previous.get("rankings") or []
    listing_id = rankings[0]["listing_id"] if rankings else "lst-0001"
    return {"listing_id": listing_id, "mode": "rent"}


# --------------------------------------------------------------------------
# Scripts
# --------------------------------------------------------------------------

#: A full happy-path rental journey through to ranked recommendations.
#: Used by the API smoke test and as the default fixture for
#: transport-level evals.
DEMO_RENTAL_SCRIPT: tuple[ScriptedStep, ...] = (
    ScriptedStep(
        tool="update_slots",
        arguments={
            "mode": "rent",
            "use_case": "weekend trip with family",
            "category": "mpv",
            "budget_max": 4000,
            "target_date": "2026-09-12",
            "seats_min": 7,
        },
        say_before="Let me note what you've told me.",
    ),
    ScriptedStep(
        tool="advance_phase",
        arguments={"target": "research"},
        say_before="That's everything I need — searching now.",
    ),
    ScriptedStep(tool="search_listings", arguments={"limit": 6}),
    ScriptedStep(
        tool="set_shortlist",
        derive_arguments=_shortlist_from_search,
        say_before="Narrowing to the strongest candidates.",
    ),
    ScriptedStep(tool="advance_phase", arguments={"target": "recommend"}),
    ScriptedStep(
        tool="rank_shortlist",
        arguments={"emphasis": {"budget": 0.1, "seats": 0.08}},
        say_before="Ranking these against your priorities.",
    ),
)


#: Scenario C: the user changes their mind about buying versus renting after
#: the interview is already complete. Proves constraints survive correctly
#: and that stale results are discarded.
DEMO_MODE_CHANGE_SCRIPT: tuple[ScriptedStep, ...] = (
    ScriptedStep(
        tool="update_slots",
        arguments={
            "mode": "buy",
            "use_case": "daily commute",
            "category": "compact_suv",
            "budget_max": 1_500_000,
            "target_date": "2026-10-01",
            "seats_min": 5,
        },
        say_before="Noting that down.",
    ),
    ScriptedStep(
        tool="change_mode",
        arguments={"mode": "rent"},
        say_before="You've said you only need it for six weeks — switching to rentals.",
    ),
    ScriptedStep(
        tool="update_slots",
        arguments={"budget_max": 3000, "target_date": "2026-10-01"},
        say_before="I'll need a daily budget instead of a purchase price.",
    ),
    ScriptedStep(tool="advance_phase", arguments={"target": "research"}),
    ScriptedStep(tool="search_listings", arguments={"limit": 6}),
)


#: Scenario E: constraints that match nothing, so the agent must name the
#: binding constraint rather than returning poor matches silently.
DEMO_EMPTY_SCRIPT: tuple[ScriptedStep, ...] = (
    ScriptedStep(
        tool="update_slots",
        arguments={
            "mode": "buy",
            "use_case": "weekend car",
            "category": "luxury_suv",
            "budget_max": 700_000,
            "target_date": "2026-10-01",
        },
        say_before="Let me see what that gets us.",
    ),
    ScriptedStep(tool="session_status"),
)




#: Straight to the booking form with no model involved. Exists so the MCP
#: Apps path can be exercised without spending model quota — the tool calls,
#: the ui event and the View are identical either way.
DEMO_BOOKING_SCRIPT: tuple[ScriptedStep, ...] = DEMO_RENTAL_SCRIPT + (
    ScriptedStep(
        tool="advance_phase",
        arguments={"target": "book"},
        say_before="Opening the booking form.",
    ),
    ScriptedStep(
        tool="open_booking_form",
        derive_arguments=_book_first_ranked,
    ),
)


SCRIPTS: dict[str, tuple[ScriptedStep, ...]] = {
    "rental": DEMO_RENTAL_SCRIPT,
    "mode_change": DEMO_MODE_CHANGE_SCRIPT,
    "empty": DEMO_EMPTY_SCRIPT,
    "booking": DEMO_BOOKING_SCRIPT,
}
