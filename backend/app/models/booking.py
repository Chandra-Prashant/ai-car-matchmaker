"""Booking domain model.

Serves FR-017 (in-conversation booking) and FR-022 (confirmation record).

Bookings are persisted rather than held in process memory because the booking
server and the checkout server are separate processes: one writes the pending
booking, the other confirms it.

STATUS LIFECYCLE
----------------
    pending    created by the booking form, not yet paid
    confirmed  checkout completed (simulated)
    cancelled  abandoned or explicitly cancelled

No real payment state is ever recorded. See Constitution V.
"""

from __future__ import annotations

import enum
from datetime import UTC, date, datetime

from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.listing import Base


class BookingStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class BookingMode(str, enum.Enum):
    BUY = "buy"
    RENT = "rent"


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[str] = mapped_column(String(24), primary_key=True)
    listing_id: Mapped[str] = mapped_column(String(16), index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    mode: Mapped[str] = mapped_column(String(8))
    status: Mapped[str] = mapped_column(String(16), index=True, default="pending")

    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(32))

    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    pickup_city: Mapped[str | None] = mapped_column(String(48), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(500), nullable=True)

    amount_inr: Mapped[int] = mapped_column(Integer)
    reference: Mapped[str | None] = mapped_column(String(24), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Booking {self.id} {self.listing_id} {self.status}>"


# --------------------------------------------------------------------------
# Schemas
# --------------------------------------------------------------------------


class BookingDraft(BaseModel):
    """Values used to prefill the form (FR-018).

    Every field is optional: the interview may not have captured all of them,
    and every prefilled value stays editable in the UI.
    """

    listing_id: str
    mode: BookingMode
    session_id: str | None = None
    full_name: str | None = None
    email: str | None = None
    phone: str | None = None
    start_date: date | None = None
    end_date: date | None = None
    pickup_city: str | None = None
    amount_inr: int | None = None


class BookingSubmission(BaseModel):
    """Validated form submission (FR-019)."""

    listing_id: str
    mode: BookingMode
    session_id: str | None = None
    full_name: str = Field(min_length=2, max_length=120)
    email: EmailStr
    phone: str = Field(min_length=6, max_length=32)
    start_date: date | None = None
    end_date: date | None = None
    pickup_city: str | None = None
    notes: str | None = Field(default=None, max_length=500)

    @field_validator("phone")
    @classmethod
    def _phone_has_digits(cls, v: str) -> str:
        digits = [c for c in v if c.isdigit()]
        if len(digits) < 6:
            raise ValueError("phone number needs at least 6 digits")
        return v


class BookingRead(BaseModel):
    id: str
    listing_id: str
    mode: BookingMode
    status: BookingStatus
    full_name: str
    email: str
    phone: str
    start_date: date | None
    end_date: date | None
    pickup_city: str | None
    notes: str | None
    amount_inr: int
    reference: str | None
    created_at: datetime
    confirmed_at: datetime | None

    model_config = {"from_attributes": True}
    
    @field_validator("created_at", "confirmed_at")
    @classmethod
    def _assume_utc(cls, v: datetime | None) -> datetime | None:
        """SQLite drops the offset. Timestamps are written in UTC, so
        reattach it rather than emit a naive datetime that fails the
        JSON Schema `date-time` format."""
        if v is not None and v.tzinfo is None:
            return v.replace(tzinfo=UTC)
        return v
