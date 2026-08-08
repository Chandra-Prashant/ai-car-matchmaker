"""Marketplace MCP server.

Exposes inventory search over MCP so the agent reaches listings through a tool
interface rather than from model recall (FR-008).

Serves T009, T010, T011.

DESIGN NOTES
------------
Every tool returns a Pydantic model whose first field is a human-readable
`summary`. Two reasons:

1. Constitution VII requires meaningful text output for hosts that cannot
   render structured content. Whatever the SDK does when serialising the
   result, the summary travels with it.
2. The summary is what lands in the model's context. A prose line costs far
   fewer tokens than the agent re-deriving "9 matched" from a JSON array, and
   it is what the agent quotes when narrating progress (FR-009).

This server carries no UI resources. Tools here are model-facing only; the
MCP Apps live in the booking and checkout servers.
"""

from __future__ import annotations

from datetime import date

from mcp.server import MCPServer
from pydantic import BaseModel, Field

from app.db import session_scope
from app.models.listing import (
    FuelType,
    ListingFilter,
    ListingRead,
    Mode,
    Transmission,
)
from app.repositories.listing_repository import ListingRepository

mcp = MCPServer(
    name="marketplace",
    title="Car Marketplace",
    description="Search rental and dealership inventory",
    version="0.1.0",
    instructions=(
        "Use these tools to find real listings. Never invent a listing or a "
        "price. search_listings reports how many candidates matched in total, "
        "not just how many were returned — use that number when telling the "
        "user how the search is narrowing."
    ),
)


# --------------------------------------------------------------------------
# Result models
# --------------------------------------------------------------------------


class SearchResult(BaseModel):
    summary: str = Field(description="Human-readable description of the result")
    total_matched: int
    returned: int
    listings: list[ListingRead]


class ComparisonResult(BaseModel):
    summary: str
    listings: list[ListingRead]
    differences: dict[str, list[str | int | None]] = Field(
        description="Attribute name to the value each listing holds, in order"
    )


class AvailabilityResult(BaseModel):
    summary: str
    listing_id: str
    available: bool
    reason: str | None = None
    window_start: date | None = None
    window_end: date | None = None


class FacetResult(BaseModel):
    summary: str
    field: str
    values: list[str]


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _describe(listing: ListingRead, mode: Mode | None) -> str:
    base = f"{listing.year} {listing.brand} {listing.model}"
    if mode is Mode.RENT and listing.rent_per_day_inr:
        return f"{base} — Rs.{listing.rent_per_day_inr:,}/day in {listing.city}"
    if listing.price_inr:
        return f"{base} — Rs.{listing.price_inr:,} in {listing.city}"
    if listing.rent_per_day_inr:
        return f"{base} — Rs.{listing.rent_per_day_inr:,}/day in {listing.city}"
    return f"{base} in {listing.city}"


def _summarise_search(page, spec: ListingFilter) -> str:
    if page.total_matched == 0:
        return "No listings matched those criteria."

    shown = len(page.items)
    lead = (
        f"{page.total_matched} listings matched"
        if shown >= page.total_matched
        else f"{page.total_matched} listings matched; showing the first {shown}"
    )
    examples = "; ".join(_describe(x, spec.mode) for x in page.items[:3])
    return f"{lead}. For example: {examples}."


# --------------------------------------------------------------------------
# Tools — T009, T010
# --------------------------------------------------------------------------


@mcp.tool(
    title="Search listings",
    description=(
        "Search car inventory. All filters are optional and combine with AND. "
        "Price bounds are interpreted per mode: against purchase price when "
        "mode is 'buy', against the daily rate when mode is 'rent'. Amounts "
        "are in Indian rupees."
    ),
)
def search_listings(
    mode: Mode | None = None,
    category: str | None = None,
    brands: list[str] | None = None,
    price_min: int | None = None,
    price_max: int | None = None,
    year_min: int | None = None,
    year_max: int | None = None,
    km_max: int | None = None,
    fuel: list[FuelType] | None = None,
    transmission: Transmission | None = None,
    seats_min: int | None = None,
    city: str | None = None,
    country: str | None = None,
    available_from: date | None = None,
    available_to: date | None = None,
    limit: int = 10,
) -> SearchResult:
    spec = ListingFilter(
        mode=mode,
        category=category,
        brands=brands,
        price_min=price_min,
        price_max=price_max,
        year_min=year_min,
        year_max=year_max,
        km_max=km_max,
        fuel=fuel,
        transmission=transmission,
        seats_min=seats_min,
        city=city,
        country=country,
        available_from=available_from,
        available_to=available_to,
        limit=limit,
    )

    with session_scope() as session:
        page = ListingRepository(session).search(spec)

    return SearchResult(
        summary=_summarise_search(page, spec),
        total_matched=page.total_matched,
        returned=len(page.items),
        listings=page.items,
    )


@mcp.tool(
    title="Compare listings",
    description=(
        "Compare two or more listings attribute by attribute. Returns the "
        "listings in the order given, plus a map of attributes to each "
        "listing's value so differences are directly readable."
    ),
)
def compare_listings(listing_ids: list[str]) -> ComparisonResult:
    with session_scope() as session:
        listings = ListingRepository(session).get_many(listing_ids)

    if not listings:
        return ComparisonResult(
            summary="None of those listing IDs exist.",
            listings=[],
            differences={},
        )

    attributes = (
        "brand", "model", "year", "km", "fuel", "transmission", "seats",
        "condition", "price_inr", "rent_per_day_inr", "city", "seller_name",
    )
    differences: dict[str, list[str | int | None]] = {}
    for attribute in attributes:
        values = [getattr(x, attribute) for x in listings]
        values = [v.value if hasattr(v, "value") else v for v in values]
        if len(set(map(str, values))) > 1:
            differences[attribute] = values

    missing = set(listing_ids) - {x.id for x in listings}
    note = f" ({len(missing)} of the requested IDs were not found)" if missing else ""
    names = " vs ".join(f"{x.year} {x.brand} {x.model}" for x in listings)

    return ComparisonResult(
        summary=(
            f"Comparing {names}{note}. "
            f"They differ on: {', '.join(differences) or 'nothing'}."
        ),
        listings=listings,
        differences=differences,
    )


@mcp.tool(
    title="Check availability",
    description=(
        "Check whether a listing is available across a date window. Purchase "
        "listings have no end date and are treated as open-ended."
    ),
)
def check_availability(
    listing_id: str,
    start: date,
    end: date | None = None,
) -> AvailabilityResult:
    with session_scope() as session:
        listing = ListingRepository(session).get(listing_id)

    if listing is None:
        return AvailabilityResult(
            summary=f"No listing with ID {listing_id}.",
            listing_id=listing_id,
            available=False,
            reason="unknown_listing",
        )

    requested_end = end or start
    starts_too_late = listing.available_from > requested_end
    ends_too_early = listing.available_to is not None and listing.available_to < start
    available = not (starts_too_late or ends_too_early)

    if available:
        reason = None
        summary = (
            f"{listing.year} {listing.brand} {listing.model} is available "
            f"from {listing.available_from}"
            + (f" to {listing.available_to}" if listing.available_to else " onwards")
            + "."
        )
    elif starts_too_late:
        reason = "not_available_until_later"
        summary = (
            f"Not available until {listing.available_from}, which is after "
            f"the requested window."
        )
    else:
        reason = "window_already_closed"
        summary = f"Availability ended on {listing.available_to}."

    return AvailabilityResult(
        summary=summary,
        listing_id=listing_id,
        available=available,
        reason=reason,
        window_start=listing.available_from,
        window_end=listing.available_to,
    )


@mcp.tool(
    title="List available values",
    description=(
        "List the distinct values held by a categorical field. Use this "
        "instead of guessing what categories, brands, or cities exist, and "
        "when a search returns nothing so you can name a workable alternative."
    ),
)
def list_facet_values(field: str) -> FacetResult:
    with session_scope() as session:
        try:
            values = ListingRepository(session).distinct_values(field)
        except ValueError as exc:
            return FacetResult(summary=str(exc), field=field, values=[])

    return FacetResult(
        summary=f"{len(values)} distinct values for {field}: {', '.join(values)}.",
        field=field,
        values=values,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
