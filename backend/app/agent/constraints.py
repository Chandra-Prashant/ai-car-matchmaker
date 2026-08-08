"""Constraint satisfiability analysis.

Serves FR-006 (detect conflicts), FR-016 (name the binding constraint on an
empty result) and the guard in `phases.py` that blocks research while
conflicts are open.

WHY THIS QUERIES INVENTORY RATHER THAN APPLYING RULES
-----------------------------------------------------
A rule saying "luxury SUVs cost more than 15 lakh" would be a second source
of truth about the catalogue, and it would drift the moment the taxonomy
changed. Instead this module asks the repository directly: it runs the
constraint set, and if nothing matches, re-runs it with each constraint
dropped in turn. Whichever constraint's removal produces matches is the
binding one.

That gives an honest answer — "your budget is what rules everything out, and
raising it to X finds 6 cars" — instead of a guess, and the same mechanism
serves both requirements.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.listing import ListingFilter, Mode
from app.repositories.listing_repository import ListingRepository
from app.state.models import Conflict, ConstraintSet

#: Constraints worth testing for bindingness, in the order a user is most
#: likely to be willing to relax them. Mode is absent deliberately: switching
#: between buying and renting is a different decision, not a relaxation.
RELAXABLE = (
    "budget_max",
    "category",
    "seats_min",
    "fuel",
    "transmission",
    "brand_affinity",
    "year_min",
    "km_max",
    "city",
    "target_date",
)

HUMAN_NAMES = {
    "budget_max": "budget",
    "category": "vehicle type",
    "seats_min": "seat count",
    "fuel": "fuel type",
    "transmission": "transmission",
    "brand_affinity": "preferred brands",
    "year_min": "minimum year",
    "km_max": "mileage limit",
    "city": "city",
    "target_date": "date",
}


@dataclass(frozen=True)
class Relaxation:
    """One constraint that, if relaxed, would produce matches."""

    field: str
    human_name: str
    matches_if_dropped: int
    suggestion: str


@dataclass(frozen=True)
class Analysis:
    matches: int
    binding: tuple[Relaxation, ...]

    @property
    def satisfiable(self) -> bool:
        return self.matches > 0


def to_filter(constraints: ConstraintSet, limit: int = 1) -> ListingFilter:
    """Translate the interview's constraint set into a repository query."""
    return ListingFilter(
        mode=constraints.mode,
        category=constraints.category,
        brands=constraints.brand_affinity or None,
        price_min=constraints.budget_min,
        price_max=constraints.budget_max,
        year_min=constraints.year_min,
        km_max=constraints.km_max,
        fuel=constraints.fuel or None,
        transmission=constraints.transmission,
        seats_min=constraints.seats_min,
        city=constraints.city,
        country=constraints.country,
        available_from=constraints.target_date,
        limit=limit,
    )


def _without(constraints: ConstraintSet, field: str) -> ConstraintSet:
    data = constraints.model_dump()
    data[field] = [] if field in ("fuel", "brand_affinity") else None
    return ConstraintSet(**data)


def _suggest(field: str, constraints: ConstraintSet, found: int) -> str:
    name = HUMAN_NAMES.get(field, field)
    unit = "per day" if constraints.mode is Mode.RENT else ""

    if field == "budget_max" and constraints.budget_max:
        return (
            f"Raising the {name} above Rs.{constraints.budget_max:,}{unit} "
            f"would open up {found} listings."
        )
    if field == "category" and constraints.category:
        return (
            f"Looking beyond {constraints.category.replace('_', ' ')} "
            f"would find {found} listings."
        )
    if field == "seats_min" and constraints.seats_min:
        return (
            f"Accepting fewer than {constraints.seats_min} seats would find "
            f"{found} listings."
        )
    return f"Relaxing the {name} would find {found} listings."


def analyse(session: Session, constraints: ConstraintSet) -> Analysis:
    """Check satisfiability and, if empty, identify what is binding."""
    repo = ListingRepository(session)

    page = repo.search(to_filter(constraints))
    if page.total_matched > 0:
        return Analysis(matches=page.total_matched, binding=())

    relaxations: list[Relaxation] = []
    for field in RELAXABLE:
        value = getattr(constraints, field, None)
        if not value:
            continue
        relaxed = repo.search(to_filter(_without(constraints, field)))
        if relaxed.total_matched > 0:
            relaxations.append(
                Relaxation(
                    field=field,
                    human_name=HUMAN_NAMES.get(field, field),
                    matches_if_dropped=relaxed.total_matched,
                    suggestion=_suggest(field, constraints, relaxed.total_matched),
                )
            )

    # Most productive relaxation first.
    relaxations.sort(key=lambda r: r.matches_if_dropped, reverse=True)
    return Analysis(matches=0, binding=tuple(relaxations))


def detect_conflict(session: Session, constraints: ConstraintSet) -> Conflict | None:
    """Return a Conflict if the constraint set cannot be satisfied.

    Called after every slot update during the interview, so the user learns
    their requirements are incompatible while they are still stating them —
    not after a search comes back empty.
    """
    # Nothing to check until enough is known for the answer to mean something.
    if not constraints.mode or not (constraints.category or constraints.budget_max):
        return None

    result = analyse(session, constraints)
    if result.satisfiable:
        return None

    if not result.binding:
        return Conflict(
            kind="no_inventory",
            fields=[],
            description=(
                "Nothing in the catalogue matches these requirements, and no "
                "single change fixes it."
            ),
            relaxations=["Consider changing more than one requirement."],
        )

    top = result.binding[:3]
    fields = [r.field for r in top]
    names = " and ".join(HUMAN_NAMES.get(f, f) for f in fields[:2])

    return Conflict(
        kind="unsatisfiable",
        fields=fields,
        description=(
            f"No listing satisfies all of these requirements — {names} "
            f"conflict with each other."
        ),
        relaxations=[r.suggestion for r in top],
    )


def describe_empty_result(session: Session, constraints: ConstraintSet) -> str:
    """FR-016: name the binding constraint and offer a specific relaxation."""
    result = analyse(session, constraints)
    if result.satisfiable:
        return f"{result.matches} listings match."

    if not result.binding:
        return (
            "Nothing matches, and relaxing any single requirement is not "
            "enough. More than one will need to change."
        )

    top = result.binding[0]
    lines = [
        f"Nothing matches. The {top.human_name} is what rules everything out.",
        top.suggestion,
    ]
    if len(result.binding) > 1:
        alt = result.binding[1]
        lines.append(f"Alternatively: {alt.suggestion}")
    return " ".join(lines)
