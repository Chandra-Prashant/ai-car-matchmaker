"""A2UI envelope messages and surface construction.

Serves T031, T033-T037 and the challenge's requirement that catalogues and
agent progress be rendered through A2UI rather than static markup.

WHAT THIS MODULE DOES
---------------------
Turns tool results into A2UI messages. The agent decides *what* to show; this
module expresses that as a component tree plus a data model; the renderer
decides how it looks.

THE STRUCTURE / DATA SPLIT
--------------------------
A2UI separates the component tree from the data that populates it, and the
constraint panel is where that pays off. Its structure is sent once per
session; every subsequent turn sends only `updateDataModel` with the changed
values. The alternative — resending the whole panel each turn — would be
larger on the wire and would make the renderer rebuild a tree that has not
changed.

TEMPLATES OVER REPETITION
-------------------------
Lists bind `children` to a data path with a template component id, so five
listings cost one CarCard definition rather than five. Inside a template,
relative paths (`brand`) resolve against the current item; absolute paths
(`/mode`) still reach the surface root.
"""

from __future__ import annotations

from typing import Any

from app.a2ui.catalog import A2UI_VERSION, CATALOG_ID
from app.models.listing import ListingRead, Mode
from app.state.models import ReasoningRecord, SessionState

# --------------------------------------------------------------------------
# Envelope builders
# --------------------------------------------------------------------------


def create_surface(
    surface_id: str,
    components: list[dict[str, Any]] | None = None,
    data_model: dict[str, Any] | None = None,
    send_data_model: bool = False,
) -> dict[str, Any]:
    """A2UI `createSurface`.

    v1.0 allows the initial component tree and data to travel in this single
    message, which suits a streaming transport: one frame produces a complete
    rendered surface rather than three that must arrive in order.
    """
    payload: dict[str, Any] = {
        "surfaceId": surface_id,
        "catalogId": CATALOG_ID,
    }
    if send_data_model:
        payload["sendDataModel"] = True
    if components is not None:
        payload["components"] = components
    if data_model is not None:
        payload["dataModel"] = data_model

    return {"version": A2UI_VERSION, "createSurface": payload}


def update_components(
    surface_id: str, components: list[dict[str, Any]]
) -> dict[str, Any]:
    return {
        "version": A2UI_VERSION,
        "updateComponents": {"surfaceId": surface_id, "components": components},
    }


def update_data_model(
    surface_id: str, value: Any, path: str = "/"
) -> dict[str, Any]:
    return {
        "version": A2UI_VERSION,
        "updateDataModel": {
            "surfaceId": surface_id,
            "path": path,
            "value": value,
        },
    }


def delete_surface(surface_id: str) -> dict[str, Any]:
    return {"version": A2UI_VERSION, "deleteSurface": {"surfaceId": surface_id}}


# --------------------------------------------------------------------------
# Bindings
# --------------------------------------------------------------------------


def path(pointer: str) -> dict[str, str]:
    """A data binding. Absolute pointers start with '/'; relative ones
    resolve against the current item inside a list template."""
    return {"path": pointer}


def fn(call: str, **args: Any) -> dict[str, Any]:
    return {"call": call, "args": args}


def rupees(pointer: str) -> dict[str, Any]:
    return fn("formatRupees", value=path(pointer))


# --------------------------------------------------------------------------
# Surface: search results
# --------------------------------------------------------------------------


def listings_surface(
    surface_id: str, listings: list[ListingRead], total: int, mode: Mode | None
) -> dict[str, Any]:
    """A catalogue of search results.

    One CarCard template repeated over the data, not one component per
    listing — which is what makes this a description of the UI rather than a
    serialised rendering of it.
    """
    components = [
        {
            "id": "root",
            "component": "Section",
            "title": f"{total} matching {'listing' if total == 1 else 'listings'}",
            "child": "listing_list",
        },
        {
            "id": "listing_list",
            "component": "List",
            "children": {"path": "/listings", "componentId": "listing_card"},
        },
        {
            "id": "listing_card",
            "component": "CarCard",
            "brand": path("brand"),
            "model": path("model"),
            "year": path("year"),
            "seller": path("seller"),
            "city": path("city"),
            "pricePerDay": path("pricePerDay"),
            "purchasePrice": path("purchasePrice"),
            "action": {
                "event": {
                    "name": "select_listing",
                    "context": {
                        "listingId": path("id"),
                        "label": path("label"),
                    },
                }
            },
        },
    ]

    data = {
        "mode": mode.value if mode else None,
        "listings": [_listing_data(listing) for listing in listings],
    }

    return create_surface(surface_id, components, data)


def _listing_data(listing: ListingRead) -> dict[str, Any]:
    return {
        "id": listing.id,
        "label": f"{listing.year} {listing.brand} {listing.model}",
        "brand": listing.brand,
        "model": listing.model,
        "year": listing.year,
        "seller": listing.seller_name,
        "city": listing.city,
        "pricePerDay": listing.rent_per_day_inr,
        "purchasePrice": listing.price_inr,
    }


# --------------------------------------------------------------------------
# Surface: ranked recommendations
# --------------------------------------------------------------------------


def rankings_surface(
    surface_id: str,
    records: list[ReasoningRecord],
    listings: dict[str, ListingRead],
    weight_source: str,
) -> dict[str, Any]:
    """Ranked recommendations, each carrying its own reasoning.

    The RankedCarCard references a ContributionBar by id as its `working`.
    Both are templates instantiated per item, so the reasoning travels with
    the card it explains rather than being a separate list the user has to
    correlate by hand.
    """
    title = (
        "Ranked using weights inferred from your priorities"
        if weight_source == "inferred"
        else "Ranked using default weights"
    )

    components = [
        {"id": "root", "component": "Section", "title": title, "child": "ranked_list"},
        {
            "id": "ranked_list",
            "component": "List",
            "children": {"path": "/rankings", "componentId": "ranked_card"},
        },
        {
            "id": "ranked_card",
            "component": "RankedCarCard",
            "rank": path("rank"),
            "brand": path("brand"),
            "model": path("model"),
            "year": path("year"),
            "city": path("city"),
            "score": path("score"),
            "pricePerDay": path("pricePerDay"),
            "purchasePrice": path("purchasePrice"),
            "matched": path("matched"),
            "tradeoffs": path("tradeoffs"),
            "working": "ranked_working",
            "action": {
                "event": {
                    "name": "book_listing",
                    "context": {
                        "listingId": path("listingId"),
                        "label": path("label"),
                    },
                }
            },
        },
        {
            "id": "ranked_working",
            "component": "ContributionBar",
            "breakdown": path("breakdown"),
            "weightSource": path("/weightSource"),
        },
    ]

    data = {
        "weightSource": weight_source,
        "rankings": [
            _ranking_data(record, listings.get(record.listing_id))
            for record in records
            if record.listing_id in listings
        ],
    }

    return create_surface(surface_id, components, data)


def _ranking_data(
    record: ReasoningRecord, listing: ListingRead | None
) -> dict[str, Any]:
    assert listing is not None
    return {
        "listingId": record.listing_id,
        "label": f"{listing.year} {listing.brand} {listing.model}",
        "rank": record.rank,
        "brand": listing.brand,
        "model": listing.model,
        "year": listing.year,
        "city": listing.city,
        "score": round(record.total_score, 2),
        "pricePerDay": listing.rent_per_day_inr,
        "purchasePrice": listing.price_inr,
        "matched": record.matched,
        "tradeoffs": record.tradeoffs,
        "breakdown": [
            {
                "criterion": component.criterion,
                "rawScore": round(component.raw_score, 3),
                "weight": round(component.weight, 3),
            }
            for component in record.breakdown
        ],
    }


# --------------------------------------------------------------------------
# Surface: constraint panel (persistent)
# --------------------------------------------------------------------------

CONSTRAINTS_SURFACE = "constraints"


def constraints_surface(state: SessionState) -> dict[str, Any]:
    """Created once per session; refreshed thereafter with data alone."""
    components = [
        {
            "id": "root",
            "component": "ConstraintPanel",
            "phase": path("/phase"),
            "known": path("/known"),
            "missing": path("/missing"),
            "conflicts": path("/conflicts"),
            "shortlistSize": path("/shortlistSize"),
        }
    ]
    return create_surface(
        CONSTRAINTS_SURFACE, components, constraints_data(state)
    )


def constraints_data(state: SessionState) -> dict[str, Any]:
    panel = state.panel()
    return {
        "phase": panel["phase"],
        "known": panel["known"],
        "missing": panel["missing"],
        "conflicts": panel["conflicts"],
        "shortlistSize": panel["shortlist_size"],
    }


def constraints_update(state: SessionState) -> dict[str, Any]:
    """The whole point of the structure/data split: one small message."""
    return update_data_model(CONSTRAINTS_SURFACE, constraints_data(state))


# --------------------------------------------------------------------------
# Surface: research progress
# --------------------------------------------------------------------------

PROGRESS_SURFACE = "progress"


def progress_surface() -> dict[str, Any]:
    components = [
        {
            "id": "root",
            "component": "ProgressTimeline",
            "steps": path("/steps"),
            "remaining": path("/remaining"),
        }
    ]
    return create_surface(PROGRESS_SURFACE, components, {"steps": [], "remaining": None})


def progress_update(
    steps: list[dict[str, str]], remaining: int | None = None
) -> dict[str, Any]:
    return update_data_model(
        PROGRESS_SURFACE, {"steps": steps, "remaining": remaining}
    )


# --------------------------------------------------------------------------
# Surface: conflicts and cost comparison
# --------------------------------------------------------------------------


def conflict_surface(
    surface_id: str, description: str, relaxations: list[str]
) -> dict[str, Any]:
    components = [
        {
            "id": "root",
            "component": "ConflictNotice",
            "description": path("/description"),
            "relaxations": path("/relaxations"),
        }
    ]
    return create_surface(
        surface_id,
        components,
        {"description": description, "relaxations": relaxations},
    )


def tco_surface(surface_id: str, comparison: dict[str, Any]) -> dict[str, Any]:
    components = [
        {
            "id": "root",
            "component": "TcoComparison",
            "durationDays": path("/durationDays"),
            "buyTotal": path("/buyTotal"),
            "rentTotal": path("/rentTotal"),
            "crossoverDays": path("/crossoverDays"),
            "recommendation": path("/recommendation"),
            "assumptions": path("/assumptions"),
        }
    ]
    data = {
        "durationDays": comparison.get("duration_days"),
        "buyTotal": (comparison.get("buy") or {}).get("total_inr"),
        "rentTotal": (comparison.get("rent") or {}).get("total_inr"),
        "crossoverDays": comparison.get("crossover_days"),
        "recommendation": comparison.get("recommendation"),
        "assumptions": comparison.get("assumptions", []),
    }
    return create_surface(surface_id, components, data)
