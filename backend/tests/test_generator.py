"""Generator and taxonomy tests.

Covers FR-026 (catalogue floor), FR-027 (determinism) and FR-028 (dual
buy/rent representation), plus the plausibility invariants that keep the mock
inventory from looking obviously synthetic.
"""

from __future__ import annotations

from datetime import date

import pytest

from app.inventory import taxonomy as tx
from app.inventory.generator import (
    CURRENT_MODEL_YEAR,
    GeneratorConfig,
    _model_position,
    generate,
)

REFERENCE_DATE = date(2026, 8, 8)


def _fingerprint(listings) -> list[tuple]:
    """Comparable representation of a whole catalogue."""
    return [
        (
            listing.id,
            listing.category,
            listing.brand,
            listing.model,
            listing.year,
            listing.km,
            listing.fuel,
            listing.transmission,
            listing.seats,
            listing.for_sale,
            listing.for_rent,
            listing.price_inr,
            listing.rent_per_day_inr,
            listing.city,
            listing.available_from,
            listing.available_to,
        )
        for listing in listings
    ]


# --------------------------------------------------------------------------
# Taxonomy — FR-026
# --------------------------------------------------------------------------


def test_taxonomy_self_validates():
    tx.validate_taxonomy()


def test_at_least_ten_categories():
    assert len(tx.CATALOGUE) >= 10


def test_at_least_ten_brands_per_category():
    for category, brands in tx.CATALOGUE.items():
        assert len(brands) >= 10, f"{category} has only {len(brands)} brands"


def test_every_category_has_a_generation_profile():
    assert set(tx.CATALOGUE) == set(tx.CATEGORY_PROFILES)


def test_price_bands_are_ordered():
    for category, profile in tx.CATEGORY_PROFILES.items():
        low, high = profile["price_band_inr"]
        assert low < high, f"{category} price band is inverted"
        rent_low, rent_high = profile["rent_band_inr"]
        assert rent_low < rent_high, f"{category} rent band is inverted"


# --------------------------------------------------------------------------
# Determinism — FR-027
# --------------------------------------------------------------------------


def test_two_runs_produce_identical_rows():
    cfg = GeneratorConfig(seed=20260808, reference_date=REFERENCE_DATE)
    assert _fingerprint(generate(cfg)) == _fingerprint(generate(cfg))


def test_different_seeds_produce_different_catalogues():
    a = generate(GeneratorConfig(seed=1, reference_date=REFERENCE_DATE))
    b = generate(GeneratorConfig(seed=2, reference_date=REFERENCE_DATE))
    assert _fingerprint(a) != _fingerprint(b)


def test_listing_ids_are_unique():
    listings = generate(GeneratorConfig(reference_date=REFERENCE_DATE))
    ids = [listing.id for listing in listings]
    assert len(ids) == len(set(ids))


# --------------------------------------------------------------------------
# Coverage — FR-026 as realised in generated output
# --------------------------------------------------------------------------


def test_generated_inventory_meets_the_floor(listings):
    assert len(listings) >= 100


def test_every_category_appears_in_output(listings):
    produced = {listing.category for listing in listings}
    assert produced == set(tx.CATALOGUE)


def test_every_brand_appears_in_its_category(listings):
    seen: dict[str, set[str]] = {}
    for listing in listings:
        seen.setdefault(listing.category, set()).add(listing.brand)
    for category, brands in tx.CATALOGUE.items():
        assert seen[category] == set(brands), f"{category} is missing brands"


# --------------------------------------------------------------------------
# Mode representation — FR-028
# --------------------------------------------------------------------------


def test_every_listing_is_available_in_at_least_one_mode(listings):
    assert all(listing.for_sale or listing.for_rent for listing in listings)


def test_some_listings_are_available_in_both_modes(listings):
    both = [x for x in listings if x.for_sale and x.for_rent]
    assert both, "FR-028 expects dual-mode inventory to exist"


def test_sale_price_present_exactly_when_for_sale(listings):
    for listing in listings:
        assert (listing.price_inr is not None) == listing.for_sale


def test_rent_price_present_exactly_when_for_rent(listings):
    for listing in listings:
        assert (listing.rent_per_day_inr is not None) == listing.for_rent


def test_non_rentable_categories_produce_no_rental_stock(listings):
    non_rentable = {
        name for name, p in tx.CATEGORY_PROFILES.items() if not p["rentable"]
    }
    for listing in listings:
        if listing.category in non_rentable:
            assert not listing.for_rent


# --------------------------------------------------------------------------
# Plausibility invariants
# --------------------------------------------------------------------------


def test_years_are_within_range(listings):
    for listing in listings:
        assert 2017 <= listing.year <= CURRENT_MODEL_YEAR


def test_new_cars_are_current_year_with_minimal_mileage(listings):
    for listing in listings:
        if listing.condition == "new":
            assert listing.year == CURRENT_MODEL_YEAR
            assert listing.km < 500


def test_prices_are_positive(listings):
    for listing in listings:
        if listing.price_inr is not None:
            assert listing.price_inr > 0
        if listing.rent_per_day_inr is not None:
            assert listing.rent_per_day_inr > 0


def test_currency_conversion_is_consistent(listings):
    for listing in listings:
        if listing.price_inr is not None:
            assert listing.price_eur == round(listing.price_inr / tx.EUR_TO_INR)
        if listing.rent_per_day_inr is not None:
            assert listing.rent_per_day_eur == round(
                listing.rent_per_day_inr / tx.EUR_TO_INR
            )


def test_seats_and_fuel_respect_category_profile(listings):
    for listing in listings:
        profile = tx.CATEGORY_PROFILES[listing.category]
        assert listing.seats in profile["seats"]
        assert listing.fuel in profile["fuels"]
        assert listing.transmission in profile["transmissions"]


def test_rental_windows_are_ordered(listings):
    for listing in listings:
        if listing.available_to is not None:
            assert listing.available_from < listing.available_to


def test_older_cars_have_more_mileage_on_average(listings):
    """Not a per-listing rule — usage varies — but the trend must hold."""
    recent = [x.km for x in listings if CURRENT_MODEL_YEAR - x.year <= 2 and x.km > 500]
    old = [x.km for x in listings if CURRENT_MODEL_YEAR - x.year >= 6]
    assert recent and old
    assert sum(old) / len(old) > sum(recent) / len(recent)


@pytest.mark.parametrize(
    "index,count,expected_order",
    [(0, 3, "lowest"), (1, 3, "middle"), (2, 3, "highest")],
)
def test_model_position_increases_with_index(index, count, expected_order):
    positions = [_model_position(i, count) for i in range(count)]
    assert positions == sorted(positions)
    assert positions[0] < positions[-1]


def test_single_model_brands_sit_mid_band():
    assert _model_position(0, 1) == 0.5


def test_flagship_models_outprice_entry_models(listings):
    """Within a brand and category, the last-listed model should generally
    cost more than the first. Checked in aggregate, since age and mileage
    legitimately disturb individual pairs."""
    wins = 0
    comparisons = 0
    for category, brand_map in tx.CATALOGUE.items():
        for brand, model_names in brand_map.items():
            if len(model_names) < 2:
                continue
            entry = [
                x.price_inr
                for x in listings
                if x.category == category
                and x.brand == brand
                and x.model == model_names[0]
                and x.price_inr
            ]
            flagship = [
                x.price_inr
                for x in listings
                if x.category == category
                and x.brand == brand
                and x.model == model_names[-1]
                and x.price_inr
            ]
            if not entry or not flagship:
                continue
            comparisons += 1
            if max(flagship) > max(entry):
                wins += 1

    assert comparisons > 0
    assert wins / comparisons > 0.7, (
        f"flagship priced above entry in only {wins}/{comparisons} brand ranges"
    )
