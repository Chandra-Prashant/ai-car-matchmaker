"""Repository tests.

Covers FR-010 (each filter dimension in isolation, then combined) and the two
non-obvious behaviours in the repository: mode-aware price bounds and interval
overlap on dates.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.models.listing import FuelType, ListingFilter, Mode, Transmission

REFERENCE_DATE = date(2026, 8, 8)


# --------------------------------------------------------------------------
# Baseline
# --------------------------------------------------------------------------


def test_empty_filter_matches_everything(repo):
    page = repo.search(ListingFilter())
    assert page.total_matched == repo.count_all()


def test_pagination_reports_total_beyond_the_page(repo):
    page = repo.search(ListingFilter(limit=5))
    assert len(page.items) == 5
    assert page.total_matched > 5


def test_pagination_offsets_do_not_overlap(repo):
    first = repo.search(ListingFilter(limit=5, offset=0))
    second = repo.search(ListingFilter(limit=5, offset=5))
    assert {x.id for x in first.items}.isdisjoint({x.id for x in second.items})


def test_repeated_identical_queries_return_identical_pages(repo):
    spec = ListingFilter(mode=Mode.BUY, limit=10)
    assert [x.id for x in repo.search(spec).items] == [
        x.id for x in repo.search(spec).items
    ]


# --------------------------------------------------------------------------
# Individual dimensions — FR-010
# --------------------------------------------------------------------------


def test_mode_buy_returns_only_sale_listings(repo):
    page = repo.search(ListingFilter(mode=Mode.BUY, limit=100))
    assert page.items
    assert all(x.for_sale for x in page.items)


def test_mode_rent_returns_only_rental_listings(repo):
    page = repo.search(ListingFilter(mode=Mode.RENT, limit=100))
    assert page.items
    assert all(x.for_rent for x in page.items)


def test_category_filter(repo):
    page = repo.search(ListingFilter(category="hatchback", limit=100))
    assert page.items
    assert all(x.category == "hatchback" for x in page.items)


def test_brand_filter_accepts_multiple(repo):
    page = repo.search(ListingFilter(brands=["BMW", "Audi"], limit=100))
    assert page.items
    assert all(x.brand in {"BMW", "Audi"} for x in page.items)


def test_year_bounds(repo):
    page = repo.search(ListingFilter(year_min=2023, year_max=2024, limit=100))
    assert page.items
    assert all(2023 <= x.year <= 2024 for x in page.items)


def test_km_ceiling(repo):
    page = repo.search(ListingFilter(km_max=20_000, limit=100))
    assert page.items
    assert all(x.km <= 20_000 for x in page.items)


def test_fuel_filter_accepts_multiple(repo):
    page = repo.search(
        ListingFilter(fuel=[FuelType.ELECTRIC, FuelType.HYBRID], limit=100)
    )
    assert page.items
    assert all(x.fuel in {FuelType.ELECTRIC, FuelType.HYBRID} for x in page.items)


def test_transmission_filter(repo):
    page = repo.search(ListingFilter(transmission=Transmission.MANUAL, limit=100))
    assert page.items
    assert all(x.transmission is Transmission.MANUAL for x in page.items)


def test_seats_minimum(repo):
    page = repo.search(ListingFilter(seats_min=7, limit=100))
    assert page.items
    assert all(x.seats >= 7 for x in page.items)


def test_country_filter(repo):
    page = repo.search(ListingFilter(country="Germany", limit=100))
    assert page.items
    assert all(x.country == "Germany" for x in page.items)


def test_city_filter(repo):
    page = repo.search(ListingFilter(city="Munich", limit=100))
    assert page.items
    assert all(x.city == "Munich" for x in page.items)


# --------------------------------------------------------------------------
# Mode-aware pricing
# --------------------------------------------------------------------------


def test_buy_price_bounds_apply_to_purchase_price(repo):
    page = repo.search(
        ListingFilter(mode=Mode.BUY, price_min=500_000, price_max=1_500_000, limit=100)
    )
    assert page.items
    assert all(500_000 <= x.price_inr <= 1_500_000 for x in page.items)


def test_rent_price_bounds_apply_to_daily_rate(repo):
    page = repo.search(ListingFilter(mode=Mode.RENT, price_max=3_000, limit=100))
    assert page.items
    assert all(x.rent_per_day_inr <= 3_000 for x in page.items)
    # The same numeric bound must not be read against purchase price.
    assert any(x.price_inr is None or x.price_inr > 3_000 for x in page.items)


def test_rent_bound_does_not_leak_into_buy_results(repo):
    rent = repo.search(ListingFilter(mode=Mode.RENT, price_max=3_000, limit=100))
    buy = repo.search(ListingFilter(mode=Mode.BUY, price_max=3_000, limit=100))
    assert rent.total_matched > 0
    assert buy.total_matched == 0, "no car sells for under 3000 rupees"


def test_modeless_price_bound_matches_either_price(repo):
    page = repo.search(ListingFilter(price_max=3_000, limit=100))
    assert page.items
    assert all(
        (x.price_inr is not None and x.price_inr <= 3_000)
        or (x.rent_per_day_inr is not None and x.rent_per_day_inr <= 3_000)
        for x in page.items
    )


# --------------------------------------------------------------------------
# Availability — interval overlap, not containment
# --------------------------------------------------------------------------


def test_request_window_inside_listing_window_matches(repo):
    listing = next(
        x
        for x in repo.search(ListingFilter(mode=Mode.RENT, limit=100)).items
        if x.available_to is not None
        and (x.available_to - x.available_from) > timedelta(days=30)
    )
    mid = listing.available_from + timedelta(days=10)
    page = repo.search(
        ListingFilter(
            mode=Mode.RENT,
            available_from=mid,
            available_to=mid + timedelta(days=3),
            limit=100,
        )
    )
    assert listing.id in {x.id for x in page.items}


def test_request_window_entirely_before_listing_is_excluded(repo):
    listing = next(
        x
        for x in repo.search(ListingFilter(mode=Mode.RENT, limit=100)).items
        if x.available_from > REFERENCE_DATE
    )
    before = listing.available_from - timedelta(days=10)
    page = repo.search(
        ListingFilter(
            mode=Mode.RENT,
            available_from=before - timedelta(days=5),
            available_to=before,
            limit=100,
        )
    )
    assert listing.id not in {x.id for x in page.items}


def test_purchase_listings_are_open_ended(repo):
    far_future = REFERENCE_DATE + timedelta(days=900)
    page = repo.search(
        ListingFilter(mode=Mode.BUY, available_from=far_future, limit=100)
    )
    assert page.items, "purchase stock has no end date and should still match"


# --------------------------------------------------------------------------
# Combined filters
# --------------------------------------------------------------------------


def test_combined_filters_narrow_results(repo):
    broad = repo.search(ListingFilter(mode=Mode.RENT, limit=100))
    narrow = repo.search(
        ListingFilter(mode=Mode.RENT, seats_min=7, price_max=3_000, limit=100)
    )
    assert narrow.total_matched < broad.total_matched
    assert all(x.seats >= 7 and x.rent_per_day_inr <= 3_000 for x in narrow.items)


def test_unsatisfiable_combination_returns_empty(repo):
    page = repo.search(
        ListingFilter(mode=Mode.BUY, category="hatchback", price_max=50_000)
    )
    assert page.total_matched == 0
    assert page.items == []


# --------------------------------------------------------------------------
# Lookup helpers
# --------------------------------------------------------------------------


def test_get_returns_a_known_listing(repo):
    known = repo.search(ListingFilter(limit=1)).items[0]
    assert repo.get(known.id).id == known.id


def test_get_unknown_returns_none(repo):
    assert repo.get("lst-9999") is None


def test_get_many_preserves_requested_order(repo):
    ids = [x.id for x in repo.search(ListingFilter(limit=4)).items]
    reversed_ids = list(reversed(ids))
    assert [x.id for x in repo.get_many(reversed_ids)] == reversed_ids


def test_get_many_with_empty_input(repo):
    assert repo.get_many([]) == []


def test_distinct_values_returns_sorted_unique(repo):
    categories = repo.distinct_values("category")
    assert categories == sorted(set(categories))
    assert len(categories) >= 10


def test_distinct_values_rejects_unlisted_columns(repo):
    with pytest.raises(ValueError):
        repo.distinct_values("price_inr")
