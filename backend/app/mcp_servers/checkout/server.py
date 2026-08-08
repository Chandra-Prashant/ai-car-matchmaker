"""Checkout MCP App server — simulated payment only.

Serves T015, T016, T017 and FR-020 through FR-022.

SAFETY (Constitution V)
-----------------------
There is no payment rail here and no payment library anywhere in this
project's dependency tree — `tests/test_no_payment_dependencies.py` asserts
that. The card field accepts an explicit allowlist of obviously-fake numbers
and nothing else.

Luhn validation is deliberately NOT implemented. A Luhn check would accept a
real card number, which is precisely the outcome to avoid. Rejecting
everything outside the allowlist is both simpler and safer.
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime
from pathlib import Path

from mcp.server import MCPServer
from pydantic import BaseModel

from app.db import session_scope
from app.models.booking import Booking, BookingRead
from app.repositories.listing_repository import ListingRepository

UI_URI = "ui://checkout/payment"
UI_MIME = "text/html;profile=mcp-app"
_UI_PATH = Path(__file__).parent / "ui" / "payment.html"

# Obviously-synthetic numbers. Anything else is rejected outright.
TEST_CARDS: dict[str, str] = {
    "0000000000000001": "approved",
    "1111111111111111": "approved",
    "4000000000000002": "declined",
    "9999999999999999": "insufficient_funds",
}

DECLINE_MESSAGES = {
    "declined": "Simulated decline — the test card is configured to fail.",
    "insufficient_funds": "Simulated insufficient funds on the test card.",
}

mcp = MCPServer(
    name="checkout",
    title="Checkout (Simulated)",
    description="Mock payment interface — no real transactions occur",
    version="0.1.0",
    instructions=(
        "Call open_checkout after a booking has been created. This checkout "
        "is entirely simulated: tell the user plainly that no real payment is "
        "taken and never ask them for genuine card details."
    ),
)


@mcp.resource(
    UI_URI,
    name="checkout_payment",
    description="Simulated payment interface rendered inside the conversation",
    mime_type=UI_MIME,
    meta={
        "ui": {
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
def checkout_view() -> str:
    return _UI_PATH.read_text(encoding="utf-8")


# --------------------------------------------------------------------------
# Result models
# --------------------------------------------------------------------------


class CheckoutDraft(BaseModel):
    booking_id: str
    listing_label: str
    mode: str
    amount_inr: int
    full_name: str
    email: str
    line_items: list[dict[str, str]]
    test_cards: list[dict[str, str]]


class OpenCheckoutResult(BaseModel):
    summary: str
    draft: CheckoutDraft | None = None
    error: str | None = None


class PaymentResult(BaseModel):
    summary: str
    approved: bool
    reference: str | None = None
    decline_reason: str | None = None
    booking: BookingRead | None = None
    simulated: bool = True


# --------------------------------------------------------------------------
# Model-facing tool
# --------------------------------------------------------------------------


@mcp.tool(
    title="Open checkout",
    description=(
        "Open the simulated checkout for an existing booking. No real payment "
        "is processed and no genuine card details are ever collected."
    ),
    meta={"ui": {"resourceUri": UI_URI, "visibility": ["model", "app"]}},
)
def open_checkout(booking_id: str) -> OpenCheckoutResult:
    with session_scope() as session:
        booking = session.get(Booking, booking_id)
        if booking is None:
            return OpenCheckoutResult(
                summary=f"No booking with ID {booking_id}.",
                error="unknown_booking",
            )
        if booking.status == "confirmed":
            return OpenCheckoutResult(
                summary=(
                    f"Booking {booking_id} is already confirmed "
                    f"(reference {booking.reference})."
                ),
                error="already_confirmed",
            )
        if booking.status == "cancelled":
            return OpenCheckoutResult(
                summary=f"Booking {booking_id} was cancelled.",
                error="cancelled",
            )

        listing = ListingRepository(session).get(booking.listing_id)
        label = (
            f"{listing.year} {listing.brand} {listing.model}"
            if listing
            else booking.listing_id
        )

        line_items = [{"label": label, "value": f"Rs.{booking.amount_inr:,}"}]
        if booking.mode == "rent" and booking.start_date and booking.end_date:
            days = max(1, (booking.end_date - booking.start_date).days)
            line_items.append(
                {
                    "label": "Rental period",
                    "value": f"{booking.start_date} to {booking.end_date} ({days} days)",
                }
            )
        if booking.pickup_city:
            line_items.append({"label": "Pickup", "value": booking.pickup_city})

        draft = CheckoutDraft(
            booking_id=booking.id,
            listing_label=label,
            mode=booking.mode,
            amount_inr=booking.amount_inr,
            full_name=booking.full_name,
            email=booking.email,
            line_items=line_items,
            test_cards=[
                {"number": number, "outcome": outcome}
                for number, outcome in TEST_CARDS.items()
            ],
        )

    return OpenCheckoutResult(
        summary=(
            f"Simulated checkout opened for booking {booking_id} — "
            f"{label}, Rs.{draft.amount_inr:,}. No real payment will be taken."
        ),
        draft=draft,
    )


# --------------------------------------------------------------------------
# App-only tool
# --------------------------------------------------------------------------


@mcp.tool(
    title="Submit simulated payment",
    description="Process the mock payment for a booking.",
    meta={"ui": {"resourceUri": UI_URI, "visibility": ["app"]}},
)
def submit_payment(booking_id: str, card_number: str) -> PaymentResult:
    digits = "".join(c for c in card_number if c.isdigit())

    outcome = TEST_CARDS.get(digits)
    if outcome is None:
        # Deliberately no Luhn check: accepting a structurally valid card
        # would mean accepting a real one.
        return PaymentResult(
            summary=(
                "Rejected: this checkout is a simulation and accepts only its "
                "listed test card numbers. Never enter a real card here."
            ),
            approved=False,
            decline_reason="not_a_test_card",
        )

    if outcome != "approved":
        return PaymentResult(
            summary=DECLINE_MESSAGES[outcome],
            approved=False,
            decline_reason=outcome,
        )

    with session_scope() as session:
        booking = session.get(Booking, booking_id)
        if booking is None:
            return PaymentResult(
                summary=f"No booking with ID {booking_id}.",
                approved=False,
                decline_reason="unknown_booking",
            )
        if booking.status == "confirmed":
            return PaymentResult(
                summary=f"Already confirmed (reference {booking.reference}).",
                approved=True,
                reference=booking.reference,
                booking=BookingRead.model_validate(booking),
            )

        booking.status = "confirmed"
        booking.reference = f"SIM-{secrets.token_hex(4).upper()}"
        booking.confirmed_at = datetime.now(UTC)
        session.flush()
        record = BookingRead.model_validate(booking)

    return PaymentResult(
        summary=(
            f"Simulated payment approved. Reference {record.reference} for "
            f"booking {record.id}, Rs.{record.amount_inr:,}. "
            f"No real transaction took place."
        ),
        approved=True,
        reference=record.reference,
        booking=record,
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
