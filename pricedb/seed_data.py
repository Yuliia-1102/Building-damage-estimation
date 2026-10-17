"""Initial materials data (epic 5.2).

Work codes/names come from core.reference.WORK_TYPES (7 fixed codes) — do not
invent new work codes here. Every work is measured in m2, so quantity_per_unit
means "material per 1 m2 of work". Each work has a full bill of materials, and
every material it needs is in the MATERIALS/PRICES tables below.

Prices: UAH per the material's own unit. Two confirmed on Epicentr (2026-10-16);
the rest are market estimates to verify before the defense. PRICE_REVISIONS adds newer dated prices on top
(the old rows stay, so the history shows the change). LABOUR holds the labour rate per 1 m2 of each work,
from average contractor price lists (rabotniki.ua, 2026).
"""
from datetime import date

PRICE_DATE = date(2026, 10, 16)
DEFAULT_SOURCE = "market estimate (verify)"

# material name -> unit
MATERIALS: dict[str, str] = {
    # facade
    "Штукатурна суміш цементна": "kg",
    "Ґрунтовка фасадна": "l",
    "Сітка армувальна": "m2",
    "Кутник штукатурний": "m",
    "Цегла керамічна повнотіла": "pcs",
    "Розчин кладковий": "kg",
    "Фарба фасадна": "l",
    "Шпаклівка фасадна": "kg",
    # windows
    "Склопакет двокамерний": "m2",
    "Віконний блок ПВХ без склопакета": "m2",
    "Штапик": "m",
    "Герметик силіконовий": "pcs",
    "Піна монтажна": "pcs",
    "Підвіконня ПВХ": "m",
    # roof
    "Металочерепиця": "m2",
    "Саморіз покрівельний": "pcs",
    "Гідроізоляційна мембрана": "m2",
    "Брусок обрешітки": "m",
    "Гребінь покрівельний": "m",
    "Герметик покрівельний": "pcs",
}

# material name -> price value (UAH per unit). Numbers only.
PRICES: dict[str, float] = {
    "Штукатурна суміш цементна": 8.5,
    "Ґрунтовка фасадна": 45.0,
    "Сітка армувальна": 35.0,
    "Кутник штукатурний": 20.0,
    "Цегла керамічна повнотіла": 11.0,
    "Розчин кладковий": 6.0,
    "Фарба фасадна": 170.0,
    "Шпаклівка фасадна": 25.0,
    "Склопакет двокамерний": 900.0,
    "Віконний блок ПВХ без склопакета": 2500.0,
    "Штапик": 15.0,
    "Герметик силіконовий": 140.0,
    "Піна монтажна": 220.0,
    "Підвіконня ПВХ": 180.0,
    "Металочерепиця": 315.0,
    "Саморіз покрівельний": 3.0,
    "Гідроізоляційна мембрана": 60.0,
    "Брусок обрешітки": 25.0,
    "Гребінь покрівельний": 150.0,
    "Герметик покрівельний": 180.0,
}

# material name -> (source, source_url) where confirmed; others use DEFAULT_SOURCE
SOURCES: dict[str, tuple[str, str]] = {
    "Штукатурна суміш цементна": ("Epicentr 2026-10-16", "https://epicentrk.ua/ua/shop/shtukaturka/"),
    "Металочерепиця": ("Epicentr 2026-10-16", "https://epicentrk.ua/shop/metallocherepitsa/"),
}

# work code (from core.reference) -> (name, damage_class code, {material: qty per m2})
WORKS: dict[str, tuple[str, str, dict[str, float]]] = {
    # --- damaged_facade: 3 works -------------------------------------------
    "facade_plaster_repair": (
        "Facade plaster repair", "damaged_facade",
        {"Штукатурна суміш цементна": 12.0, "Ґрунтовка фасадна": 0.25, "Сітка армувальна": 1.1,
         "Кутник штукатурний": 0.5}),
    "facade_masonry_repair": (
        "Masonry wall repair", "damaged_facade",
        {"Цегла керамічна повнотіла": 55.0, "Розчин кладковий": 30.0, "Ґрунтовка фасадна": 0.15}),
    "facade_painting": (
        "Facade painting", "damaged_facade",
        {"Фарба фасадна": 0.3, "Ґрунтовка фасадна": 0.15, "Шпаклівка фасадна": 1.0}),
    # --- broken_window: 2 works --------------------------------------------
    "window_glazing_replacement": (
        "Glazing replacement", "broken_window",
        {"Склопакет двокамерний": 1.0, "Герметик силіконовий": 0.5, "Штапик": 4.0}),
    "window_unit_replacement": (
        "Window unit replacement", "broken_window",
        {"Віконний блок ПВХ без склопакета": 1.0, "Склопакет двокамерний": 1.0, "Піна монтажна": 0.4,
         "Герметик силіконовий": 0.5, "Підвіконня ПВХ": 0.3}),
    # --- damaged_roof: 2 works ---------------------------------------------
    "roof_covering_repair": (
        "Roof covering repair", "damaged_roof",
        {"Герметик покрівельний": 0.5, "Гідроізоляційна мембрана": 1.1, "Саморіз покрівельний": 4.0}),
    "roof_covering_replacement": (
        "Roof covering replacement", "damaged_roof",
        {"Металочерепиця": 1.1, "Саморіз покрівельний": 8.0, "Гідроізоляційна мембрана": 1.1,
         "Брусок обрешітки": 3.0, "Гребінь покрівельний": 0.3}),
}

# Newer prices for materials whose first price was off. Added as new dated rows; the first price stays in history.
REVISION_DATE = date(2026, 10, 17)
PRICE_REVISIONS: dict[str, tuple[float, str, str]] = {
    # A PVC window is 5,500-6,500 UAH/m2 with a glass unit (manufacturer quoted by LIGA.net, July 2026);
    # a two-chamber glass unit alone is 2,300-3,300 UAH/m2. Frame = window minus glass unit.
    "Склопакет двокамерний": (2700.0, "lux-okna.com 3082, viknanimechchyny.ua 2301 UAH/m2, 2026",
                              "https://lux-okna.com/komplektaciya/steklopakety/dvokamerni"),
    "Віконний блок ПВХ без склопакета": (3300.0, "window 5500-6500 UAH/m2 (LIGA.net, 07.2026) minus glass unit",
                                         "https://zaxid.net/tsini_na_sklopaketi_v_ukrayini_2026_zrostannya_40_vidsotkiv_yaka_prichina_n1640940"),
}

# work code -> (UAH per m2 of work, source, source_url). Labour only, materials are priced separately.
LABOUR_DATE = date(2026, 10, 17)
LABOUR: dict[str, tuple[float, str, str]] = {
    "facade_plaster_repair": (339.0, "rabotniki.ua: cement-sand facade plaster, average of 692 price lists",
                              "https://www.rabotniki.ua/uk/price/shtukaturka-fasada-tsementnopeschannaya-mayachnaya"),
    "facade_masonry_repair": (700.0, "rabotniki.ua: half-brick masonry, Kyiv 733, Lviv 698, Odesa 665",
                              "https://www.rabotniki.ua/uk/kladochnye-raboty/kiev"),
    "facade_painting": (201.0, "rabotniki.ua: facade painting in two coats, average",
                        "https://www.rabotniki.ua/uk/price/pokraska-fasada-ili-steny-dva-sloya"),
    "window_glazing_replacement": (717.0, "rabotniki.ua: glass replacement in a window, Kyiv average",
                                   "https://www.rabotniki.ua/uk/price/zamena-stekla-dveri/kiev"),
    "window_unit_replacement": (587.0, "rabotniki.ua: PVC window installation, average of 448 price lists",
                                "https://www.rabotniki.ua/uk/price/montazh-okna-metalloplastikovogo"),
    "roof_covering_repair": (285.0, "rabotniki.ua: membrane roofing 230-340, individual quotes (estimate)",
                             "https://www.rabotniki.ua/uk/krovelnye-raboty"),
    "roof_covering_replacement": (556.0, "rabotniki.ua: roof dismantling 246 + metal tile laying 310, averages",
                                  "https://www.rabotniki.ua/uk/krovelnye-raboty"),
}
