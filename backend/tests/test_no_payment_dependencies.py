"""Constitution V — the mock transaction must stay mock.

T018. These tests fail loudly if a payment rail is ever introduced, whether
deliberately or by a transitive dependency.
"""

from __future__ import annotations

import tomllib
from importlib.metadata import distributions
from pathlib import Path

import pytest

from app.mcp_servers.checkout.server import TEST_CARDS, submit_payment

# Real payment processors and card-handling libraries.
FORBIDDEN = {
    "stripe", "braintree", "square", "squareup", "paypalrestsdk", "paypalhttp",
    "razorpay", "payu", "paytm", "adyen", "authorizenet", "mollie-api-python",
    "checkout-sdk", "cybersource-rest-client", "worldpay", "klarna",
    "creditcard", "card-identifier", "luhn", "python-luhn", "pyluhn",
}

_PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_no_payment_library_declared():
    data = tomllib.loads(_PYPROJECT.read_text())
    declared = list(data["project"].get("dependencies", []))
    for group in data.get("dependency-groups", {}).values():
        declared.extend(group)

    names = {
        d.split("[")[0].split(">")[0].split("<")[0].split("=")[0].strip().lower()
        for d in declared
    }
    offenders = names & FORBIDDEN
    assert not offenders, f"payment libraries declared: {offenders}"


def test_no_payment_library_installed():
    installed = {
        (d.metadata["Name"] or "").lower() for d in distributions()
    }
    offenders = installed & FORBIDDEN
    assert not offenders, f"payment libraries present transitively: {offenders}"


def test_every_test_card_is_obviously_synthetic():
    """A repeated-digit or reserved-range number cannot be mistaken for real."""
    for number in TEST_CARDS:
        assert len(number) == 16
        assert number.isdigit()
        distinct = len(set(number))
        starts_reserved = number.startswith(("0000", "4000000000000002"))
        assert distinct <= 2 or starts_reserved, (
            f"{number} is not obviously synthetic"
        )


@pytest.mark.parametrize(
    "card",
    [
        "4111111111111111",  # a widely published Visa test number
        "5500005555555559",
        "378282246310005",
        "6011111111111117",
    ],
)
def test_cards_outside_the_allowlist_are_rejected(card):
    """Including numbers that would pass a Luhn check.

    This is the point of the allowlist: a Luhn-based check would accept these,
    and by extension would accept a genuine card.
    """
    result = submit_payment("bkg-does-not-matter", card)
    assert result.approved is False
    assert result.decline_reason == "not_a_test_card"


def test_rejection_never_reaches_the_database():
    """A rejected card must not touch booking state at all."""
    result = submit_payment("bkg-nonexistent", "4111111111111111")
    assert result.approved is False
    assert result.booking is None
    assert result.reference is None


def test_result_is_always_flagged_as_simulated():
    result = submit_payment("bkg-nonexistent", "0000000000000001")
    assert result.simulated is True
