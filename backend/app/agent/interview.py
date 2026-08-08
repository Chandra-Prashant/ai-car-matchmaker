"""Interview tools — the operations the model performs on session state.

Serves T023 (out-of-order slot capture), T024 (conflict detection) and T025
(mid-flow mode change).

These are plain functions taking an explicit `SessionState`, not decorated
MCP tools. The adapter in `orchestrator.py` exposes them to the agent SDK.
Keeping them SDK-free means every one is unit-testable without an API key,
same reasoning as `phases.py`.

Each returns a result carrying a `summary` written for the model to read
aloud or act on. The model should never have to invent a description of what
just happened to the state.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.agent.constraints import analyse, detect_conflict
from app.models.listing import FuelType, Mode, Transmission
from app.state.models import ConstraintSet, SessionState

# Slots the model may set. Anything outside this is rejected rather than
# silently ignored, so a hallucinated slot name surfaces immediately.
SETTABLE = frozenset(
    {
        "mode", "use_case", "category", "budget_max", "budget_min",
        "target_date", "duration_days", "seats_min", "fuel", "transmission",
        "brand_affinity", "year_min", "km_max", "city", "country",
    }
)


class SlotUpdateResult(BaseModel):
    summary: str
    updated: list[str] = Field(default_factory=list)
    rejected: list[str] = Field(default_factory=list)
    known: dict = Field(default_factory=dict)
    still_missing: list[str] = Field(default_factory=list)
    conflict: str | None = None
    ready_to_search: bool = False


class ModeChangeResult(BaseModel):
    summary: str
    new_mode: Mode
    dropped: list[str] = Field(default_factory=list)
    kept: dict = Field(default_factory=dict)
    still_missing: list[str] = Field(default_factory=list)


class ConflictResult(BaseModel):
    summary: str
    open_conflicts: list[str] = Field(default_factory=list)
    resolved: bool = False


def _describe(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(v.value if hasattr(v, "value") else v) for v in value)
    return str(value.value if hasattr(value, "value") else value)


# --------------------------------------------------------------------------
# T023 — slot capture
# --------------------------------------------------------------------------


def update_slots(
    session: Session,
    state: SessionState,
    mode: Mode | None = None,
    use_case: str | None = None,
    category: str | None = None,
    budget_max: int | None = None,
    budget_min: int | None = None,
    target_date: date | None = None,
    duration_days: int | None = None,
    seats_min: int | None = None,
    fuel: list[FuelType] | None = None,
    transmission: Transmission | None = None,
    brand_affinity: list[str] | None = None,
    year_min: int | None = None,
    km_max: int | None = None,
    city: str | None = None,
    country: str | None = None,
) -> SlotUpdateResult:
    """Record whatever the user just revealed.

    Partial and out-of-order by design (FR-004): pass only what was learned
    this turn. Slots not mentioned are left alone, so the model never has to
    restate the whole constraint set to change one field.

    A mode change is deliberately NOT handled here — that discards other
    slots, so it goes through `change_mode` where the consequences are
    explicit.
    """
    incoming = {
        "use_case": use_case,
        "category": category,
        "budget_max": budget_max,
        "budget_min": budget_min,
        "target_date": target_date,
        "duration_days": duration_days,
        "seats_min": seats_min,
        "fuel": fuel,
        "transmission": transmission,
        "brand_affinity": brand_affinity,
        "year_min": year_min,
        "km_max": km_max,
        "city": city,
        "country": country,
    }

    updated: list[str] = []
    rejected: list[str] = []

    # Setting mode for the first time is ordinary; changing it is not.
    if mode is not None:
        if state.constraints.mode is None:
            state.constraints.mode = mode
            updated.append("mode")
        elif state.constraints.mode != mode:
            rejected.append("mode")

    for name, value in incoming.items():
        if value is None:
            continue
        if name not in SETTABLE:  # pragma: no cover - defensive
            rejected.append(name)
            continue
        setattr(state.constraints, name, value)
        updated.append(name)

    # A rental duration and a start date imply an end date; carrying both
    # separately would let them drift apart.
    if state.constraints.duration_days and state.constraints.target_date:
        state.constraints.duration_days = state.constraints.duration_days

    conflict = detect_conflict(session, state.constraints)
    if conflict is not None:
        existing = {c.kind for c in state.open_conflicts}
        if conflict.kind not in existing:
            state.conflicts.append(conflict)
    else:
        for c in state.conflicts:
            c.resolved = True

    state.touch()

    missing = state.constraints.missing_required()
    open_conflicts = state.open_conflicts

    if rejected:
        summary = (
            "Recorded "
            + ", ".join(updated)
            + ". Mode cannot be changed here — use change_mode, which will "
            "tell the user what has to be re-asked."
        )
    elif not updated:
        summary = "Nothing new to record."
    else:
        parts = [
            f"{name} = {_describe(getattr(state.constraints, name))}"
            for name in updated
        ]
        summary = "Recorded " + "; ".join(parts) + "."

    if open_conflicts:
        summary += " " + open_conflicts[0].description
        if open_conflicts[0].relaxations:
            summary += " " + open_conflicts[0].relaxations[0]
    elif missing:
        summary += " Still needed: " + ", ".join(missing) + "."
    else:
        summary += " Everything required is now known."

    return SlotUpdateResult(
        summary=summary,
        updated=updated,
        rejected=rejected,
        known=state.constraints.filled(),
        still_missing=missing,
        conflict=open_conflicts[0].description if open_conflicts else None,
        ready_to_search=not missing and not open_conflicts,
    )


# --------------------------------------------------------------------------
# T024 — conflicts
# --------------------------------------------------------------------------


def flag_conflict(
    state: SessionState,
    kind: str,
    fields: list[str],
    description: str,
    relaxations: list[str] | None = None,
) -> ConflictResult:
    """Record a conflict the model spotted that inventory analysis would not.

    Inventory-derived conflicts are found automatically by `update_slots`.
    This exists for the semantic kind — "you want a two-seater for a family
    of five" — which no query can detect.
    """
    from app.state.models import Conflict

    state.conflicts.append(
        Conflict(
            kind=kind,
            fields=fields,
            description=description,
            relaxations=relaxations or [],
        )
    )
    state.touch()
    return ConflictResult(
        summary=f"Conflict noted: {description}",
        open_conflicts=[c.description for c in state.open_conflicts],
    )


def resolve_conflict(
    session: Session, state: SessionState, kind: str | None = None
) -> ConflictResult:
    """Mark a conflict settled after the user chose how to relax it.

    Inventory-derived conflicts are re-checked against the catalogue rather
    than taken on trust — if the constraints still match nothing, the
    conflict stays open however confident the model is that it fixed it.
    """
    target = [
        c for c in state.open_conflicts if kind is None or c.kind == kind
    ]
    if not target:
        return ConflictResult(
            summary="No matching open conflict.",
            open_conflicts=[c.description for c in state.open_conflicts],
        )

    still_unsatisfiable = not analyse(session, state.constraints).satisfiable
    if still_unsatisfiable:
        return ConflictResult(
            summary=(
                "The constraints still match nothing, so the conflict "
                "remains. The user needs to relax something further."
            ),
            open_conflicts=[c.description for c in state.open_conflicts],
        )

    for conflict in target:
        conflict.resolved = True
    state.touch()

    return ConflictResult(
        summary="Conflict resolved; the constraints now match inventory.",
        open_conflicts=[c.description for c in state.open_conflicts],
        resolved=True,
    )


# --------------------------------------------------------------------------
# T025 — mid-flow mode change (Scenario C)
# --------------------------------------------------------------------------


def change_mode(
    session: Session, state: SessionState, new_mode: Mode
) -> ModeChangeResult:
    """Switch between buying and renting, keeping only what still applies.

    Seat count and body type survive; budget and dates do not, because
    Rs.800,000 as a purchase price and as a daily rate are different
    requirements wearing the same number. Returning the dropped slots lets
    the agent tell the user what it needs to re-ask instead of silently
    losing their answers.
    """
    if state.constraints.mode == new_mode:
        return ModeChangeResult(
            summary=f"Already {new_mode.value}ing; nothing changed.",
            new_mode=new_mode,
            kept=state.constraints.filled(),
            still_missing=state.constraints.missing_required(),
        )

    previous = state.constraints.mode
    dropped = state.apply_mode_change(new_mode)

    conflict = detect_conflict(session, state.constraints)
    if conflict is not None:
        state.conflicts.append(conflict)

    missing = state.constraints.missing_required()
    kept = state.constraints.filled()

    was = f"from {previous.value} " if previous else ""
    summary = f"Switched {was}to {new_mode.value}."
    if dropped:
        summary += (
            " These no longer apply and need re-asking: " + ", ".join(dropped) + "."
        )
    if kept:
        retained = [k for k in kept if k != "mode"]
        if retained:
            summary += " Kept: " + ", ".join(retained) + "."
    if state.shortlist == [] and previous is not None:
        summary += " Previous results were discarded."

    return ModeChangeResult(
        summary=summary,
        new_mode=new_mode,
        dropped=dropped,
        kept=kept,
        still_missing=missing,
    )


# --------------------------------------------------------------------------
# FR-007 — amend anything, at any time
# --------------------------------------------------------------------------


def revise_constraints(
    session: Session,
    state: SessionState,
    clear: list[str] | None = None,
    **updates: object,
) -> SlotUpdateResult:
    """Change or remove constraints after the interview has moved on.

    Available in every phase, because a user may reconsider at any point —
    including after seeing recommendations. Clearing a slot is distinct from
    setting it: `update_slots` cannot express "forget my brand preference".
    """
    cleared: list[str] = []
    for name in clear or []:
        if name not in SETTABLE:
            continue
        empty = [] if name in ("fuel", "brand_affinity") else None
        setattr(state.constraints, name, empty)
        cleared.append(name)

    result = update_slots(session, state, **updates)  # type: ignore[arg-type]

    if cleared:
        result = result.model_copy(
            update={
                "summary": f"Cleared {', '.join(cleared)}. " + result.summary,
                "updated": result.updated + [f"-{c}" for c in cleared],
                "known": state.constraints.filled(),
                "still_missing": state.constraints.missing_required(),
            }
        )

    # Results computed under the old constraints no longer describe reality.
    if state.shortlist or state.reasoning_log:
        state.shortlist = []
        state.reasoning_log = []
        state.touch()
        result = result.model_copy(
            update={
                "summary": result.summary + " Previous results were discarded.",
            }
        )

    return result
