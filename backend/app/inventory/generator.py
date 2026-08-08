"""Deterministic mock inventory generator.

Serves FR-026 (catalogue floor), FR-027 (determinism) and FR-028 (dual
buy/rent representation).

DETERMINISM CONTRACT
--------------------
Given the same `seed` and `reference_date`, this module produces
content-identical rows. Two mechanisms make that hold:

1. Iteration order is explicit (sorted keys), never dict insertion order or
   set iteration.
2. Each listing draws from its own RNG stream derived from the seed and the
   listing's stable identity, so adding a category or brand does not shift the
   values generated for any other listing.

Note this is a claim about row content, not about SQLite file bytes — page
allocation and header counters can differ between runs without any row
differing.

`reference_date` defaults to today because availability windows must look
current in a demo. Tests pin it explicitly.

PLAUSIBILITY MODEL
------------------
Price is not drawn independently of the rest of the record:

- Segment band sets the range for the category.
- Model position within the brand's range anchors where in that band the
  vehicle starts. Taxonomy model tuples are ordered entry-first, so a 3 Series
  and a 7 Series draw from different points rather than the same uniform
  distribution.
- Brand tier scales the result, with per-segment overrides because a brand's
  standing is not constant across segments.
- Age depreciates it, and mileage above the age-expected figure penalises it
  further.

KNOWN LIMITATION
----------------
Model launch years are not modelled, so a listing may carry a model year
predating that model's real introduction. Fixing this would require a `since`
field on every catalogue entry; the cost is not judged worth it for mock
inventory. Recorded in docs/architecture.md.
"""

from __future__ import annotations

import argparse
import hashlib
import random
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.inventory import taxonomy as tx
from app.models.listing import Listing
from app.models.registry import Base  # registers every table

# --------------------------------------------------------------------------
# Tuning constants
# --------------------------------------------------------------------------

DEFAULT_SEED = 20260808
CURRENT_MODEL_YEAR = 2026
MAX_AGE_YEARS = 9

# Multiplier applied to the segment base price. Brands that sit above or below
# the middle of their own segment.
BRAND_TIER: dict[str, float] = {
    # premium within any segment they appear in
    "Bentley": 2.10,
    "Porsche": 1.70,
    "Maserati": 1.55,
    "Land Rover": 1.35,
    "BMW": 1.20,
    "Mercedes-Benz": 1.22,
    "Audi": 1.15,
    "Lexus": 1.18,
    "Jaguar": 1.12,
    "Volvo": 1.10,
    "Tesla": 1.25,
    "Genesis": 1.08,
    # value end
    "Maruti Suzuki": 0.86,
    "Renault": 0.88,
    "Nissan": 0.90,
    "Tata": 0.92,
    "Citroen": 0.90,
    "Fiat": 0.88,
    "Force": 0.85,
    "MG": 0.94,
    "BYD": 0.98,
}
DEFAULT_TIER = 1.0

# Per-category overrides. A brand's tier is not constant across segments: a
# Toyota is mid-market among MPVs but sits at the affordable end of the coupe
# segment, where its neighbours are Porsche and Bentley.
CATEGORY_BRAND_TIER: dict[str, dict[str, float]] = {
    "coupe": {
        "Toyota": 0.55,
        "Ford": 0.55,
        "Nissan": 0.60,
        "Jaguar": 0.75,
        "Chevrolet": 0.80,
        "Lexus": 0.95,
    },
    "convertible": {
        "Mazda": 0.45,
        "Mini": 0.45,
        "Ford": 0.55,
        "Jaguar": 0.72,
        "Chevrolet": 0.80,
    },
}

# Where a model sits within its brand's range, entry to flagship.
MODEL_POSITION_MIN = 0.15
MODEL_POSITION_MAX = 0.85

# Annual depreciation applied multiplicatively per year of age.
DEPRECIATION_PER_YEAR = 0.87
# Additional value lost per 10,000 km beyond the age-expected usage.
WEAR_PENALTY_PER_10K = 0.015

# Typical annual usage, by country.
ANNUAL_KM = {"India": 11_000, "Germany": 14_000}

# Share of the catalogue offered new rather than pre-owned.
NEW_SHARE = 0.35

DEALERSHIP_NAMES = (
    "Apex Motors", "Crown Auto", "Meridian Cars", "Northgate Automotive",
    "Silverline Motors", "Vantage Auto Group", "Keystone Cars", "Solstice Motors",
)
RENTAL_PLATFORM_NAMES = (
    "DriveNow", "RoadFleet", "Wanderwheels", "KeyPass Rentals",
    "Openroad Hire", "Milestone Rentals",
)


@dataclass(frozen=True)
class GeneratorConfig:
    seed: int = DEFAULT_SEED
    reference_date: date | None = None
    listings_per_pair_min: int = 1
    listings_per_pair_max: int = 2

    def resolved_reference_date(self) -> date:
        return self.reference_date or date.today()  # noqa: DTZ011 - calendar date, not a timestamp


# --------------------------------------------------------------------------
# Deterministic RNG derivation
# --------------------------------------------------------------------------


def _stream(seed: int, *identity: str | int) -> random.Random:
    """Return an RNG seeded from the global seed plus a stable identity.

    Deriving a per-listing stream means the values for listing X do not depend
    on how many listings were generated before it — so editing the taxonomy
    does not churn the whole catalogue.
    """
    key = f"{seed}:" + ":".join(str(part) for part in identity)
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def _slug(value: str) -> str:
    return "".join(ch.lower() if ch.isalnum() else "-" for ch in value).strip("-")


def _brand_tier(category: str, brand: str) -> float:
    override = CATEGORY_BRAND_TIER.get(category, {}).get(brand)
    if override is not None:
        return override
    return BRAND_TIER.get(brand, DEFAULT_TIER)


def _model_position(index: int, count: int) -> float:
    """Map a model's index in its brand tuple to a position in the segment band.

    Taxonomy model tuples are ordered entry-first, so index carries real
    pricing signal.
    """
    if count <= 1:
        return 0.5
    span = MODEL_POSITION_MAX - MODEL_POSITION_MIN
    return MODEL_POSITION_MIN + span * (index / (count - 1))


# --------------------------------------------------------------------------
# Field derivation
# --------------------------------------------------------------------------


def _pick_year(rng: random.Random, condition: str) -> int:
    if condition == "new":
        return CURRENT_MODEL_YEAR
    # Skew toward more recent used stock — triangular, mode at 2 years old.
    age = int(rng.triangular(1, MAX_AGE_YEARS, 2))
    return CURRENT_MODEL_YEAR - age


def _pick_km(rng: random.Random, age: int, country: str) -> int:
    if age == 0:
        return rng.randint(0, 400)
    base = ANNUAL_KM[country] * age
    # Usage intensity varies; some cars are driven hard, some barely.
    factor = rng.triangular(0.45, 1.75, 1.0)
    return int(round(base * factor, -2))


def _expected_km(age: int, country: str) -> int:
    return ANNUAL_KM[country] * age


def _sale_price_inr(
    rng: random.Random,
    profile: tx.CategoryProfile,
    category: str,
    brand: str,
    model_position: float,
    age: int,
    km: int,
    country: str,
) -> int:
    low, high = profile["price_band_inr"]
    # Anchored by where this model sits in its brand's range, not drawn flat.
    base_new = low + (high - low) * model_position
    base_new *= _brand_tier(category, brand)
    base_new *= rng.uniform(0.93, 1.07)

    value = base_new * (DEPRECIATION_PER_YEAR**age)

    # Penalise usage above what the age alone would predict.
    excess_km = max(0, km - _expected_km(age, country))
    value *= max(0.55, 1.0 - (excess_km / 10_000) * WEAR_PENALTY_PER_10K)

    return int(round(value, -3))


def _rent_per_day_inr(
    rng: random.Random,
    profile: tx.CategoryProfile,
    sale_price: int,
    age: int,
) -> int:
    low, high = profile["rent_band_inr"]
    p_low, p_high = profile["price_band_inr"]

    # Where this car sits in its segment's price range drives where it sits in
    # the segment's rental range.
    span = max(1, p_high - p_low)
    position = min(1.0, max(0.0, (sale_price - p_low) / span))
    rate = low + (high - low) * position

    # Older rental stock is cheaper.
    rate *= max(0.7, 1.0 - age * 0.045)
    rate *= rng.uniform(0.94, 1.08)
    return int(round(rate, -1))


def _to_eur(inr: int | None) -> int | None:
    if inr is None:
        return None
    return round(inr / tx.EUR_TO_INR)


# --------------------------------------------------------------------------
# Listing construction
# --------------------------------------------------------------------------


def _build_listing(
    listing_id: str,
    category: str,
    brand: str,
    model: str,
    cfg: GeneratorConfig,
    model_index: int,
    model_count: int,
) -> Listing:
    profile = tx.CATEGORY_PROFILES[category]
    rng = _stream(cfg.seed, category, brand, model, listing_id)
    ref = cfg.resolved_reference_date()

    country = rng.choice(sorted(tx.CITIES.keys()))
    city = rng.choice(tx.CITIES[country])

    condition = "new" if rng.random() < NEW_SHARE else "used"
    year = _pick_year(rng, condition)
    age = CURRENT_MODEL_YEAR - year
    km = _pick_km(rng, age, country)

    fuel = rng.choice(profile["fuels"])
    transmission = rng.choice(profile["transmissions"])
    seats = rng.choice(profile["seats"])

    sale_price = _sale_price_inr(
        rng,
        profile,
        category,
        brand,
        _model_position(model_index, model_count),
        age,
        km,
        country,
    )

    # Mode availability. Rental-eligible categories put a share of stock into
    # the rental pool; some listings are offered both ways (FR-028).
    if profile["rentable"]:
        roll = rng.random()
        for_rent = roll < 0.55
        for_sale = (not for_rent) or roll > 0.40
    else:
        for_rent = False
        for_sale = True

    rent_rate = _rent_per_day_inr(rng, profile, sale_price, age) if for_rent else None

    if for_rent:
        seller_type = "rental_platform"
        seller_name = rng.choice(RENTAL_PLATFORM_NAMES)
    elif condition == "new":
        seller_type = "dealership"
        seller_name = rng.choice(DEALERSHIP_NAMES)
    else:
        seller_type = "certified_preowned"
        seller_name = rng.choice(DEALERSHIP_NAMES)

    available_from = ref + timedelta(days=rng.randint(0, 21))
    available_to = (
        available_from + timedelta(days=rng.randint(45, 210)) if for_rent else None
    )

    return Listing(
        id=listing_id,
        category=category,
        brand=brand,
        model=model,
        variant=None,
        year=year,
        km=km,
        fuel=fuel,
        transmission=transmission,
        seats=seats,
        condition=condition,
        for_sale=for_sale,
        for_rent=for_rent,
        price_inr=sale_price if for_sale else None,
        price_eur=_to_eur(sale_price) if for_sale else None,
        rent_per_day_inr=rent_rate,
        rent_per_day_eur=_to_eur(rent_rate),
        min_rental_days=rng.choice((1, 1, 2, 3)) if for_rent else None,
        weekly_discount_pct=rng.choice((0, 5, 10, 12)) if for_rent else None,
        city=city,
        country=country,
        seller_type=seller_type,
        seller_name=seller_name,
        available_from=available_from,
        available_to=available_to,
        image_key=f"{category}/{_slug(brand)}-{_slug(model)}",
    )


def generate(cfg: GeneratorConfig | None = None) -> list[Listing]:
    """Produce the full catalogue. Order is stable across runs."""
    cfg = cfg or GeneratorConfig()
    tx.validate_taxonomy()

    listings: list[Listing] = []
    counter = 0

    for category in sorted(tx.CATALOGUE.keys()):
        for brand in sorted(tx.CATALOGUE[category].keys()):
            model_names = tx.CATALOGUE[category][brand]
            count_rng = _stream(cfg.seed, "count", category, brand)
            n = count_rng.randint(cfg.listings_per_pair_min, cfg.listings_per_pair_max)

            for i in range(n):
                index = i % len(model_names)
                model = model_names[index]
                counter += 1
                listing_id = f"lst-{counter:04d}"
                listings.append(
                    _build_listing(
                        listing_id,
                        category,
                        brand,
                        model,
                        cfg,
                        model_index=index,
                        model_count=len(model_names),
                    )
                )

    return listings


# --------------------------------------------------------------------------
# Persistence
# --------------------------------------------------------------------------


def write_db(listings: list[Listing], db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        session.add_all(listings)
        session.commit()


def summarise(listings: list[Listing]) -> str:
    by_category: dict[str, int] = {}
    brands_seen: dict[str, set[str]] = {}
    for listing in listings:
        by_category[listing.category] = by_category.get(listing.category, 0) + 1
        brands_seen.setdefault(listing.category, set()).add(listing.brand)

    lines = [f"{len(listings)} listings across {len(by_category)} categories"]
    for category in sorted(by_category):
        lines.append(
            f"  {category:<16} {by_category[category]:>3} listings, "
            f"{len(brands_seen[category]):>2} brands"
        )
    lines.append(f"  for sale: {sum(1 for x in listings if x.for_sale)}")
    lines.append(f"  for rent: {sum(1 for x in listings if x.for_rent)}")
    lines.append(f"  both:     {sum(1 for x in listings if x.for_sale and x.for_rent)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate mock car inventory")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "data" / "seed" / "marketplace.db",
    )
    parser.add_argument(
        "--reference-date",
        type=date.fromisoformat,
        default=None,
        help="ISO date anchoring availability windows (default: today)",
    )
    args = parser.parse_args()

    cfg = GeneratorConfig(seed=args.seed, reference_date=args.reference_date)
    listings = generate(cfg)
    write_db(listings, args.out)

    print(summarise(listings))
    print(f"\nwritten to {args.out}")


if __name__ == "__main__":
    main()
