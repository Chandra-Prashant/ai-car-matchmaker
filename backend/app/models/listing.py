"""Listing domain model — ORM and API schemas.

Serves FR-010 (filter dimensions) and FR-028 (dual buy/rent representation).

A listing may be available for purchase, for rental, or both. Mode is therefore
modelled as two independent flags with independent prices, not as a single
enum — a single enum would require duplicate rows for dual-mode inventory.
"""

from __future__ import annotations

import enum
from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import Boolean, Date, Index, Integer, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------


class Mode(str, enum.Enum):
    BUY = "buy"
    RENT = "rent"


class FuelType(str, enum.Enum):
    PETROL = "petrol"
    DIESEL = "diesel"
    HYBRID = "hybrid"
    ELECTRIC = "electric"
    CNG = "cng"


class Transmission(str, enum.Enum):
    MANUAL = "manual"
    AUTOMATIC = "automatic"


class SellerType(str, enum.Enum):
    DEALERSHIP = "dealership"
    RENTAL_PLATFORM = "rental_platform"
    CERTIFIED_PREOWNED = "certified_preowned"


class Condition(str, enum.Enum):
    NEW = "new"
    USED = "used"


# --------------------------------------------------------------------------
# ORM
# --------------------------------------------------------------------------


class Listing(Base):
    __tablename__ = "listings"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)

    # Identity
    category: Mapped[str] = mapped_column(String(32), index=True)
    brand: Mapped[str] = mapped_column(String(32), index=True)
    model: Mapped[str] = mapped_column(String(64))
    variant: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Specification
    year: Mapped[int] = mapped_column(Integer, index=True)
    km: Mapped[int] = mapped_column(Integer, index=True)
    fuel: Mapped[str] = mapped_column(String(16), index=True)
    transmission: Mapped[str] = mapped_column(String(16), index=True)
    seats: Mapped[int] = mapped_column(Integer, index=True)
    condition: Mapped[str] = mapped_column(String(16))

    # Availability by mode
    for_sale: Mapped[bool] = mapped_column(Boolean, index=True, default=False)
    for_rent: Mapped[bool] = mapped_column(Boolean, index=True, default=False)

    # Pricing — INR is canonical; EUR derived at a declared fixed rate.
    price_inr: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    price_eur: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rent_per_day_inr: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    rent_per_day_eur: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Rental economics
    min_rental_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weekly_discount_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Location and seller
    city: Mapped[str] = mapped_column(String(48), index=True)
    country: Mapped[str] = mapped_column(String(32), index=True)
    seller_type: Mapped[str] = mapped_column(String(24))
    seller_name: Mapped[str] = mapped_column(String(64))

    # Availability window (rentals); purchase listings use available_from only.
    available_from: Mapped[date] = mapped_column(Date, index=True)
    available_to: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)

    # Presentation — a stable key the frontend maps to a placeholder asset.
    image_key: Mapped[str] = mapped_column(String(64))

    __table_args__ = (
        Index("ix_listings_sale_lookup", "for_sale", "category", "price_inr"),
        Index("ix_listings_rent_lookup", "for_rent", "category", "rent_per_day_inr"),
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Listing {self.id} {self.brand} {self.model} ({self.year})>"


# --------------------------------------------------------------------------
# API schemas
# --------------------------------------------------------------------------


class ListingRead(BaseModel):
    id: str
    category: str
    brand: str
    model: str
    variant: str | None
    year: int
    km: int
    fuel: FuelType
    transmission: Transmission
    seats: int
    condition: Condition
    for_sale: bool
    for_rent: bool
    price_inr: int | None
    price_eur: int | None
    rent_per_day_inr: int | None
    rent_per_day_eur: int | None
    min_rental_days: int | None
    weekly_discount_pct: int | None
    city: str
    country: str
    seller_type: SellerType
    seller_name: str
    available_from: date
    available_to: date | None
    image_key: str

    model_config = {"from_attributes": True}


class ListingFilter(BaseModel):
    """Every dimension named in FR-010.

    All fields optional; an empty filter matches the full inventory. Price
    bounds are interpreted against the field appropriate to `mode`, so callers
    never have to know which price column applies.
    """

    mode: Mode | None = None
    category: str | None = None
    brands: list[str] | None = None

    price_min: int | None = Field(default=None, ge=0)
    price_max: int | None = Field(default=None, ge=0)

    year_min: int | None = None
    year_max: int | None = None
    km_max: int | None = Field(default=None, ge=0)

    fuel: list[FuelType] | None = None
    transmission: Transmission | None = None
    seats_min: int | None = Field(default=None, ge=1)

    city: str | None = None
    country: str | None = None

    available_from: date | None = None
    available_to: date | None = None

    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @field_validator("brands", "fuel")
    @classmethod
    def _reject_empty_lists(cls, v: list | None) -> list | None:
        # An empty list would silently match nothing, which is almost never
        # what a caller means. Treat it as "unspecified".
        return v or None

    @model_validator(mode="after")
    def _check_ranges(self) -> ListingFilter:
        if self.price_min is not None and self.price_max is not None:
            if self.price_min > self.price_max:
                raise ValueError("price_min cannot exceed price_max")
        if self.year_min is not None and self.year_max is not None:
            if self.year_min > self.year_max:
                raise ValueError("year_min cannot exceed year_max")
        if self.available_from and self.available_to:
            if self.available_from > self.available_to:
                raise ValueError("available_from cannot be after available_to")
        return self


class ListingPage(BaseModel):
    """Result envelope. `total_matched` is required by FR-009 so the agent can
    report how many candidates remain as it narrows."""

    items: list[ListingRead]
    total_matched: int
    limit: int
    offset: int
