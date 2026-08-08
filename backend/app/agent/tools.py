"""Tool registry — the bridge between the state machine and the agent SDK.

Serves T022 and T030, and makes T021's tool scoping operational.

WHY A REGISTRY RATHER THAN SDK DECORATORS
-----------------------------------------
Every tool here is a plain function over an explicit `SessionState` and
`Session`. The SDK adapter reads this registry and advertises only the tools
`phases.available_tools()` permits for the current phase.

Two consequences:

1. Tool scoping becomes structural. The model is not told "do not search
   yet" — search is simply not in the tool list until the interview
   completes. A rule the model cannot break beats a rule it is asked to obey.
2. Every tool is testable without an API key, a network call, or an SDK
   import, which is what the T045 eval suite depends on.

Search tools that read inventory are exposed to the agent through the
marketplace MCP server, not from here; this registry covers the tools that
read or write session state.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.agent import interview, ranking, tco
from app.agent.constraints import describe_empty_result, to_filter
from app.agent.phases import Decision, advance, available_tools, phase_status
from app.models.listing import FuelType, Mode, Transmission
from app.repositories.listing_repository import ListingRepository
from app.state.models import Phase, SessionState


@dataclass(frozen=True)
class ToolSpec:
    """One agent-callable operation.

    `schema` is JSON Schema for the arguments, so the SDK adapter can
    advertise the tool without a second source of truth about its shape.
    """

    name: str
    description: str
    schema: dict[str, Any]
    handler: Callable[..., Any]


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------


def _update_slots(session: Session, state: SessionState, **kwargs: Any) -> dict:
    return interview.update_slots(session, state, **kwargs).model_dump()


def _revise_constraints(
    session: Session, state: SessionState, clear: list[str] | None = None, **kwargs: Any
) -> dict:
    return interview.revise_constraints(
        session, state, clear=clear, **kwargs
    ).model_dump()


def _change_mode(session: Session, state: SessionState, mode: Mode) -> dict:
    return interview.change_mode(session, state, mode).model_dump()


def _flag_conflict(
    session: Session,
    state: SessionState,
    kind: str,
    fields: list[str],
    description: str,
    relaxations: list[str] | None = None,
) -> dict:
    return interview.flag_conflict(
        state, kind, fields, description, relaxations
    ).model_dump()


def _resolve_conflict(
    session: Session, state: SessionState, kind: str | None = None
) -> dict:
    return interview.resolve_conflict(session, state, kind).model_dump()


def _run_search(session: Session, state: SessionState, limit: int = 10) -> dict:
    """Search using the constraints already gathered.

    Deliberately takes no filter arguments. The constraint set is the single
    source of truth about what the user wants; letting the agent pass ad-hoc
    filters here would let it search for something the user never asked for
    and would leave no record in state of why those results appeared.
    """
    repo = ListingRepository(session)
    page = repo.search(to_filter(state.constraints, limit=limit))

    if page.total_matched == 0:
        return {
            "summary": describe_empty_result(session, state.constraints),
            "total_matched": 0,
            "listings": [],
            "empty": True,
        }

    return {
        "summary": (
            f"{page.total_matched} listings match the current constraints; "
            f"returning {len(page.items)}."
        ),
        "total_matched": page.total_matched,
        "listings": [x.model_dump(mode="json") for x in page.items],
        "empty": False,
    }


def _set_shortlist(
    session: Session, state: SessionState, listing_ids: list[str]
) -> dict:
    """Narrow candidates to the set worth ranking (FR-011)."""
    if len(listing_ids) > 10:
        return {
            "summary": (
                f"{len(listing_ids)} is too many — narrow to at most 10 "
                "before ranking."
            ),
            "accepted": False,
            "shortlist": state.shortlist,
        }

    found = ListingRepository(session).get_many(listing_ids)
    known = [x.id for x in found]
    unknown = [x for x in listing_ids if x not in known]

    state.shortlist = known
    state.reasoning_log = []
    state.touch()

    summary = f"Shortlisted {len(known)} listings."
    if unknown:
        summary += f" Not found and dropped: {', '.join(unknown)}."

    return {
        "summary": summary,
        "accepted": True,
        "shortlist": known,
        "dropped": unknown,
    }


def _rank_shortlist(
    session: Session, state: SessionState, emphasis: dict[str, float] | None = None
) -> dict:
    records = ranking.rank_shortlist(session, state, emphasis)
    if not records:
        return {"summary": "Nothing shortlisted to rank.", "rankings": []}

    repo = ListingRepository(session)
    explanations = [
        ranking.explain(record, repo.get(record.listing_id)) for record in records
    ]

    return {
        "summary": ranking.weight_summary(state) + " " + explanations[0],
        "weight_source": state.weight_source.value,
        "weights": state.inferred_weights,
        "rankings": [record.model_dump(mode="json") for record in records],
        "explanations": explanations,
    }


def _compute_tco(
    session: Session, state: SessionState, listing_id: str, days: int
) -> dict:
    return tco.compute_tco(session, listing_id, days).model_dump(mode="json")


def _advance_phase(session: Session, state: SessionState, target: str) -> dict:
    """Propose a transition. The guard decides (Constitution III)."""
    try:
        phase = Phase(target)
    except ValueError:
        return {
            "summary": f"'{target}' is not a phase.",
            "allowed": False,
            "phase": state.phase.value,
        }

    decision: Decision = advance(state, phase)
    return {
        "summary": decision.message,
        "allowed": decision.allowed,
        "missing": list(decision.missing),
        "phase": state.phase.value,
        "available_tools": list(available_tools(state)),
    }


def _session_status(session: Session, state: SessionState) -> dict:
    status = phase_status(state)
    status["known"] = state.panel()["known"]
    status["missing"] = state.constraints.missing_required()
    return status


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------

_SLOT_PROPERTIES = {
    "use_case": {"type": "string", "description": "What the car is for"},
    "category": {"type": "string", "description": "Vehicle type, e.g. compact_suv"},
    "budget_max": {
        "type": "integer",
        "description": "Ceiling in rupees — total price when buying, per day when renting",
    },
    "budget_min": {"type": "integer"},
    "target_date": {"type": "string", "format": "date"},
    "duration_days": {"type": "integer"},
    "seats_min": {"type": "integer"},
    "fuel": {
        "type": "array",
        "items": {"type": "string", "enum": [f.value for f in FuelType]},
    },
    "transmission": {
        "type": "string",
        "enum": [t.value for t in Transmission],
    },
    "brand_affinity": {"type": "array", "items": {"type": "string"}},
    "year_min": {"type": "integer"},
    "km_max": {"type": "integer"},
    "city": {"type": "string"},
    "country": {"type": "string"},
}


def _object(properties: dict, required: list[str] | None = None) -> dict:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


# --------------------------------------------------------------------------
# Registry
# --------------------------------------------------------------------------

REGISTRY: dict[str, ToolSpec] = {
    "update_slots": ToolSpec(
        name="update_slots",
        description=(
            "Record what the user just told you about their needs. Pass only "
            "what you learned this turn — omitted fields are left unchanged, "
            "so you never need to restate the whole set. To change buy/rent, "
            "use change_mode instead."
        ),
        schema=_object(
            {
                "mode": {"type": "string", "enum": [m.value for m in Mode]},
                **_SLOT_PROPERTIES,
            }
        ),
        handler=_update_slots,
    ),
    "revise_constraints": ToolSpec(
        name="revise_constraints",
        description=(
            "Change or remove constraints after the interview has moved on. "
            "Use `clear` to forget a requirement entirely. Available in every "
            "phase — the user may reconsider at any point."
        ),
        schema=_object(
            {
                "clear": {"type": "array", "items": {"type": "string"}},
                **_SLOT_PROPERTIES,
            }
        ),
        handler=_revise_constraints,
    ),
    "change_mode": ToolSpec(
        name="change_mode",
        description=(
            "Switch between buying and renting. Constraints that mean "
            "different things under each mode — budget, dates — are dropped "
            "and returned so you can re-ask for them."
        ),
        schema=_object(
            {"mode": {"type": "string", "enum": [m.value for m in Mode]}},
            required=["mode"],
        ),
        handler=_change_mode,
    ),
    "flag_conflict": ToolSpec(
        name="flag_conflict",
        description=(
            "Record a conflict you noticed that a catalogue query would not "
            "detect — for example a two-seater for a family of five. "
            "Conflicts arising from inventory are found automatically."
        ),
        schema=_object(
            {
                "kind": {"type": "string"},
                "fields": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
                "relaxations": {"type": "array", "items": {"type": "string"}},
            },
            required=["kind", "fields", "description"],
        ),
        handler=_flag_conflict,
    ),
    "resolve_conflict": ToolSpec(
        name="resolve_conflict",
        description=(
            "Mark a conflict settled after the user chose how to relax it. "
            "Re-checked against inventory — if nothing matches yet, the "
            "conflict stays open."
        ),
        schema=_object({"kind": {"type": "string"}}),
        handler=_resolve_conflict,
    ),
    "search_listings": ToolSpec(
        name="search_listings",
        description=(
            "Search inventory using the constraints gathered so far. Takes no "
            "filters: the constraint set is what the user asked for. If "
            "nothing matches, the result names the binding constraint and "
            "suggests a specific relaxation."
        ),
        schema=_object(
            {"limit": {"type": "integer", "minimum": 1, "maximum": 50}}
        ),
        handler=_run_search,
    ),
    "set_shortlist": ToolSpec(
        name="set_shortlist",
        description=(
            "Narrow the candidates to at most ten listings worth ranking."
        ),
        schema=_object(
            {"listing_ids": {"type": "array", "items": {"type": "string"}}},
            required=["listing_ids"],
        ),
        handler=_set_shortlist,
    ),
    "rank_shortlist": ToolSpec(
        name="rank_shortlist",
        description=(
            "Rank the shortlist and record why each listing placed where it "
            "did. Optionally pass `emphasis` to shift criterion weights based "
            "on how the user described their priorities — values are clamped "
            "to +/-0.15 each. Criteria: budget, recency, category, condition, "
            "seats, fuel, transmission, brand, availability, location."
        ),
        schema=_object(
            {
                "emphasis": {
                    "type": "object",
                    "additionalProperties": {"type": "number"},
                }
            }
        ),
        handler=_rank_shortlist,
    ),
    "compute_tco": ToolSpec(
        name="compute_tco",
        description=(
            "Compare the total cost of buying versus renting a listing over a "
            "given number of days, including the crossover point at which "
            "buying becomes cheaper. Use when the user is undecided about "
            "mode or has a fixed-duration need."
        ),
        schema=_object(
            {
                "listing_id": {"type": "string"},
                "days": {"type": "integer", "minimum": 1},
            },
            required=["listing_id", "days"],
        ),
        handler=_compute_tco,
    ),
    "advance_phase": ToolSpec(
        name="advance_phase",
        description=(
            "Propose moving to another phase: interview, research, recommend, "
            "book, complete. The move is authorised only if its conditions "
            "hold; if refused, the result names what is missing."
        ),
        schema=_object(
            {
                "target": {
                    "type": "string",
                    "enum": [p.value for p in Phase],
                }
            },
            required=["target"],
        ),
        handler=_advance_phase,
    ),
    "session_status": ToolSpec(
        name="session_status",
        description=(
            "Report the current phase, what is known, what is missing, and "
            "what is blocking progress."
        ),
        schema=_object({}),
        handler=_session_status,
    ),
}

#: Callable in every phase, since orientation is never out of place.
ALWAYS_AVAILABLE = ("session_status", "change_mode")


def tools_for(state: SessionState) -> list[ToolSpec]:
    """Tool specs the model may be offered right now (T021)."""
    permitted = set(available_tools(state)) | set(ALWAYS_AVAILABLE)
    return [spec for name, spec in REGISTRY.items() if name in permitted]


def call(
    session: Session, state: SessionState, name: str, arguments: dict[str, Any]
) -> dict:
    """Invoke a tool, refusing anything outside the current phase.

    The refusal is returned rather than raised so the model reads it as a
    tool result and self-corrects.
    """
    spec = REGISTRY.get(name)
    if spec is None:
        return {"summary": f"No tool named {name}.", "error": "unknown_tool"}

    permitted = set(available_tools(state)) | set(ALWAYS_AVAILABLE)
    if name not in permitted:
        return {
            "summary": (
                f"{name} is not available during the {state.phase.value} "
                f"phase. Available now: {', '.join(sorted(permitted))}."
            ),
            "error": "tool_not_in_phase",
            "phase": state.phase.value,
        }

    return spec.handler(session, state, **arguments)
