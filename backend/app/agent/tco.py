"""Buy-versus-rent cost comparison.

Serves T029 and FR-015.

This is the part of the agent that reasons about the user's actual problem
rather than filtering a catalogue. Someone who needs a car for six weeks is
not asking "which SUV is cheapest" — they are asking a question they may not
have framed yet, and the answer flips depending on duration.

WHAT IS MODELLED
----------------
Ownership over a short horizon = depreciation + transaction friction +
carrying costs. Transaction friction is the piece that matters most and is
usually omitted: you cannot buy a car and resell it six weeks later at market
value. Registration, transfer, and the buyer's-discount reality of a quick
resale are what make renting correct at short durations, so leaving them out
would produce a confidently wrong recommendation.

WHAT IS NOT MODELLED
--------------------
- Cost of capital. Rigorous, but it adds a number nobody questions and
  nobody understands. Excluded deliberately rather than forgotten.
- Fuel and tolls. Identical under either option for the same journey, so
  they cancel and would only inflate both sides.
- Tax treatment, financing, and leasing. Out of scope per spec section 4.

Every constant below is exposed in the result's `assumptions`, so the agent
can show its working instead of asserting a number.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.models.listing import ListingRead
from app.repositories.listing_repository import ListingRepository

# --------------------------------------------------------------------------
# Assumptions — all named, all surfaced to the user
# --------------------------------------------------------------------------

#: Value lost the moment a car changes hands, over and above time-based
#: depreciation. Covers registration transfer, dealer margin on a quick
#: resale, and the discount a private buyer expects.
TRANSACTION_FRICTION_PCT = 0.11

#: One-off costs on purchase: registration, road tax, first insurance.
#: Expressed as a share of the purchase price.
ACQUISITION_COST_PCT = 0.09

#: Time-based depreciation, annual, applied pro-rata across the holding
#: period. Matches the generator's model so quotes and comparisons agree.
ANNUAL_DEPRECIATION_PCT = 0.13

#: Insurance and road tax carried while owning, annual, as a share of value.
ANNUAL_CARRYING_PCT = 0.035

#: Routine servicing while owning, per day, flat.
MAINTENANCE_PER_DAY_INR = 45

#: Rentals bundle insurance and servicing; owners do not. No extra term is
#: needed on the rental side beyond the quoted rate.

DAYS_PER_YEAR = 365


class CostLine(BaseModel):
    label: str
    amount_inr: int
    note: str | None = None


class OptionCost(BaseModel):
    option: str
    total_inr: int
    per_day_inr: int
    lines: list[CostLine] = Field(default_factory=list)


class TcoComparison(BaseModel):
    summary: str
    duration_days: int
    buy: OptionCost | None = None
    rent: OptionCost | None = None
    recommendation: str | None = None
    saving_inr: int | None = None
    crossover_days: int | None = None
    assumptions: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Cost models
# --------------------------------------------------------------------------


def _ownership_cost(price: int, days: int) -> OptionCost:
    """Net cost of buying, holding for `days`, then selling."""
    years = days / DAYS_PER_YEAR

    acquisition = round(price * ACQUISITION_COST_PCT)
    time_depreciation = round(price * ANNUAL_DEPRECIATION_PCT * years)
    friction = round(price * TRANSACTION_FRICTION_PCT)
    carrying = round(price * ANNUAL_CARRYING_PCT * years)
    maintenance = round(MAINTENANCE_PER_DAY_INR * days)

    total = acquisition + time_depreciation + friction + carrying + maintenance

    return OptionCost(
        option="buy",
        total_inr=total,
        per_day_inr=round(total / max(1, days)),
        lines=[
            CostLine(
                label="Registration, road tax, insurance",
                amount_inr=acquisition,
                note=f"{ACQUISITION_COST_PCT:.0%} of purchase price",
            ),
            CostLine(
                label="Depreciation over the period",
                amount_inr=time_depreciation,
                note=f"{ANNUAL_DEPRECIATION_PCT:.0%} per year, pro-rated",
            ),
            CostLine(
                label="Resale loss",
                amount_inr=friction,
                note="value lost simply by buying and selling again",
            ),
            CostLine(
                label="Insurance and tax while owned",
                amount_inr=carrying,
                note=f"{ANNUAL_CARRYING_PCT:.1%} per year, pro-rated",
            ),
            CostLine(
                label="Servicing",
                amount_inr=maintenance,
                note=f"Rs.{MAINTENANCE_PER_DAY_INR}/day",
            ),
        ],
    )


def _rental_cost(rate: int, days: int, weekly_discount_pct: int | None) -> OptionCost:
    gross = rate * days
    discount = 0
    if days >= 7 and weekly_discount_pct:
        discount = round(gross * weekly_discount_pct / 100)

    total = gross - discount
    lines = [
        CostLine(
            label=f"{days} days at Rs.{rate:,}/day",
            amount_inr=gross,
        )
    ]
    if discount:
        lines.append(
            CostLine(
                label="Weekly rate discount",
                amount_inr=-discount,
                note=f"{weekly_discount_pct}% for 7 days or more",
            )
        )
    lines.append(
        CostLine(
            label="Insurance and servicing",
            amount_inr=0,
            note="included in the rental rate",
        )
    )

    return OptionCost(
        option="rent",
        total_inr=total,
        per_day_inr=round(total / max(1, days)),
        lines=lines,
    )


def _crossover(price: int, rate: int, weekly_discount_pct: int | None) -> int | None:
    """Duration at which buying becomes cheaper than renting.

    Searched rather than solved: the rental side has a discount step at seven
    days, so the functions are not both smooth and a closed form would be
    wrong at the boundary.
    """
    for days in range(1, 365 * 3 + 1):
        buy = _ownership_cost(price, days).total_inr
        rent = _rental_cost(rate, days, weekly_discount_pct).total_inr
        if buy <= rent:
            return days
    return None


def _assumptions() -> list[str]:
    return [
        f"Registration and first insurance taken as {ACQUISITION_COST_PCT:.0%} "
        "of the purchase price.",
        f"Depreciation of {ANNUAL_DEPRECIATION_PCT:.0%} per year, applied "
        "pro-rata.",
        f"A further {TRANSACTION_FRICTION_PCT:.0%} lost on resale, reflecting "
        "that a car cannot be bought and sold quickly at market value.",
        f"Insurance and road tax while owning at {ANNUAL_CARRYING_PCT:.1%} "
        "per year; servicing at Rs.{:,}/day.".format(MAINTENANCE_PER_DAY_INR),
        "Fuel and tolls excluded — identical under either option.",
        "Financing, leasing and tax treatment are out of scope.",
    ]


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------


def compare_listing(listing: ListingRead, days: int) -> TcoComparison:
    """Compare buying and renting one dual-mode listing over `days`."""
    if days < 1:
        return TcoComparison(
            summary="A duration of at least one day is needed to compare.",
            duration_days=days,
        )

    buy = (
        _ownership_cost(listing.price_inr, days)
        if listing.for_sale and listing.price_inr
        else None
    )
    rent = (
        _rental_cost(listing.rent_per_day_inr, days, listing.weekly_discount_pct)
        if listing.for_rent and listing.rent_per_day_inr
        else None
    )

    name = f"{listing.year} {listing.brand} {listing.model}"

    if buy and not rent:
        return TcoComparison(
            summary=f"{name} is only offered for sale, so there is nothing to compare.",
            duration_days=days,
            buy=buy,
            assumptions=_assumptions(),
        )
    if rent and not buy:
        return TcoComparison(
            summary=f"{name} is only offered for rental.",
            duration_days=days,
            rent=rent,
            assumptions=_assumptions(),
        )
    if not buy and not rent:  # pragma: no cover - defensive
        return TcoComparison(
            summary=f"No pricing available for {name}.", duration_days=days
        )

    cheaper = "rent" if rent.total_inr < buy.total_inr else "buy"
    saving = abs(buy.total_inr - rent.total_inr)
    crossover = _crossover(
        listing.price_inr, listing.rent_per_day_inr, listing.weekly_discount_pct
    )

    weeks = round(days / 7, 1)
    summary = (
        f"Over {days} days ({weeks} weeks), renting the {name} costs "
        f"Rs.{rent.total_inr:,} against Rs.{buy.total_inr:,} to buy and "
        f"resell — {'renting' if cheaper == 'rent' else 'buying'} is "
        f"Rs.{saving:,} cheaper."
    )

    if crossover:
        summary += (
            f" Buying overtakes renting at about {crossover} days"
            f" ({round(crossover / 30)} months)."
        )
        recommendation = (
            f"Rent — the period is well short of the {crossover}-day crossover."
            if days < crossover
            else f"Buy — the period is past the {crossover}-day crossover."
        )
    else:
        recommendation = (
            "Rent — buying does not become cheaper within a three-year horizon."
        )

    caveats = [
        "Ownership assumes the car is sold at the end of the period; keeping "
        "it longer changes the picture substantially.",
    ]
    if days < 7:
        caveats.append(
            "Very short periods may also carry minimum-hire terms not "
            "reflected here."
        )

    return TcoComparison(
        summary=summary,
        duration_days=days,
        buy=buy,
        rent=rent,
        recommendation=recommendation,
        saving_inr=saving,
        crossover_days=crossover,
        assumptions=_assumptions(),
        caveats=caveats,
    )


def compute_tco(session: Session, listing_id: str, days: int) -> TcoComparison:
    """Agent-facing entry point (FR-015)."""
    listing = ListingRepository(session).get(listing_id)
    if listing is None:
        return TcoComparison(
            summary=f"No listing with ID {listing_id}.", duration_days=days
        )
    return compare_listing(listing, days)


def compare_shortlist(
    session: Session, listing_ids: list[str], days: int
) -> list[TcoComparison]:
    """Run the comparison across a shortlist, dual-mode listings only."""
    listings = ListingRepository(session).get_many(listing_ids)
    return [
        compare_listing(listing, days)
        for listing in listings
        if listing.for_sale and listing.for_rent
    ]
