"""Model-backed agent runner.

Serves T022. Implements the `AgentRunner` protocol, so it is a drop-in
replacement for `ScriptedRunner` — nothing downstream of the event stream
changes.

HOW ORCHESTRATION IS ENFORCED
-----------------------------
The model decides *what to do next*. It does not decide what it is allowed
to do. Three mechanisms, in order of strength:

1. Only the current phase's tools are advertised. The model cannot search
   during the interview because search is not in the list it receives.
2. `tools.call()` refuses anything out of phase even if the model asks for
   it anyway.
3. Phase transitions are authorised by `phases.py` against state, never by
   the model's assertion that it is ready.

When a call is refused, the refusal is returned as the tool result. The
model reads "still missing: budget_max" and asks the user for it. Refusal is
a correction, not a dead end.

THE PROMPT IS REBUILT EACH TURN
-------------------------------
The system prompt is generated from live state — current phase, known
constraints, what is missing, the exact tool list. A model that can see the
state does not have to remember it, which matters much more on small,
fast models than on frontier ones.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.agent import tools as tool_registry
from app.agent.model_client import ModelClient, RateLimited
from app.api.mcp_bridge import RESOURCE_OWNERS, SERVERS
from app.agent.phases import (
    TURN_CAPS,
    advance,
    available_tools,
    turn_cap_reached,
)
from app.a2ui import surfaces as a2ui
from app.api.events import (
    AgentEvent,
    a2ui_message,
    ui_frame,
    done_event,
    error_event,
    message,
    phase_event,
    progress,
    state_event,
    tool_finished,
    tool_started,
)
from app.inventory import taxonomy
from app.state.models import Phase, SessionState, ToolCallRecord

MAX_HISTORY_TURNS = 12

PHASE_GUIDANCE = {
    Phase.INTERVIEW: (
        "You are gathering requirements. Ask about ONE missing thing at a "
        "time, conversationally — never present a list of questions. Record "
        "everything the user tells you with update_slots as soon as they say "
        "it, including things they volunteer out of order. Do not search: "
        "you have no search tool yet, and you will get it once the required "
        "details are known. The moment nothing is listed as STILL REQUIRED, "
        "call advance_phase to move to research in that same turn — do not "
        "ask about optional details like city, fuel or brand first. You can "
        "refine after showing real options, and seeing results is more "
        "useful to the user than another question."
    ),
    Phase.RESEARCH: (
        "You have what you need. Search, then narrow the results to at most "
        "ten candidates with set_shortlist, then call advance_phase to reach "
        "recommend. Do NOT describe the listings yourself while still in "
        "research — an unranked list has no reasoning attached to it, and "
        "every recommendation you show must be explained. If nothing "
        "matches, the result tells you which constraint is binding — relay "
        "that with the specific relaxation suggested, and do not silently "
        "widen the search yourself."
    ),
    Phase.RECOMMEND: (
        "Rank the shortlist. ALWAYS pass `emphasis` to rank_shortlist, "
        "derived from how the user described their needs — not from what you "
        "think matters generally. A stated ceiling they seemed anxious about "
        "raises budget; 'doesn't matter how old' lowers recency; a trip with "
        "a fixed party size raises seats; a named city raises location. Use "
        "values between -0.15 and 0.15. If they truly expressed no "
        "priorities at all, pass an empty object. Present the "
        "top few. The interface already shows each car's name, price, specs, "
        "matched criteria and trade-offs as cards — do NOT list those again "
        "in prose. Say only what the cards cannot: which one you would pick "
        "and why, or what distinguishes them from each other. Two or three "
        "sentences. If the user is undecided between buying and renting, use "
        "compute_tco."
    ),
    Phase.BOOK: (
        "The user has chosen. Open the booking form with everything already "
        "known so they are not retyping it — then STOP and wait. Do not open "
        "checkout in the same turn: there is no booking to pay for until the "
        "user has submitted the form, and the form will tell you its "
        "reference when they do. When it does, record it with record_booking, "
        "then open checkout. State plainly that payment is simulated."
    ),
    Phase.COMPLETE: "The booking is confirmed. Summarise and offer further help.",
}


def _system_prompt(state: SessionState, model_name: str) -> str:
    known = state.constraints.filled()
    missing = state.constraints.missing_required()
    conflicts = [c.description for c in state.open_conflicts]

    today = date.today()
    lines = [
        "You are a car matchmaking assistant. You help people find a car to "
        "buy or rent by interviewing them, searching real inventory, and "
        "explaining your recommendations.",
        "",
        f"TODAY IS {today.isoformat()} ({today.strftime('%A %d %B %Y')}). "
        "Resolve every relative date the user gives — 'next month', 'the "
        "12th', 'in two weeks' — against this date, and always pass dates as "
        "YYYY-MM-DD. Never assume a different year.",
        "",
        "RULES",
        "- Never invent a listing, a price, or availability. Everything comes "
        "from tool results.",
        "- Call tools as soon as you learn something. Do not batch updates "
        "until the end of a conversation.",
        "- Keep replies short and natural. One question at a time.",
        "- Do not narrate what you are about to do. Chain the tool calls you "
        "need and speak once at the end, when you have something for the "
        "user. Saying 'let me search now' before searching wastes a step and "
        "tells them nothing.",
        "- If a tool refuses, read why and act on it — usually by asking the "
        "user for what is missing.",
        "- Never tell the user you have opened, searched, booked or recorded "
        "something unless a tool call in THIS turn returned successfully "
        "saying so. Being in a later phase does not mean the work was done — "
        "it may have happened in an earlier conversation the user cannot "
        "see. If you are unsure whether something is already open, do it "
        "rather than claim it.",
        "",
        f"CURRENT PHASE: {state.phase.value}",
        PHASE_GUIDANCE[state.phase],
        "",
        f"KNOWN SO FAR: {json.dumps(known, default=str) if known else 'nothing yet'}",
        f"STILL REQUIRED: {', '.join(missing) if missing else 'nothing — you may advance'}",
    ]

    if conflicts:
        lines += ["", "UNRESOLVED CONFLICTS: " + "; ".join(conflicts)]

    if state.shortlist:
        lines.append(f"SHORTLIST: {len(state.shortlist)} listings")

    # Naming the vocabulary prevents the model guessing at category strings —
    # it will happily emit "MPV" or "SUV" when the catalogue expects "mpv".
    lines += [
        "",
        "VALID CATEGORIES (use these exact strings): "
        + ", ".join(sorted(taxonomy.CATALOGUE))
        + ". Never read this list to the user — suggest the two or three "
        "that suit what they have described and let them choose.",
        "",
        f"TOOLS AVAILABLE NOW: {', '.join(available_tools(state))}. "
        "Tools from other phases are not callable yet.",
    ]
    return "\n".join(lines)


def _tool_schemas(state: SessionState) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.schema,
            },
        }
        for spec in tool_registry.tools_for(state)
    ]


def _history(state: SessionState) -> list[dict[str, str]]:
    """Recent conversation only.

    The full transcript is preserved in state for replay; sending all of it
    every turn would waste tokens without improving behaviour, since the
    system prompt already carries the accumulated facts.
    """
    recent = state.history[-MAX_HISTORY_TURNS:]
    return [
        {"role": "assistant" if t.role == "assistant" else "user", "content": t.content}
        for t in recent
        if t.content and not t.content.startswith("(")
    ]


def _normalise(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Repair the argument shapes models commonly get slightly wrong."""
    fixed = dict(arguments)

    # Models emit "MPV" or "Compact SUV" where the catalogue expects "mpv".
    category = fixed.get("category")
    if isinstance(category, str):
        candidate = category.strip().lower().replace(" ", "_").replace("-", "_")
        if candidate in taxonomy.CATALOGUE:
            fixed["category"] = candidate
        else:
            match = next(
                (c for c in taxonomy.CATALOGUE if c.replace("_", "") == candidate.replace("_", "")),
                None,
            )
            if match:
                fixed["category"] = match

    for key in ("mode", "transmission"):
        if isinstance(fixed.get(key), str):
            fixed[key] = fixed[key].strip().lower()

    if isinstance(fixed.get("fuel"), str):
        fixed["fuel"] = [fixed["fuel"].strip().lower()]
    elif isinstance(fixed.get("fuel"), list):
        fixed["fuel"] = [str(f).strip().lower() for f in fixed["fuel"]]

    if isinstance(fixed.get("brand_affinity"), str):
        fixed["brand_affinity"] = [fixed["brand_affinity"]]

    return fixed


def _auto_advance(state: SessionState) -> tuple[str, Phase] | None:
    """Advance if the guard permits, without asking the model.

    Only ever moves forward one step, and only when `phases.advance` agrees.
    Every constraint in phases.py still applies — this changes who proposes
    the transition, not who authorises it.
    """
    nexts = {
        Phase.INTERVIEW: Phase.RESEARCH,
        Phase.RESEARCH: Phase.RECOMMEND,
    }
    target = nexts.get(state.phase)
    if target is None:
        return None

    decision = advance(state, target)
    return (decision.message, target) if decision.allowed else None


#: Tools whose result is a user interface rather than data. They need the
#: async MCP client, so the runner handles them instead of the synchronous
#: tool registry.
UI_TOOLS = {
    "open_booking_form": ("booking-form", "ui://booking/form"),
    "open_checkout": ("checkout", "ui://checkout/payment"),
    # Called directly by the checkout demo script so both MCP Apps can be
    # exercised without a model.
    "submit_booking": ("booking-form", ""),
}


async def _call_ui_tool(
    name: str, arguments: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Invoke an MCP App tool and shape the frame the client will render.

    Returns (tool result for the model, ui frame for the client). The model
    sees the summary so it can talk about what just opened; the client gets
    what it needs to mount a sandboxed View.
    """
    from mcp.client import Client

    server_name, uri = UI_TOOLS[name]
    server = SERVERS[server_name]

    async with Client(server) as client:
        result = await client.call_tool(name, arguments)

    structured = (
        getattr(result, "structured_content", None)
        or getattr(result, "structuredContent", None)
        or {}
    )
    summary = str(structured.get("summary", "")) or "Opened."

    frame = {
        "uri": uri,
        "server": server_name,
        "toolName": name,
        "toolInput": arguments,
        "toolResult": {"structuredContent": structured},
    }

    # An error result means no View should be shown — the frame is dropped
    # and the model gets the reason instead.
    if structured.get("error"):
        return {"summary": summary, "error": structured["error"]}, {}

    # Tools without a UI resource are relayed for their result alone —
    # submit_booking creates a booking whose id the next step needs, and
    # reshaping it to {summary, opened} would throw that away.
    if not uri:
        return {**structured, "summary": summary}, {}

    return {"summary": summary, "opened": True}, frame


#: Tool results that produce a visible surface, and the builder for each.
SURFACE_BUILDERS = ("search_listings", "rank_shortlist", "compute_tco")


PHASE_LABELS = [
    (Phase.INTERVIEW, "Understanding what you need"),
    (Phase.RESEARCH, "Searching listings"),
    (Phase.RECOMMEND, "Ranking against your priorities"),
    (Phase.BOOK, "Booking"),
]


def _progress_steps(state: SessionState, activity: str | None = None) -> list[dict]:
    """Live agent progress as A2UI data.

    Sent as updateDataModel against a surface whose structure was created
    once, so the timeline animates without resending its components.
    """
    order = [p for p, _ in PHASE_LABELS]
    current = order.index(state.phase) if state.phase in order else len(order)

    steps = []
    for index, (phase, label) in enumerate(PHASE_LABELS):
        status = "done" if index < current else "active" if index == current else "pending"
        text = label
        if status == "active" and activity:
            text = f"{label} — {activity}"
        steps.append({"label": text, "status": status})
    return steps


def _surfaces_for(
    name: str, result: dict[str, Any], state: SessionState, turn: int
) -> list[dict[str, Any]]:
    """Build the A2UI envelopes a tool result implies.

    The agent decides what to show by calling a tool; this decides how to
    describe it. Nothing here renders anything — the client owns that, which
    is the separation the protocol exists to enforce.
    """
    from app.models.listing import ListingRead, Mode
    from app.state.models import ReasoningRecord

    if name == "search_listings":
        if result.get("empty"):
            return [
                a2ui.conflict_surface(
                    f"empty_{turn}",
                    str(result.get("summary", "Nothing matched.")),
                    [],
                )
            ]
        listings = [
            ListingRead.model_validate(row) for row in result.get("listings", [])
        ]
        if not listings:
            return []
        return [
            a2ui.listings_surface(
                f"results_{turn}",
                listings,
                int(result.get("total_matched", len(listings))),
                state.constraints.mode,
            )
        ]

    if name == "rank_shortlist":
        records = [
            ReasoningRecord.model_validate(row)
            for row in result.get("rankings", [])
        ]
        listings = {
            row["id"]: ListingRead.model_validate(row)
            for row in result.get("listings", [])
        }
        if not records or not listings:
            return []
        return [
            a2ui.rankings_surface(
                f"ranked_{turn}",
                records,
                listings,
                str(result.get("weight_source", "fallback")),
            )
        ]

    if name == "compute_tco" and result.get("duration_days"):
        return [a2ui.tco_surface(f"tco_{turn}", result)]

    return []


def _echo_tool_call(call: Any) -> dict[str, Any]:
    """Rebuild a tool call for the next request, preserving provider extras.

    Gemini 3 signs its reasoning and attaches the signature to each tool call
    at `extra_content.google.thought_signature`. It is a non-standard field,
    so a naive reconstruction from id/name/arguments drops it — and the next
    request is rejected with a 400 saying the signature is missing.

    Carrying `extra_content` through verbatim fixes it without special-casing
    any provider: anything a provider attaches comes back untouched.
    """
    echoed: dict[str, Any] = {
        "id": call.id,
        "type": "function",
        "function": {
            "name": call.function.name,
            "arguments": call.function.arguments,
        },
    }

    extra = getattr(call, "extra_content", None)
    if extra is None:
        # Unknown fields land in model_extra when the SDK parses a response
        # containing keys it does not know about.
        extra = (getattr(call, "model_extra", None) or {}).get("extra_content")
    if extra:
        echoed["extra_content"] = extra

    return echoed


class ModelRunner:
    """Drives the conversation with a real model."""

    def __init__(self, session: Session, client: ModelClient | None = None) -> None:
        self._session = session
        self._client = client or ModelClient()

    async def run_turn(
        self, state: SessionState, user_message: str
    ) -> AsyncIterator[AgentEvent]:
        state.record_turn("user", user_message)
        yield state_event(state)

        # The panel's structure is sent once; every later change to it in
        # this turn travels as data alone. That split is the reason A2UI
        # separates components from the data model, and the panel is where
        # it earns its keep.
        yield a2ui_message(a2ui.delete_surface(a2ui.CONSTRAINTS_SURFACE), "panel")
        yield a2ui_message(a2ui.constraints_surface(state), "panel")
        yield a2ui_message(a2ui.progress_surface(), "progress")
        yield a2ui_message(
            a2ui.progress_update(_progress_steps(state, "starting")), "progress"
        )

        if turn_cap_reached(state):
            yield message(
                "We seem to be going in circles on this step. Could you tell "
                "me directly what you'd like to do next?"
            )
            yield done_event(state)
            return

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": _system_prompt(state, self._client.describe())},
            *_history(state),
        ]

        tool_records: list[ToolCallRecord] = []

        for round_index in range(self._client.config.max_rounds):
            # Regenerated each round: a tool may have changed phase, which
            # changes both the guidance and the callable tool set.
            messages[0] = {
                "role": "system",
                "content": _system_prompt(state, self._client.describe()),
            }

            try:
                reply = await self._client.complete(messages, _tool_schemas(state))
            except RateLimited as exc:
                yield error_event(str(exc), recoverable=True)
                yield done_event(state)
                return
            except Exception as exc:  # noqa: BLE001 - surfaced to the user
                yield error_event(
                    f"The model call failed: {exc}", recoverable=True
                )
                yield done_event(state)
                return

            text = (reply.content or "").strip()
            calls = getattr(reply, "tool_calls", None) or []

            if text:
                yield message(text)

            if not calls:
                if text:
                    state.record_turn("assistant", text, tool_records)
                yield done_event(state)
                return

            messages.append(
                {
                    "role": "assistant",
                    "content": reply.content,
                    "tool_calls": [_echo_tool_call(call) for call in calls],
                }
            )

            for call in calls:
                name = call.function.name
                try:
                    raw = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    raw = {}
                arguments = _normalise(name, raw)

                yield tool_started(name, arguments)
                yield a2ui_message(
                    a2ui.progress_update(
                        _progress_steps(state, name.replace("_", " "))
                    ),
                    "progress",
                )

                if name in UI_TOOLS:
                    result, frame = await _call_ui_tool(name, arguments)
                    if frame:
                        yield ui_frame(frame, surface="inline")
                else:
                    result = tool_registry.call(
                        self._session, state, name, arguments
                    )
                summary = str(result.get("summary", ""))
                tool_records.append(
                    ToolCallRecord(tool=name, arguments=arguments, summary=summary)
                )

                yield tool_finished(name, summary, result)

                # A refusal that only says "already there" is an artefact of
                # auto-advance beating the model to it, not a real block.
                # Surfacing it would show a red line for something that went
                # right.
                if name == "advance_phase" and not summary.startswith("Already in"):
                    yield phase_event(
                        phase=state.phase.value,
                        allowed=bool(result.get("allowed")),
                        message=summary,
                        missing=list(result.get("missing", [])),
                    )
                if name == "search_listings" and not result.get("empty"):
                    yield progress(
                        "Narrowing candidates",
                        remaining=int(result.get("total_matched", 0)),
                    )

                for envelope in _surfaces_for(name, result, state, round_index):
                    yield a2ui_message(envelope, "inline")

                yield a2ui_message(a2ui.constraints_update(state), "panel")
                yield a2ui_message(
                    a2ui.progress_update(
                        _progress_steps(state),
                        int(result.get("total_matched", 0)) or None,
                    ),
                    "progress",
                )
                yield state_event(state)

                # Auto-advance when the guard already permits it. The state
                # machine knows the interview is complete; spending a model
                # round asking it to notice wastes quota and it sometimes
                # keeps interviewing anyway. The guard still authorises the
                # move — this only removes the need for the model to
                # propose it.
                if name in ("update_slots", "set_shortlist", "rank_shortlist"):
                    auto = _auto_advance(state)
                    if auto is not None:
                        decision, target = auto
                        yield phase_event(
                            phase=state.phase.value,
                            allowed=True,
                            message=decision,
                        )
                        yield state_event(state)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, default=str)[:6000],
                    }
                )

        # Rounds exhausted. Ending cleanly beats looping until the quota is
        # spent, and the user gets a turn back rather than silence.
        yield message(
            "I've done as much as I can in one go — tell me how you'd like "
            "to proceed."
        )
        state.record_turn("assistant", "(round limit reached)", tool_records)
        yield done_event(state)
