"""Ranking, weight inference, and explanation.

Serves T026, T027, T028 and FR-012, FR-013. Implements the Q2 decision
recorded in plan.md: inferred weights with a fixed fallback.

WHAT IS AND IS NOT SCORED
-------------------------
Hard constraints — budget ceiling, date window, minimum seats — are filters
applied by the repository before anything reaches this module. A listing that
violates one is absent, not penalised. Scoring therefore only ever orders
listings that already satisfy every stated requirement, which is what makes
"no recommendation exceeds the stated budget" a structural fact rather than
a probabilistic one.

WEIGHT INFERENCE (Q2)
---------------------
The agent may propose emphasis based on how the user phrased their needs —
"I really can't stretch past 8 lakh but I'm relaxed about the year" should
raise the budget weight and lower the year weight. Every proposed delta is
clamped to +/-0.15, every weight is floored, and the set is renormalised.

If the agent proposes nothing, or proposes something unusable, the base
weights apply and `weight_source` reports `fallback`. That flag is shown in
the UI: a system that says when it inferred and when it did not is more
trustworthy than one that always claims to have reasoned.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models.listing import ListingRead, Mode
from app.repositories.listing_repository import ListingRepository
from app.state.models import (
    ConstraintSet,
    ReasoningRecord,
    ScoreComponent,
    SessionState,
    WeightSource,
)

#: Base weights, summing to 1.0. Used directly as the fallback, and as the
#: starting point that inference adjusts.
BASE_WEIGHTS: dict[str, float] = {
    "budget": 0.22,
    "recency": 0.14,
    "category": 0.14,
    "condition": 0.10,
    "seats": 0.10,
    "fuel": 0.08,
    "transmission": 0.06,
    "brand": 0.06,
    "availability": 0.06,
    "location": 0.04,
}

#: How far the agent may move any single weight. Bounded so that inference
#: reorders results without letting one criterion dominate the rest.
MAX_DELTA = 0.15
MIN_WEIGHT = 0.01

#: A criterion at or above this counts as a match worth naming.
MATCH_THRESHOLD = 0.75
#: At or below this it is a trade-off the user should be told about.
TRADEOFF_THRESHOLD = 0.45

CRITERION_LABELS = {
    "budget": "price against budget",
    "recency": "model year",
    "category": "vehicle type",
    "condition": "mileage and condition",
    "seats": "seating",
    "fuel": "fuel type",
    "transmission": "transmission",
    "brand": "brand preference",
    "availability": "availability",
    "location": "location",
}

MAX_PLAUSIBLE_AGE = 10
MAX_PLAUSIBLE_KM = 150_000


# --------------------------------------------------------------------------
# Weights
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class WeightSet:
    weights: dict[str, float]
    source: WeightSource
    adjustments: dict[str, float]


def resolve_weights(emphasis: dict[str, float] | None) -> WeightSet:
    """Apply the agent's proposed emphasis within bounds.

    Unknown criteria are ignored rather than rejected — a model that invents
    a criterion name should not break ranking.
    """
    if not emphasis:
        return WeightSet(dict(BASE_WEIGHTS), WeightSource.FALLBACK, {})

    applied: dict[str, float] = {}
    weights = dict(BASE_WEIGHTS)

    for criterion, delta in emphasis.items():
        if criterion not in weights:
            continue
        try:
            value = float(delta)
        except (TypeError, ValueError):
            continue
        clamped = max(-MAX_DELTA, min(MAX_DELTA, value))
        if clamped == 0:
            continue
        weights[criterion] = max(MIN_WEIGHT, weights[criterion] + clamped)
        applied[criterion] = clamped

    if not applied:
        return WeightSet(dict(BASE_WEIGHTS), WeightSource.FALLBACK, {})

    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}
    return WeightSet(weights, WeightSource.INFERRED, applied)


# --------------------------------------------------------------------------
# Per-criterion scoring
# --------------------------------------------------------------------------


def _price_of(listing: ListingRead, mode: Mode | None) -> int | None:
    if mode is Mode.RENT:
        return listing.rent_per_day_inr
    if mode is Mode.BUY:
        return listing.price_inr
    return listing.price_inr or listing.rent_per_day_inr


def _score_budget(listing: ListingRead, c: ConstraintSet) -> tuple[float, str]:
    price = _price_of(listing, c.mode)
    if price is None or not c.budget_max:
        return 0.5, "no budget stated"
    ratio = price / c.budget_max
    score = max(0.0, min(1.0, 1.0 - ratio))
    pct = round(ratio * 100)
    return score, f"uses {pct}% of budget"


def _score_recency(listing: ListingRead, _c: ConstraintSet) -> tuple[float, str]:
    age = max(0, 2026 - listing.year)
    score = max(0.0, 1.0 - age / MAX_PLAUSIBLE_AGE)
    label = "current model year" if age == 0 else f"{age} year{'s' if age > 1 else ''} old"
    return score, label


def _score_category(listing: ListingRead, c: ConstraintSet) -> tuple[float, str]:
    if not c.category:
        return 0.5, "no type stated"
    if listing.category == c.category:
        return 1.0, "matches requested type"
    return 0.35, f"is {listing.category.replace('_', ' ')}, not {c.category.replace('_', ' ')}"


def _score_condition(listing: ListingRead, _c: ConstraintSet) -> tuple[float, str]:
    if listing.condition.value == "new":
        return 1.0, "new"
    score = max(0.0, 1.0 - listing.km / MAX_PLAUSIBLE_KM)
    return score, f"{listing.km:,} km"


def _score_seats(listing: ListingRead, c: ConstraintSet) -> tuple[float, str]:
    if not c.seats_min:
        return 0.5, "no seat requirement"
    if listing.seats < c.seats_min:  # pragma: no cover - filtered upstream
        return 0.0, f"only {listing.seats} seats"
    surplus = listing.seats - c.seats_min
    # Meeting the requirement is what matters; a much larger car is mildly
    # worse, not better.
    score = 1.0 if surplus <= 1 else max(0.6, 1.0 - surplus * 0.08)
    return score, f"{listing.seats} seats"


def _score_fuel(listing: ListingRead, c: ConstraintSet) -> tuple[float, str]:
    if not c.fuel:
        return 0.5, "no fuel preference"
    if listing.fuel in c.fuel:
        return 1.0, f"{listing.fuel.value}, as preferred"
    return 0.25, f"{listing.fuel.value}, not preferred"


def _score_transmission(listing: ListingRead, c: ConstraintSet) -> tuple[float, str]:
    if not c.transmission:
        return 0.5, "no transmission preference"
    if listing.transmission == c.transmission:
        return 1.0, f"{listing.transmission.value}, as preferred"
    return 0.25, f"{listing.transmission.value}, not preferred"


def _score_brand(listing: ListingRead, c: ConstraintSet) -> tuple[float, str]:
    if not c.brand_affinity:
        return 0.5, "no brand preference"
    if listing.brand in c.brand_affinity:
        return 1.0, f"{listing.brand}, a preferred brand"
    return 0.4, f"{listing.brand}, outside stated preferences"


def _score_availability(listing: ListingRead, c: ConstraintSet) -> tuple[float, str]:
    if not c.target_date:
        return 0.5, "no date stated"
    if listing.available_from <= c.target_date:
        return 1.0, f"available from {listing.available_from}"
    days = (listing.available_from - c.target_date).days
    score = max(0.0, 1.0 - days / 30)
    return score, f"available {days} days after the target date"


def _score_location(listing: ListingRead, c: ConstraintSet) -> tuple[float, str]:
    if not c.city and not c.country:
        return 0.5, listing.city
    if c.city and listing.city == c.city:
        return 1.0, f"in {listing.city}"
    if c.country and listing.country == c.country:
        return 0.7, f"in {listing.city}, same country"
    return 0.3, f"in {listing.city}"


SCORERS = {
    "budget": _score_budget,
    "recency": _score_recency,
    "category": _score_category,
    "condition": _score_condition,
    "seats": _score_seats,
    "fuel": _score_fuel,
    "transmission": _score_transmission,
    "brand": _score_brand,
    "availability": _score_availability,
    "location": _score_location,
}


# --------------------------------------------------------------------------
# Ranking
# --------------------------------------------------------------------------


def score_listing(
    listing: ListingRead, constraints: ConstraintSet, weights: dict[str, float]
) -> tuple[float, list[ScoreComponent], list[str], list[str]]:
    """Score one listing. Returns total, breakdown, matched, trade-offs."""
    components: list[ScoreComponent] = []
    matched: list[str] = []
    tradeoffs: list[str] = []
    total = 0.0

    for criterion, scorer in SCORERS.items():
        raw, note = scorer(listing, constraints)
        weight = weights.get(criterion, 0.0)
        components.append(
            ScoreComponent(criterion=criterion, raw_score=raw, weight=weight)
        )
        total += raw * weight

        label = CRITERION_LABELS[criterion]
        if raw >= MATCH_THRESHOLD:
            matched.append(f"{label}: {note}")
        elif raw <= TRADEOFF_THRESHOLD:
            tradeoffs.append(f"{label}: {note}")

    return total, components, matched, tradeoffs


def rank_shortlist(
    session: Session,
    state: SessionState,
    emphasis: dict[str, float] | None = None,
) -> list[ReasoningRecord]:
    """Rank the session's shortlist and record why (FR-012, FR-013).

    Writes `reasoning_log`, `inferred_weights` and `weight_source` onto the
    state, and reorders `shortlist` into ranked order so downstream steps see
    a consistent sequence.
    """
    if not state.shortlist:
        return []

    listings = ListingRepository(session).get_many(state.shortlist)
    weight_set = resolve_weights(emphasis)

    scored: list[tuple[float, ListingRead, list[ScoreComponent], list[str], list[str]]] = []
    for listing in listings:
        total, components, matched, tradeoffs = score_listing(
            listing, state.constraints, weight_set.weights
        )
        scored.append((total, listing, components, matched, tradeoffs))

    # Listing id as tiebreaker keeps ranking deterministic (FR-027).
    scored.sort(key=lambda row: (-row[0], row[1].id))

    records = [
        ReasoningRecord(
            listing_id=listing.id,
            rank=index + 1,
            total_score=round(total, 4),
            matched=matched,
            tradeoffs=tradeoffs,
            breakdown=components,
            weight_source=weight_set.source,
        )
        for index, (total, listing, components, matched, tradeoffs) in enumerate(scored)
    ]

    state.reasoning_log = records
    state.shortlist = [record.listing_id for record in records]
    state.inferred_weights = weight_set.weights
    state.weight_source = weight_set.source
    state.touch()
    return records


def explain(record: ReasoningRecord, listing: ListingRead) -> str:
    """One paragraph the agent can say aloud about a ranked listing."""
    name = f"{listing.year} {listing.brand} {listing.model}"
    lines = [f"#{record.rank} {name} (score {record.total_score:.2f})."]

    if record.matched:
        lines.append("Fits on " + "; ".join(record.matched[:3]) + ".")
    if record.tradeoffs:
        lines.append("Compromises on " + "; ".join(record.tradeoffs[:2]) + ".")

    top = max(record.breakdown, key=lambda c: c.raw_score * c.weight)
    lines.append(
        f"{CRITERION_LABELS[top.criterion].capitalize()} contributed most to "
        f"this ranking."
    )
    return " ".join(lines)


def weight_summary(state: SessionState) -> str:
    """How the ranking was weighted — shown alongside results."""
    if state.weight_source is WeightSource.FALLBACK:
        return "Ranked using default criterion weights."

    ordered = sorted(state.inferred_weights.items(), key=lambda kv: -kv[1])[:3]
    named = ", ".join(f"{CRITERION_LABELS[k]} ({v:.0%})" for k, v in ordered)
    return f"Ranked with weights inferred from your priorities — mainly {named}."
