"""Listing repository — query layer over the inventory.

Serves FR-010 (every filter dimension) and FR-011 (shortlist narrowing).

This module is the only place that knows how a `ListingFilter` becomes SQL.
Callers above it — including the MCP `search_listings` tool and the agent —
work in domain terms and never touch columns directly.

TWO DECISIONS WORTH KNOWING
---------------------------
1. Price bounds are mode-aware. `price_min`/`price_max` apply to the purchase
   price when mode is BUY and to the daily rate when mode is RENT. A caller
   saying "under 3000 a day" should not have to know which column that is.
   With no mode set, the bound matches a listing on either price.

2. Date filtering is interval overlap, not containment. A rental available
   1 Sep - 30 Nov matches a request for 10-15 Oct. Containment would wrongly
   exclude it.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models.listing import (
    Listing,
    ListingFilter,
    ListingPage,
    ListingRead,
    Mode,
)


class ListingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def search(self, spec: ListingFilter) -> ListingPage:
        """Return a page of matching listings plus the total match count.

        `total_matched` is separate from the page size because FR-009 requires
        the agent to report how many candidates remain as it narrows.
        """
        conditions = self._build_conditions(spec)

        total = self._session.scalar(
            select(func.count()).select_from(Listing).where(*conditions)
        )

        stmt: Select = (
            select(Listing)
            .where(*conditions)
            .order_by(*self._ordering(spec))
            .limit(spec.limit)
            .offset(spec.offset)
        )
        rows = self._session.scalars(stmt).all()

        return ListingPage(
            items=[ListingRead.model_validate(row) for row in rows],
            total_matched=total or 0,
            limit=spec.limit,
            offset=spec.offset,
        )

    def get(self, listing_id: str) -> ListingRead | None:
        row = self._session.get(Listing, listing_id)
        return ListingRead.model_validate(row) if row else None

    def get_many(self, listing_ids: Sequence[str]) -> list[ListingRead]:
        """Fetch several listings, preserving the caller's requested order.

        Order preservation matters: `compare_listings` shows columns in the
        order the user named them, not in whatever order the database returns.
        """
        if not listing_ids:
            return []
        rows = self._session.scalars(
            select(Listing).where(Listing.id.in_(listing_ids))
        ).all()
        by_id = {row.id: row for row in rows}
        return [
            ListingRead.model_validate(by_id[listing_id])
            for listing_id in listing_ids
            if listing_id in by_id
        ]

    def count_all(self) -> int:
        return self._session.scalar(select(func.count()).select_from(Listing)) or 0

    def distinct_values(self, column: str) -> list[str]:
        """Distinct values for a categorical column.

        Used to answer "what categories do you have?" without the agent
        hardcoding the taxonomy, and to name a binding constraint when a
        search returns nothing (FR-016).
        """
        allowed = {"category", "brand", "fuel", "transmission", "city", "country"}
        if column not in allowed:
            raise ValueError(f"{column!r} is not a filterable categorical column")
        rows = self._session.scalars(
            select(getattr(Listing, column)).distinct().order_by(getattr(Listing, column))
        ).all()
        return list(rows)

    # ----------------------------------------------------------------
    # Condition building
    # ----------------------------------------------------------------

    def _build_conditions(self, spec: ListingFilter) -> list:
        conditions: list = []

        # --- mode -----------------------------------------------------
        if spec.mode is Mode.BUY:
            conditions.append(Listing.for_sale.is_(True))
        elif spec.mode is Mode.RENT:
            conditions.append(Listing.for_rent.is_(True))

        # --- identity -------------------------------------------------
        if spec.category:
            conditions.append(Listing.category == spec.category)
        if spec.brands:
            conditions.append(Listing.brand.in_(spec.brands))

        # --- price (mode-aware) ---------------------------------------
        conditions.extend(self._price_conditions(spec))

        # --- specification --------------------------------------------
        if spec.year_min is not None:
            conditions.append(Listing.year >= spec.year_min)
        if spec.year_max is not None:
            conditions.append(Listing.year <= spec.year_max)
        if spec.km_max is not None:
            conditions.append(Listing.km <= spec.km_max)
        if spec.fuel:
            conditions.append(Listing.fuel.in_([f.value for f in spec.fuel]))
        if spec.transmission:
            conditions.append(Listing.transmission == spec.transmission.value)
        if spec.seats_min is not None:
            conditions.append(Listing.seats >= spec.seats_min)

        # --- location -------------------------------------------------
        if spec.city:
            conditions.append(Listing.city == spec.city)
        if spec.country:
            conditions.append(Listing.country == spec.country)

        # --- availability ---------------------------------------------
        conditions.extend(self._availability_conditions(spec))

        return conditions

    def _price_conditions(self, spec: ListingFilter) -> list:
        if spec.price_min is None and spec.price_max is None:
            return []

        def bounds(column) -> list:
            checks = []
            if spec.price_min is not None:
                checks.append(column >= spec.price_min)
            if spec.price_max is not None:
                checks.append(column <= spec.price_max)
            return checks

        if spec.mode is Mode.BUY:
            return [Listing.price_inr.is_not(None), *bounds(Listing.price_inr)]

        if spec.mode is Mode.RENT:
            return [
                Listing.rent_per_day_inr.is_not(None),
                *bounds(Listing.rent_per_day_inr),
            ]

        # No mode stated: a listing matches if either of its prices fits.
        sale_ok = [Listing.price_inr.is_not(None), *bounds(Listing.price_inr)]
        rent_ok = [
            Listing.rent_per_day_inr.is_not(None),
            *bounds(Listing.rent_per_day_inr),
        ]
        from sqlalchemy import and_

        return [or_(and_(*sale_ok), and_(*rent_ok))]

    def _availability_conditions(self, spec: ListingFilter) -> list:
        """Interval overlap between the request window and the listing window.

        A listing with no end date (purchase stock) is treated as open-ended.
        """
        conditions: list = []

        if spec.available_from is not None:
            conditions.append(
                or_(
                    Listing.available_to.is_(None),
                    Listing.available_to >= spec.available_from,
                )
            )

        if spec.available_to is not None:
            conditions.append(Listing.available_from <= spec.available_to)

        return conditions

    def _ordering(self, spec: ListingFilter) -> list:
        """Stable, sensible default ordering.

        Ranking is the agent's job (FR-012), not the repository's — this only
        needs to be deterministic so that pagination is coherent and so that
        repeated identical queries return identical pages (FR-027).
        """
        if spec.mode is Mode.RENT:
            return [Listing.rent_per_day_inr.asc(), Listing.id.asc()]
        if spec.mode is Mode.BUY:
            return [Listing.price_inr.asc(), Listing.id.asc()]
        return [Listing.id.asc()]
