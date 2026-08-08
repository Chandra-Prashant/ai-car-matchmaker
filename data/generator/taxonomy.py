"""Category and brand taxonomy — reference data for inventory generation.

Serves FR-026: at least 10 categories with at least 10 brands in each.
This file provides 12 categories x 10 brands = 120 category-brand pairs.

Versioned deliberately as data, not as inline constants in the generator, so
that the taxonomy can change without touching generation logic and so that
diffs to the catalogue are legible in review.

CURRENCY NOTE
-------------
INR is the canonical price. EUR is derived at a single declared rate below.
Real Indian and European prices for the same vehicle diverge for tax and
market reasons this project does not model; a fixed rate is a stated
simplification, not an oversight.
"""

from __future__ import annotations

from typing import TypedDict

TAXONOMY_VERSION = "1.0.0"

# 1 EUR expressed in INR. Declared, not fetched — determinism (FR-027)
# matters more here than accuracy.
EUR_TO_INR = 95


class CategoryProfile(TypedDict):
    """Generation envelope for a category.

    price_band_inr    plausible on-road purchase price range, new
    rent_band_inr     plausible per-day rental range
    seats             seat counts that occur in this category
    fuels             fuel types plausible for this category
    transmissions     gearbox types plausible for this category
    rentable          whether rental inventory exists in this category
    """

    price_band_inr: tuple[int, int]
    rent_band_inr: tuple[int, int]
    seats: tuple[int, ...]
    fuels: tuple[str, ...]
    transmissions: tuple[str, ...]
    rentable: bool


CATEGORY_PROFILES: dict[str, CategoryProfile] = {
    "hatchback": {
        "price_band_inr": (450_000, 1_100_000),
        "rent_band_inr": (1_200, 2_600),
        "seats": (4, 5),
        "fuels": ("petrol", "diesel", "cng"),
        "transmissions": ("manual", "automatic"),
        "rentable": True,
    },
    "sedan": {
        "price_band_inr": (800_000, 2_200_000),
        "rent_band_inr": (1_800, 4_000),
        "seats": (5,),
        "fuels": ("petrol", "diesel", "hybrid", "cng"),
        "transmissions": ("manual", "automatic"),
        "rentable": True,
    },
    "compact_suv": {
        "price_band_inr": (900_000, 2_000_000),
        "rent_band_inr": (2_000, 4_500),
        "seats": (5,),
        "fuels": ("petrol", "diesel", "hybrid"),
        "transmissions": ("manual", "automatic"),
        "rentable": True,
    },
    "full_size_suv": {
        "price_band_inr": (1_600_000, 4_500_000),
        "rent_band_inr": (3_500, 8_000),
        "seats": (5, 7),
        "fuels": ("diesel", "petrol", "hybrid"),
        "transmissions": ("manual", "automatic"),
        "rentable": True,
    },
    "mpv": {
        "price_band_inr": (900_000, 2_800_000),
        "rent_band_inr": (2_400, 5_500),
        "seats": (6, 7, 8),
        "fuels": ("petrol", "diesel", "hybrid", "cng"),
        "transmissions": ("manual", "automatic"),
        "rentable": True,
    },
    "luxury_sedan": {
        "price_band_inr": (4_500_000, 15_000_000),
        "rent_band_inr": (9_000, 25_000),
        "seats": (4, 5),
        "fuels": ("petrol", "diesel", "hybrid", "electric"),
        "transmissions": ("automatic",),
        "rentable": True,
    },
    "luxury_suv": {
        "price_band_inr": (6_000_000, 22_000_000),
        "rent_band_inr": (12_000, 35_000),
        "seats": (5, 7),
        "fuels": ("petrol", "diesel", "hybrid", "electric"),
        "transmissions": ("automatic",),
        "rentable": True,
    },
    "electric": {
        "price_band_inr": (1_000_000, 7_000_000),
        "rent_band_inr": (2_500, 9_000),
        "seats": (4, 5, 7),
        "fuels": ("electric",),
        "transmissions": ("automatic",),
        "rentable": True,
    },
    "coupe": {
        "price_band_inr": (3_500_000, 18_000_000),
        "rent_band_inr": (10_000, 30_000),
        "seats": (2, 4),
        "fuels": ("petrol", "hybrid", "electric"),
        "transmissions": ("automatic", "manual"),
        "rentable": True,
    },
    "convertible": {
        "price_band_inr": (4_000_000, 25_000_000),
        "rent_band_inr": (14_000, 40_000),
        "seats": (2, 4),
        "fuels": ("petrol", "hybrid"),
        "transmissions": ("automatic", "manual"),
        "rentable": True,
    },
    "pickup": {
        "price_band_inr": (1_400_000, 4_000_000),
        "rent_band_inr": (3_000, 7_500),
        "seats": (2, 5),
        "fuels": ("diesel", "petrol"),
        "transmissions": ("manual", "automatic"),
        "rentable": False,
    },
    "van": {
        "price_band_inr": (700_000, 5_500_000),
        "rent_band_inr": (2_200, 9_000),
        "seats": (7, 9, 12),
        "fuels": ("diesel", "petrol", "cng", "electric"),
        "transmissions": ("manual", "automatic"),
        "rentable": True,
    },
}


# Ten brands per category, each with representative models.
# Model names are illustrative of the segment; this is mock inventory.
CATALOGUE: dict[str, dict[str, tuple[str, ...]]] = {
    "hatchback": {
        "Maruti Suzuki": ("Swift", "Baleno", "Ignis"),
        "Hyundai": ("i20", "Grand i10 Nios"),
        "Tata": ("Altroz", "Tiago"),
        "Toyota": ("Glanza", "Yaris"),
        "Honda": ("Jazz", "Brio"),
        "Volkswagen": ("Polo", "Golf"),
        "Renault": ("Kwid", "Clio"),
        "Citroen": ("C3", "C4 Cactus"),
        "Skoda": ("Fabia", "Scala"),
        "MG": ("Comet", "3"),
    },
    "sedan": {
        "Honda": ("City", "Amaze"),
        "Hyundai": ("Verna", "Elantra"),
        "Maruti Suzuki": ("Ciaz", "Dzire"),
        "Skoda": ("Slavia", "Octavia"),
        "Volkswagen": ("Virtus", "Passat"),
        "Toyota": ("Camry", "Corolla Altis"),
        "Tata": ("Tigor",),
        "Nissan": ("Sunny", "Altima"),
        "Kia": ("K5", "Forte"),
        "MG": ("5",),
    },
    "compact_suv": {
        "Tata": ("Nexon", "Punch"),
        "Hyundai": ("Creta", "Venue"),
        "Kia": ("Seltos", "Sonet"),
        "Maruti Suzuki": ("Brezza", "Grand Vitara"),
        "Mahindra": ("XUV300", "Bolero Neo"),
        "Toyota": ("Urban Cruiser", "Corolla Cross"),
        "Honda": ("Elevate", "WR-V"),
        "Nissan": ("Magnite", "Kicks"),
        "Renault": ("Kiger", "Captur"),
        "Volkswagen": ("Taigun", "T-Cross"),
    },
    "full_size_suv": {
        "Mahindra": ("XUV700", "Scorpio N"),
        "Toyota": ("Fortuner", "Land Cruiser Prado"),
        "MG": ("Gloster", "Hector Plus"),
        "Jeep": ("Meridian", "Grand Cherokee"),
        "Ford": ("Endeavour", "Explorer"),
        "Isuzu": ("MU-X",),
        "Hyundai": ("Tucson", "Santa Fe"),
        "Kia": ("Carnival", "Sorento"),
        "Skoda": ("Kodiaq",),
        "Volkswagen": ("Tiguan", "Touareg"),
    },
    "mpv": {
        "Maruti Suzuki": ("Ertiga", "XL6", "Invicto"),
        "Toyota": ("Innova Crysta", "Innova Hycross", "Rumion"),
        "Kia": ("Carens",),
        "Renault": ("Triber", "Espace"),
        "Mahindra": ("Marazzo",),
        "Nissan": ("Serena",),
        "Honda": ("Freed", "Odyssey"),
        "Hyundai": ("Stargazer", "Custo"),
        "Citroen": ("C8", "Berlingo"),
        "MG": ("M9",),
    },
    "luxury_sedan": {
        "BMW": ("3 Series", "5 Series", "7 Series"),
        "Mercedes-Benz": ("C-Class", "E-Class", "S-Class"),
        "Audi": ("A4", "A6", "A8 L"),
        "Volvo": ("S60", "S90"),
        "Jaguar": ("XF", "XE"),
        "Lexus": ("ES", "LS"),
        "Porsche": ("Panamera", "Taycan"),
        "Genesis": ("G70", "G80"),
        "Maserati": ("Ghibli", "Quattroporte"),
        "Tesla": ("Model 3", "Model S"),
    },
    "luxury_suv": {
        "BMW": ("X1", "X3", "X5", "X7"),
        "Mercedes-Benz": ("GLA", "GLC", "GLE", "GLS"),
        "Audi": ("Q3", "Q5", "Q7", "Q8"),
        "Volvo": ("XC40", "XC60", "XC90"),
        "Land Rover": ("Discovery Sport", "Range Rover Velar", "Defender"),
        "Porsche": ("Macan", "Cayenne"),
        "Lexus": ("NX", "RX"),
        "Jaguar": ("F-Pace",),
        "Maserati": ("Grecale", "Levante"),
        "Bentley": ("Bentayga",),
    },
    "electric": {
        "Tata": ("Nexon EV", "Tiago EV", "Curvv EV"),
        "MG": ("ZS EV", "Windsor EV", "Comet EV"),
        "Hyundai": ("Ioniq 5", "Kona Electric"),
        "Kia": ("EV6", "EV9"),
        "BYD": ("Atto 3", "Seal", "e6"),
        "Tesla": ("Model 3", "Model Y"),
        "BMW": ("i4", "iX1", "iX"),
        "Mercedes-Benz": ("EQB", "EQE", "EQS"),
        "Volvo": ("EX40", "EX90"),
        "Mahindra": ("XUV400 EV", "BE 6"),
    },
    "coupe": {
        "BMW": ("4 Series", "8 Series", "M4"),
        "Mercedes-Benz": ("CLE", "AMG GT"),
        "Audi": ("A5", "RS5"),
        "Porsche": ("718 Cayman", "911 Carrera"),
        "Ford": ("Mustang",),
        "Chevrolet": ("Camaro", "Corvette"),
        "Nissan": ("Z", "GT-R"),
        "Toyota": ("GR Supra", "GR86"),
        "Lexus": ("RC", "LC"),
        "Jaguar": ("F-Type",),
    },
    "convertible": {
        "BMW": ("4 Series Convertible", "Z4"),
        "Mercedes-Benz": ("C-Class Cabriolet", "SL"),
        "Audi": ("A5 Cabriolet", "TT Roadster"),
        "Porsche": ("911 Cabriolet", "718 Boxster"),
        "Mini": ("Cooper Convertible",),
        "Mazda": ("MX-5",),
        "Jaguar": ("F-Type Convertible",),
        "Chevrolet": ("Corvette Convertible",),
        "Ford": ("Mustang Convertible",),
        "Bentley": ("Continental GTC",),
    },
    "pickup": {
        "Toyota": ("Hilux",),
        "Isuzu": ("D-Max V-Cross",),
        "Ford": ("Ranger", "F-150"),
        "Nissan": ("Navara",),
        "Mahindra": ("Scorpio Getaway", "Bolero Pik-Up"),
        "Volkswagen": ("Amarok",),
        "Mitsubishi": ("L200 Triton",),
        "RAM": ("1500",),
        "Chevrolet": ("Colorado",),
        "Jeep": ("Gladiator",),
    },
    "van": {
        "Force": ("Traveller", "Urbania"),
        "Maruti Suzuki": ("Eeco",),
        "Toyota": ("HiAce", "Proace"),
        "Mercedes-Benz": ("Sprinter", "V-Class"),
        "Volkswagen": ("Transporter", "ID. Buzz"),
        "Ford": ("Transit", "Tourneo"),
        "Renault": ("Trafic", "Master"),
        "Citroen": ("SpaceTourer", "Jumpy"),
        "Peugeot": ("Traveller", "Expert"),
        "Fiat": ("Ducato", "Scudo"),
    },
}


CITIES: dict[str, tuple[str, ...]] = {
    "India": ("Delhi NCR", "Mumbai", "Bengaluru", "Pune", "Hyderabad", "Chennai", "Jaipur"),
    "Germany": ("Munich", "Berlin", "Hamburg", "Frankfurt", "Stuttgart", "Cologne"),
}


def categories() -> list[str]:
    return list(CATALOGUE.keys())


def brands(category: str) -> list[str]:
    return list(CATALOGUE[category].keys())


def models(category: str, brand: str) -> tuple[str, ...]:
    return CATALOGUE[category][brand]


def validate_taxonomy() -> None:
    """Assert the FR-026 floor and internal consistency.

    Called by the generator and by tests so a bad edit to this file fails
    loudly rather than producing quietly malformed inventory.
    """
    assert len(CATALOGUE) >= 10, "FR-026 requires at least 10 categories"
    assert set(CATALOGUE) == set(CATEGORY_PROFILES), (
        "every category must have both a catalogue entry and a generation profile"
    )
    for category, brand_map in CATALOGUE.items():
        assert len(brand_map) >= 10, f"{category}: FR-026 requires at least 10 brands"
        for brand, model_names in brand_map.items():
            assert model_names, f"{category}/{brand}: at least one model required"
