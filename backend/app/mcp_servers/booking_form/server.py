"""Booking form MCP App server.

Serves T012, T013, T014 and FR-017 through FR-019.

This is a real MCP App per SEP-1865 (spec 2026-01-26), not a UI rendered by
the frontend and labelled as one:

- `ui://booking/form` is declared as a resource with mimeType
  `text/html;profile=mcp-app`.
- `open_booking_form` references it through `_meta.ui.resourceUri`.
- The View calls back via `tools/call` on tools marked `visibility: ["app"]`,
  which keeps form plumbing out of the agent's tool list.

Every tool also returns a readable text summary, so a host without MCP Apps
support still gets a usable result (Constitution VII).
"""

from __future__ import annotations

import secrets
from datetime import UTC, date, datetime
from pathlib import Path

from mcp.server import MCPServer
from pydantic import BaseModel, ValidationError

from app.db import session_scope
from app.models.booking import (
    Booking,
    BookingDraft,
    BookingMode,
    BookingRead,
    BookingSubmission,
)
from app.models.listing import Mode
from app.repositories.listing_repository import ListingRepository

UI_URI = "ui://booking/form"
UI_MIME = "text/html;profile=mcp-app"
_UI_PATH = Path(__file__).parent / "ui" / "form.html"

mcp = MCPServer(
    name="booking-form",
    title="Booking Form",
    description="In-conversation booking form for a selected listing",
    version="0.1.0",
    instructions=(
        "Call open_booking_form once the user has chosen a listing. Pass "
        "everything already known from the interview so the form arrives "
        "prefilled. Do not ask the user to retype details you already have."
    ),
)


# --------------------------------------------------------------------------
# UI resource
# --------------------------------------------------------------------------


@mcp.resource(
    UI_URI,
    name="booking_form",
    description="Interactive booking form rendered inside the conversation",
    mime_type=UI_MIME,
    meta={
        "ui": {
            # No external origins needed: the form is self-contained, so the
            # host's restrictive CSP default is exactly right.
            "csp": {
                "connectDomains": [],
                "resourceDomains": [],
                "frameDomains": [],
                "baseUriDomains": [],
            },
            "prefersBorder": True,
        }
    },
)
def booking_form_view() -> str:
    return _UI_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Result models
# --------------------------------------------------------------------------


class OpenFormResult(BaseModel):
    summary: str
    draft: BookingDraft | None = None
    listing_label: str | None = None
    error: str | None = None


class FieldValidationResult(BaseModel):
    summary: str
    field: str
    valid: bool
    message: str | None = None


class SubmitResult(BaseModel):
    summary: str
    booking: BookingRead | None = None
    errors: dict[str, str] = {}


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(6)}"


def _quote(listing, mode: BookingMode, start: date | None, end: date | None) -> int:
    """Amount for the booking. Rentals price by day; purchases by sale price."""
    if mode is BookingMode.BUY:
        return listing.price_inr or 0

    rate = listing.rent_per_day_inr or 0
    if not (start and end):
        return rate * (listing.min_rental_days or 1)

    days = max(1, (end - start).days)
    total = rate * days
    if days >= 7 and listing.weekly_discount_pct:
        total = int(total * (1 - listing.weekly_discount_pct / 100))
    return total


# --------------------------------------------------------------------------
# Model-facing tool
# --------------------------------------------------------------------------


@mcp.tool(
    title="Open booking form",
    description=(
        "Open the booking form inside the conversation for a chosen listing. "
        "Supply every detail already gathered during the interview; all "
        "prefilled values remain editable by the user."
    ),
    meta={"ui": {"resourceUri": UI_URI, "visibility": ["model", "app"]}},
)
def open_booking_form(
    listing_id: str,
    mode: BookingMode,
    session_id: str | None = None,
    full_name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    pickup_city: str | None = None,
) -> OpenFormResult:
    with session_scope() as session:
        listing = ListingRepository(session).get(listing_id)

    if listing is None:
        return OpenFormResult(
            summary=f"No listing with ID {listing_id}; cannot open a form.",
            error="unknown_listing",
        )

    wanted = Mode.BUY if mode is BookingMode.BUY else Mode.RENT
    if (wanted is Mode.BUY and not listing.for_sale) or (
        wanted is Mode.RENT and not listing.for_rent
    ):
        return OpenFormResult(
            summary=f"Listing {listing_id} is not available to {mode.value}.",
            error="mode_unavailable",
        )

    amount = _quote(listing, mode, start_date, end_date)
    label = f"{listing.year} {listing.brand} {listing.model}"

    return OpenFormResult(
        summary=(
            f"Booking form opened for {label} in {listing.city} "
            f"({mode.value}, Rs.{amount:,})."
        ),
        listing_label=label,
        draft=BookingDraft(
            listing_id=listing_id,
            mode=mode,
            session_id=session_id,
            full_name=full_name,
            email=email,
            phone=phone,
            start_date=start_date,
            end_date=end_date,
            pickup_city=pickup_city or listing.city,
            amount_inr=amount,
        ),
    )


# --------------------------------------------------------------------------
# App-only tools — callable by the View, hidden from the agent
# --------------------------------------------------------------------------


@mcp.tool(
    title="Validate a booking field",
    description="Validate a single field as the user types.",
    meta={"ui": {"resourceUri": UI_URI, "visibility": ["app"]}},
)
def validate_booking_field(field: str, value: str) -> FieldValidationResult:
    probe = {
        "listing_id": "lst-0001",
        "mode": "rent",
        "full_name": "Placeholder Name",
        "email": "placeholder@example.com",
        "phone": "0000000000",
        field: value,
    }
    try:
        BookingSubmission.model_validate(probe)
    except ValidationError as exc:
        for err in exc.errors():
            if err["loc"] and err["loc"][0] == field:
                return FieldValidationResult(
                    summary=f"{field} is invalid: {err['msg']}",
                    field=field,
                    valid=False,
                    message=err["msg"],
                )
    return FieldValidationResult(
        summary=f"{field} is valid.", field=field, valid=True
    )


@mcp.tool(
    title="Submit booking",
    description="Submit the completed booking form.",
    meta={"ui": {"resourceUri": UI_URI, "visibility": ["app"]}},
)
def submit_booking(
    listing_id: str,
    mode: BookingMode,
    full_name: str,
    email: str,
    phone: str,
    session_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    pickup_city: str | None = None,
    notes: str | None = None,
) -> SubmitResult:
    try:
        submission = BookingSubmission(
            listing_id=listing_id,
            mode=mode,
            session_id=session_id,
            full_name=full_name,
            email=email,
            phone=phone,
            start_date=start_date,
            end_date=end_date,
            pickup_city=pickup_city,
            notes=notes,
        )
    except ValidationError as exc:
        errors = {
            str(err["loc"][0]): err["msg"] for err in exc.errors() if err["loc"]
        }
        return SubmitResult(
            summary="The form has validation errors: "
            + "; ".join(f"{k} — {v}" for k, v in errors.items()),
            errors=errors,
        )

    with session_scope() as session:
        listing = ListingRepository(session).get(listing_id)
        if listing is None:
            return SubmitResult(
                summary=f"No listing with ID {listing_id}.",
                errors={"listing_id": "unknown listing"},
            )

        amount = _quote(listing, mode, submission.start_date, submission.end_date)
        booking = Booking(
            id=_new_id("bkg"),
            listing_id=listing_id,
            session_id=submission.session_id,
            mode=mode.value,
            status="pending",
            full_name=submission.full_name,
            email=str(submission.email),
            phone=submission.phone,
            start_date=submission.start_date,
            end_date=submission.end_date,
            pickup_city=submission.pickup_city,
            notes=submission.notes,
            amount_inr=amount,
            created_at=datetime.now(UTC),
        )
        session.add(booking)
        session.flush()
        record = BookingRead.model_validate(booking)
        label = f"{listing.year} {listing.brand} {listing.model}"

    return SubmitResult(
        summary=(
            f"Booking {record.id} created for {label} — Rs.{amount:,}, "
            f"awaiting payment."
        ),
        booking=record,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
