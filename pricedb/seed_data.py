"""Initial materials data (epic 5.2).

Work codes/names come from core.reference.WORK_TYPES (7 fixed codes) — do not
invent new work codes here. Every work is measured in m2, so quantity_per_unit
means "material per 1 m2 of work". Each work has a full bill of materials, and
every material it needs is in the MATERIALS/PRICES tables below.

Prices: UAH per the material's own unit. Two confirmed on Epicentr (2026-10-16);
the rest are market estimates to verify before the defense.
"""
from datetime import date

PRICE_DATE = date(2026, 10, 16)
DEFAULT_SOURCE = "market estimate (verify)"

# material name -> unit
MATERIALS: dict[str, str] = {
    # facade
    "Plaster mix": "kg",
    "Primer": "l",
    "Reinforcing mesh": "m2",
    "Plaster corner bead": "m",
    "Brick": "pcs",
    "Masonry mortar": "kg",
    "Facade paint": "l",
    "Facade putty": "kg",
    # windows
    "Window glass unit": "m2",
    "Window frame": "m2",
    "Glazing bead": "m",
    "Silicone sealant": "pcs",
    "Mounting foam": "pcs",
    "Window sill": "m",
    # roof
    "Metal roof sheet": "m2",
    "Roofing screw": "pcs",
    "Waterproofing membrane": "m2",
    "Timber batten": "m",
    "Ridge cap": "m",
    "Roofing sealant": "pcs",
}

# material name -> price value (UAH per unit). Numbers only.
PRICES: dict[str, float] = {
    "Plaster mix": 8.5,
    "Primer": 45.0,
    "Reinforcing mesh": 35.0,
    "Plaster corner bead": 20.0,
    "Brick": 11.0,
    "Masonry mortar": 6.0,
    "Facade paint": 170.0,
    "Facade putty": 25.0,
    "Window glass unit": 900.0,
    "Window frame": 2500.0,
    "Glazing bead": 15.0,
    "Silicone sealant": 140.0,
    "Mounting foam": 220.0,
    "Window sill": 180.0,
    "Metal roof sheet": 315.0,
    "Roofing screw": 3.0,
    "Waterproofing membrane": 60.0,
    "Timber batten": 25.0,
    "Ridge cap": 150.0,
    "Roofing sealant": 180.0,
}

# material name -> (source, source_url) where confirmed; others use DEFAULT_SOURCE
SOURCES: dict[str, tuple[str, str]] = {
    "Plaster mix": ("Epicentr 2026-10-16", "https://epicentrk.ua/ua/shop/shtukaturka/"),
    "Metal roof sheet": ("Epicentr 2026-10-16", "https://epicentrk.ua/shop/metallocherepitsa/"),
}

# work code (from core.reference) -> (name, damage_class code, {material: qty per m2})
WORKS: dict[str, tuple[str, str, dict[str, float]]] = {
    # --- damaged_facade: 3 works -------------------------------------------
    "facade_plaster_repair": (
        "Facade plaster repair", "damaged_facade",
        {"Plaster mix": 12.0, "Primer": 0.25, "Reinforcing mesh": 1.1,
         "Plaster corner bead": 0.5}),
    "facade_masonry_repair": (
        "Masonry wall repair", "damaged_facade",
        {"Brick": 55.0, "Masonry mortar": 30.0, "Primer": 0.15}),
    "facade_painting": (
        "Facade painting", "damaged_facade",
        {"Facade paint": 0.3, "Primer": 0.15, "Facade putty": 1.0}),
    # --- broken_window: 2 works --------------------------------------------
    "window_glazing_replacement": (
        "Glazing replacement", "broken_window",
        {"Window glass unit": 1.0, "Silicone sealant": 0.5, "Glazing bead": 4.0}),
    "window_unit_replacement": (
        "Window unit replacement", "broken_window",
        {"Window frame": 1.0, "Window glass unit": 1.0, "Mounting foam": 0.4,
         "Silicone sealant": 0.5, "Window sill": 0.3}),
    # --- damaged_roof: 2 works ---------------------------------------------
    "roof_covering_repair": (
        "Roof covering repair", "damaged_roof",
        {"Roofing sealant": 0.5, "Waterproofing membrane": 1.1, "Roofing screw": 4.0}),
    "roof_covering_replacement": (
        "Roof covering replacement", "damaged_roof",
        {"Metal roof sheet": 1.1, "Roofing screw": 8.0, "Waterproofing membrane": 1.1,
         "Timber batten": 3.0, "Ridge cap": 0.3}),
}