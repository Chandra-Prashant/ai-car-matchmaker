"""Agent state models.

Serves FR-023 (continuity across phases), FR-024 (replayable decisions) and
Constitution III (state is explicit and inspectable).

The agent's memory lives here as a serialisable object, not implicitly in the
model's context window. Two consequences that matter:

1. The orchestrator can enforce phase transitions deterministically, because
   the conditions for advancing are properties of this object rather than
   something the model asserts about itself.
2. The current state can be rendered to the user at any moment (FR-005),
   which is what makes the interview panel possible.
"""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.models.listing import FuelType, Mode, Transmission


class Phase(str, enum.Enum):
    INTERVIEW = "interview"
    RESEARCH = "research"
    RECOMMEND = "recommend"
    BOOK = "book"
    COMPLETE = "complete"


class WeightSource(str, enum.Enum):
    INFERRED = "inferred"
    FALLBACK = "fallback"


# --------------------------------------------------------------------------
# Constraints
# --------------------------------------------------------------------------


class ConstraintSet(BaseModel):
    """What the user wants, as gathered so far.

    Every field is optional: the interview fills them progressively and in
    whatever order the user volunteers them (FR-004).
    """

    # The five required by FR-001 before research may begin.
    mode: Mode | None = None
    use_case: str | None = None
    category: str | None = None
    budget_max: int | None = None
    target_date: date | None = None

    # Refinements.
    budget_min: int | None = None
    duration_days: int | None = None
    seats_min: int | None = None
    fuel: list[FuelType] = Field(default_factory=list)
    transmission: Transmission | None = None
    brand_affinity: list[str] = Field(default_factory=list)
    year_min: int | None = None
    km_max: int | None = None
    city: str | None = None
    country: str | None = None

    # Slots whose meaning does not depend on buy-vs-rent. When the user
    # changes mode mid-flow (Scenario C, T025), these survive and the rest
    # are re-elicited — a budget of 800000 means something entirely
    # different as a daily rate.
    MODE_INDEPENDENT: tuple[str, ...] = (
        "use_case", "category", "seats_min", "fuel", "transmission",
        "brand_affinity", "city", "country",
    )
    REQUIRED: tuple[str, ...] = (
        "mode", "use_case", "category", "budget_max", "target_date",
    )

    model_config = {"ignored_types": (tuple,)}

    def missing_required(self) -> list[str]:
        return [name for name in self.REQUIRED if not getattr(self, name)]

    def is_complete(self) -> bool:
        return not self.missing_required()

    def filled(self) -> dict[str, object]:
        """Only the slots that carry a value — what the UI panel renders."""
        return {
            name: value
            for name, value in self.model_dump(exclude_none=True).items()
            if value not in ([], "")
        }

    def surviving_mode_change(self) -> ConstraintSet:
        """Return a copy retaining only mode-independent slots.

        Used when the user switches between buying and renting. Everything
        priced or dated is dropped rather than silently reinterpreted.
        """
        kept = {
            name: getattr(self, name)
            for name in self.MODE_INDEPENDENT
            if getattr(self, name)
        }
        return ConstraintSet(**kept)


# --------------------------------------------------------------------------
# Conflicts
# --------------------------------------------------------------------------


class Conflict(BaseModel):
    """A pair of constraints that cannot both be satisfied (FR-006).

    Surfaced to the user rather than resolved silently: the agent must not
    quietly drop one of the user's stated requirements.
    """

    kind: str
    fields: list[str]
    description: str
    relaxations: list[str] = Field(default_factory=list)
    resolved: bool = False


# --------------------------------------------------------------------------
# Reasoning
# --------------------------------------------------------------------------


class ScoreComponent(BaseModel):
    criterion: str
    raw_score: float = Field(ge=0.0, le=1.0)
    weight: float = Field(ge=0.0, le=1.0)

    @property
    def contribution(self) -> float:
        return self.raw_score * self.weight


class ReasoningRecord(BaseModel):
    """Why a listing was ranked where it was (FR-013).

    A recommendation the system cannot justify is a bug, not a result
    (Constitution IV), so this is required for every ranked listing rather
    than attached opportunistically.
    """

    listing_id: str
    rank: int
    total_score: float
    matched: list[str] = Field(default_factory=list)
    tradeoffs: list[str] = Field(default_factory=list)
    breakdown: list[ScoreComponent] = Field(default_factory=list)
    weight_source: WeightSource = WeightSource.FALLBACK


# --------------------------------------------------------------------------
# History
# --------------------------------------------------------------------------


class ToolCallRecord(BaseModel):
    tool: str
    arguments: dict = Field(default_factory=dict)
    summary: str | None = None
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TurnRecord(BaseModel):
    """One exchange, kept so the session can be replayed (FR-024)."""

    role: Literal["user", "assistant", "system"]
    content: str
    phase: Phase
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PhaseTransition(BaseModel):
    from_phase: Phase
    to_phase: Phase
    reason: str
    at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------


class SessionState(BaseModel):
    session_id: str
    phase: Phase = Phase.INTERVIEW

    constraints: ConstraintSet = Field(default_factory=ConstraintSet)
    conflicts: list[Conflict] = Field(default_factory=list)

    inferred_weights: dict[str, float] = Field(default_factory=dict)
    weight_source: WeightSource = WeightSource.FALLBACK

    shortlist: list[str] = Field(default_factory=list)
    reasoning_log: list[ReasoningRecord] = Field(default_factory=list)

    booking_id: str | None = None
    confirmation_reference: str | None = None

    history: list[TurnRecord] = Field(default_factory=list)
    transitions: list[PhaseTransition] = Field(default_factory=list)

    # Guards against an agent looping inside a phase without progressing.
    turns_in_phase: int = 0

    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    # ----------------------------------------------------------------
    # Derived views
    # ----------------------------------------------------------------

    @property
    def open_conflicts(self) -> list[Conflict]:
        return [c for c in self.conflicts if not c.resolved]

    def panel(self) -> dict:
        """What the interview panel renders (FR-005)."""
        return {
            "phase": self.phase.value,
            "known": self.constraints.filled(),
            "missing": self.constraints.missing_required(),
            "conflicts": [c.description for c in self.open_conflicts],
            "shortlist_size": len(self.shortlist),
        }

    # ----------------------------------------------------------------
    # Mutations
    # ----------------------------------------------------------------

    def touch(self) -> None:
        self.updated_at = datetime.now(UTC)

    def record_turn(
        self,
        role: Literal["user", "assistant", "system"],
        content: str,
        tool_calls: list[ToolCallRecord] | None = None,
    ) -> None:
        self.history.append(
            TurnRecord(
                role=role,
                content=content,
                phase=self.phase,
                tool_calls=tool_calls or [],
            )
        )
        if role == "user":
            self.turns_in_phase += 1
        self.touch()

    def transition_to(self, phase: Phase, reason: str) -> None:
        """Record a phase change.

        Callers must check the guard first — see app/agent/phases.py. This
        method records the move; it does not authorise it.
        """
        self.transitions.append(
            PhaseTransition(from_phase=self.phase, to_phase=phase, reason=reason)
        )
        self.phase = phase
        self.turns_in_phase = 0
        self.touch()

    def apply_mode_change(self, new_mode: Mode) -> list[str]:
        """Switch buy/rent, keeping only what still applies (Scenario C).

        Returns the names of the slots that were dropped, so the agent can
        tell the user what it needs to re-ask rather than silently losing
        their answers.
        """
        before = self.constraints.filled()
        survivors = self.constraints.surviving_mode_change()
        survivors.mode = new_mode
        self.constraints = survivors

        dropped = [
            name for name in before if name not in survivors.filled() and name != "mode"
        ]
        self.shortlist = []
        self.reasoning_log = []
        self.conflicts = []
        self.touch()
        return dropped
