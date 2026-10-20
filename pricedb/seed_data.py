"""Initial materials data (epic 5.2).

Work codes come from core.reference.WORK_TYPES (14 fixed codes): do not invent new work codes here.
quantity_per_unit is material per 1 unit of work: per m2 of damaged surface, except masonry and debris
removal, which are per m3 of wall (area x wall thickness).

Prices are in UAH per the material's own unit, each with its source:
- PRICES: the first prices (2026-10-16), mostly market estimates.
- PRICE_REVISIONS: prices checked in shops and price lists on 2026-10-17. They are added as new dated rows,
  so the first price stays in the history; materials added on that day get their first price here.
- LABOUR: labour per 1 m2 of each work, from average contractor price lists (mostly rabotniki.ua, 2026).
Retail prices from single shops, not official estimates: the report marks the cost as indicative.
"""
from datetime import date

PRICE_DATE = date(2026, 10, 16)
REVISION_DATE = date(2026, 10, 17)
LABOUR_DATE = date(2026, 10, 17)
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
    "Мінвата фасадна 100 мм": "m2",
    "Клей для мінвати": "kg",
    "Дюбель для утеплювача": "pcs",
    "Штукатурка декоративна короїд": "kg",
    "Вивезення будівельного сміття": "m3",
    "Оренда риштувань (місяць)": "m2",
    # windows
    "Склопакет двокамерний": "m2",
    "Віконний блок ПВХ без склопакета": "m2",
    "Штапик": "m",
    "Герметик силіконовий": "pcs",
    "Піна монтажна": "pcs",
    "Підвіконня ПВХ": "m",
    "Відлив віконний": "m",
    "Плита OSB-3 12 мм": "m2",
    "Плівка поліетиленова 150 мкм": "m2",
    # roof
    "Металочерепиця": "m2",
    "Саморіз покрівельний": "pcs",
    "Гідроізоляційна мембрана": "m2",
    "Брусок обрешітки": "m",
    "Гребінь покрівельний": "m",
    "Герметик покрівельний": "pcs",
    "Наплавлюваний матеріал ЕПП (нижній шар)": "m2",
    "Наплавлюваний матеріал ЕКП (верхній шар)": "m2",
    "Праймер бітумний": "kg",
    "Брус кроквяний 50x150": "m3",
    "Вогнебіозахист для деревини": "l",
    "Кріплення для крокв": "pcs",
}

# First prices, 2026-10-16 (material name -> UAH per unit).
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

# material name -> (source, source_url) of a first price that was confirmed; others use DEFAULT_SOURCE
SOURCES: dict[str, tuple[str, str]] = {
    "Штукатурна суміш цементна": ("Epicentr 2026-10-16", "https://epicentrk.ua/ua/shop/shtukaturka/"),
    "Металочерепиця": ("Epicentr 2026-10-16", "https://epicentrk.ua/shop/metallocherepitsa/"),
}

# Prices checked on 2026-10-17: material name -> (UAH per unit, source, url).
PRICE_REVISIONS: dict[str, tuple[float, str, str]] = {
    "Штукатурна суміш цементна": (8.0, "Ceresit cement plaster 25 kg, 199 UAH",
                                  "https://bud-platforma.com.ua/category/shtukaturky/tsementni"),
    "Ґрунтовка фасадна": (61.5, "Ceresit CT 17, 10 l, 614.90 UAH",
                          "https://optistroy.com.ua/catalog/fasadni_materialy/"),
    "Сітка армувальна": (21.9, "Masternet 160 g/m2, 50 m2 roll, 1095 UAH",
                         "https://optistroy.com.ua/catalog/fasadni_materialy/"),
    "Кутник штукатурний": (7.0, "PVC corner bead 3 m, 20 UAH",
                           "https://grico.com.ua/shtukaturni-kutniki-ta-mayaki/kutnik-pvh-perforovanij-3-m/"),
    "Цегла керамічна повнотіла": (14.0, "solid brick M-150, 14 UAH/pcs",
                                  "https://konsolbud.com.ua/tsehla-chervona-riadova-povnotila-m-150-ternopil"),
    "Шпаклівка фасадна": (17.8, "facade cement putty 25 kg, 443.96 UAH",
                          "https://prom.ua/ua/Shpaklevka-tsementnaya.html"),
    "Мінвата фасадна 100 мм": (494.0, "facade mineral wool 135 kg/m3, 100 mm, 1.44 m2 pack, 712 UAH (Epicentr)",
                               "https://epicentrk.ua/ua/shop/bazaltovaya-i-mineralnaya-vata/fs/oblast-primeneniya-fasad/"),
    "Клей для мінвати": (15.1, "Ceresit CT 190, 25 kg, 378 UAH",
                         "https://kub.in.ua/ua/kleevye-smesi/klej-dlja-mineralnoj-vaty/klej-dlja-minvaty-ceresit-ct-190"),
    "Дюбель для утеплювача": (6.8, "insulation dowel 10x140 with metal nail, 200 pcs, 1356 UAH",
                              "https://build.rozetka.com.ua/418252125/p418252125/"),
    "Штукатурка декоративна короїд": (20.6, "Ceresit CT 35, 25 kg, 515.85 UAH (Epicentr)",
                                      "https://epicentrk.ua/ua/shop/dekorativnaya-shtukaturka-koroed-ceresit-2-mm-25-kg.html"),
    "Вивезення будівельного сміття": (700.0, "construction debris removal with loading, from 700 UAH/m3 (Kyiv)",
                                      "https://murashka.kiev.ua/vyviz-budivelnoho-smittia/"),
    "Оренда риштувань (місяць)": (29.0, "scaffolding set 192 m2, 5299 UAH/month (Kyiv)",
                                  "https://lesa-kiev.biz.ua/index_ua.html"),
    # A PVC window is 5,500-6,500 UAH/m2 with a glass unit (manufacturer quoted in July 2026);
    # a two-chamber glass unit alone is 2,300-3,300 UAH/m2. Frame = window minus glass unit.
    "Склопакет двокамерний": (2700.0, "lux-okna.com 3082, viknanimechchyny.ua 2301 UAH/m2",
                              "https://lux-okna.com/komplektaciya/steklopakety/dvokamerni"),
    "Віконний блок ПВХ без склопакета": (3300.0, "window 5500-6500 UAH/m2 (07.2026) minus glass unit",
                                         "https://zaxid.net/tsini_na_sklopaketi_v_ukrayini_2026_zrostannya_40_vidsotkiv_yaka_prichina_n1640940"),
    "Герметик силіконовий": (135.0, "silicone sealant 280 ml, 135 UAH",
                             "https://sigma.ua/buy/germetik-silikonovyy-universalnyy-prozrachnyy-280ml-310g-oae-asmaco-2732701/"),
    "Піна монтажна": (239.0, "BauGut PRO 750 ml, 239 UAH (Epicentr)",
                      "https://epicentrk.ua/ua/shop/pena-stroitelnaya-baugut-pro-750ml.html"),
    "Підвіконня ПВХ": (475.2, "PVC sill 300 mm, 475.20 UAH/m (Epicentr)",
                       "https://epicentrk.ua/ua/shop/podokonniki/fs/material-vyrobu-pvkh/"),
    "Відлив віконний": (205.0, "metal window drip 250x1000 mm, 205 UAH",
                        "https://build.rozetka.com.ua/ua/379851840/p379851840/"),
    "Плита OSB-3 12 мм": (252.8, "OSB-3 12 mm 2500x1250, 789.90 UAH per sheet",
                          "https://budia.ua/plita-osb-25001250-12-mm"),
    "Плівка поліетиленова 150 мкм": (9.0, "PE film 150 um, 150 m2 roll, 1349 UAH",
                                     "https://bt-coffee.com.ua/budivelni-materiali/suputni-materiali/budivelni-plivki-ta-membrani/plivka-polietilenova-chorna-150-mkm-150-m2nexler"),
    "Саморіз покрівельний": (1.75, "roofing screw 4.8x35, 250 pcs, 435 UAH",
                             "https://kievdah.com.ua/ua/metallocerepica/komplektaciya-m-ch/samorez-krovelnyj-po-derevu.html"),
    "Гідроізоляційна мембрана": (25.8, "BRAVA 100 g/m2, 75 m2 roll, 1935 UAH",
                                 "https://torus-stroi.ua/ua/paro-gidro-barery/superdifuziina-membrana-brava-100g-m2-75-kv-m"),
    "Брусок обрешітки": (30.0, "pine batten 50x50, 21-45 UAH/m",
                         "https://pilo-material.kiev.ua/uk/pylomaterialy/brus/brusok-50x50-mm/"),
    "Гребінь покрівельний": (124.5, "half-round ridge 2 m, 249 UAH",
                             "https://bud-inteh.com/konek-polukruglyj-dlya-metallocherepicy-2-m"),
    "Герметик покрівельний": (145.0, "Grover B100 bitumen roofing sealant 300 ml, 145 UAH (Epicentr)",
                              "https://epicentrk.ua/ua/shop/hermetyk-bitumnyi-grover-b100-pokrivelnyi-chornyi-300-ml.html"),
    "Наплавлюваний матеріал ЕПП (нижній шар)": (108.5, "Bitumaks EPP 3.0, 10 m2 roll, 1085.45 UAH (Epicentr)",
                                                "https://epicentrk.ua/ua/shop/ruberoid-bitumaks-epp-3-0-rulon-10-kv-m.html"),
    "Наплавлюваний матеріал ЕКП (верхній шар)": (386.6, "Technoelast EKP 5.5, 10 m2 roll, 3866 UAH",
                                                 "https://prom.ua/ua/Tehnoelast-ekp.html"),
    "Праймер бітумний": (77.0, "ECOBIT bitumen primer 18 kg, 1386 UAH (Epicentr)",
                         "https://epicentrk.ua/ua/shop/mplc-praimer-bitumnii-ecobit-20-l-18-kg-1ec7785e-7580-653e-b1f0-41f1bb4279b7.html"),
    "Брус кроквяний 50x150": (12000.0, "pine beam 50x150x6000, 12000 UAH/m3 (Kyiv)",
                              "https://www.pilomaterial.com.ua/ua/brus-derevyannyj/brus-50x150x6000-sosna"),
    "Вогнебіозахист для деревини": (42.8, "Strazh-1 fire and bio protection 5 l, 214 UAH (Epicentr)",
                                    "https://epicentrk.ua/ua/shop/antiseptik-vodnyy-rasstvor-strazh-1-khmbb-3324-strazh-zelenyy-5-l.html"),
    "Кріплення для крокв": (28.8, "rafter connector Profstal 32x250, 28.78 UAH (Epicentr)",
                            "https://epicentrk.ua/shop/kreplenie-dlya-stropil-levoe-32x250x32x1-8-mm.html"),
}

# work code (from core.reference) -> (name, damage_class code, {material: qty per m2 of work})
WORKS: dict[str, tuple[str, str, dict[str, float]]] = {
    # --- damaged_facade ----------------------------------------------------
    "facade_plaster_repair": (
        "Facade plaster repair", "damaged_facade",
        {"Штукатурна суміш цементна": 15.0, "Ґрунтовка фасадна": 0.2, "Сітка армувальна": 1.1,
         "Кутник штукатурний": 0.5}),
    "facade_etics_repair": (
        "Insulated facade restoration", "damaged_facade",
        {"Мінвата фасадна 100 мм": 1.05, "Клей для мінвати": 9.0, "Дюбель для утеплювача": 6.0,
         "Сітка армувальна": 1.1, "Ґрунтовка фасадна": 0.2, "Штукатурка декоративна короїд": 3.0}),
    # per 1 m3 of wall: 250x120x65 bricks with 10 mm joints take 0.26 x 0.13 x 0.075 m each -> 394 per m3
    # (+3% waste); about 0.23 m3 of mortar per m3, i.e. ~420 kg of dry mix (Siltek M-1 data sheet)
    "facade_masonry_repair": (
        "Masonry wall repair", "damaged_facade",
        {"Цегла керамічна повнотіла": 406.0, "Розчин кладковий": 420.0}),
    "facade_painting": (
        "Facade painting", "damaged_facade",
        {"Фарба фасадна": 0.3, "Ґрунтовка фасадна": 0.15, "Шпаклівка фасадна": 1.0}),
    # per 1 m3 of destroyed wall: rubble takes about 1.4 times the volume of the wall it came from
    "facade_debris_removal": (
        "Dismantling and debris removal", "damaged_facade",
        {"Вивезення будівельного сміття": 1.4}),
    "facade_scaffolding": (
        "Facade scaffolding", "damaged_facade",
        {"Оренда риштувань (місяць)": 2.0}),          # two months of rent
    # --- broken_window -----------------------------------------------------
    "window_glazing_replacement": (
        "Glazing replacement", "broken_window",
        {"Склопакет двокамерний": 1.0, "Герметик силіконовий": 0.5, "Штапик": 4.0}),
    "window_unit_replacement": (
        "Window unit replacement", "broken_window",
        {"Віконний блок ПВХ без склопакета": 1.0, "Склопакет двокамерний": 1.0, "Піна монтажна": 0.4,
         "Герметик силіконовий": 0.5, "Підвіконня ПВХ": 0.3, "Відлив віконний": 0.3}),
    "window_temporary_closure": (
        "Temporary closure of openings", "broken_window",
        {"Плита OSB-3 12 мм": 1.1, "Брусок обрешітки": 2.0, "Плівка поліетиленова 150 мкм": 1.2}),
    # --- damaged_roof ------------------------------------------------------
    "roof_covering_repair": (
        "Pitched roof covering repair", "damaged_roof",
        {"Металочерепиця": 1.1, "Саморіз покрівельний": 8.0, "Герметик покрівельний": 0.2}),
    "roof_covering_replacement": (
        "Pitched roof covering replacement", "damaged_roof",
        {"Металочерепиця": 1.1, "Саморіз покрівельний": 8.0, "Гідроізоляційна мембрана": 1.1,
         "Брусок обрешітки": 3.0, "Гребінь покрівельний": 0.3}),
    "flat_roof_repair": (
        "Flat roof repair", "damaged_roof",
        {"Наплавлюваний матеріал ЕКП (верхній шар)": 1.15, "Праймер бітумний": 0.3,
         "Герметик покрівельний": 0.1}),
    "flat_roof_replacement": (
        "Flat roof replacement", "damaged_roof",
        {"Наплавлюваний матеріал ЕПП (нижній шар)": 1.15, "Наплавлюваний матеріал ЕКП (верхній шар)": 1.15,
         "Праймер бітумний": 0.3}),
    "roof_structure_repair": (
        "Rafter structure repair", "damaged_roof",
        {"Брус кроквяний 50x150": 0.02, "Вогнебіозахист для деревини": 0.4, "Кріплення для крокв": 1.5}),
}

# work code -> (UAH per m2 of work, source, source_url). Labour only, materials are priced separately.
LABOUR: dict[str, tuple[float, str, str]] = {
    "facade_plaster_repair": (339.0, "rabotniki.ua: cement-sand facade plaster, average of 692 price lists",
                              "https://www.rabotniki.ua/uk/price/shtukaturka-fasada-tsementnopeschannaya-mayachnaya"),
    "facade_etics_repair": (1050.0, "rabotniki.ua: wall insulation with mineral wool 740 + decorative plaster 310",
                            "https://www.rabotniki.ua/uk/price/uteplenie-sten-minvatoy"),
    "facade_masonry_repair": (3141.0, "rabotniki.ua: rough brick masonry per m3, average of 849 price lists",
                              "https://www.rabotniki.ua/uk/price/stena-chernovaya-ne-bolee-380-sht-na-kub"),
    "facade_painting": (201.0, "rabotniki.ua: facade painting in two coats, average",
                        "https://www.rabotniki.ua/uk/price/pokraska-fasada-ili-steny-dva-sloya"),
    "facade_debris_removal": (1344.0, "rabotniki.ua: dismantling of a one-brick (0.25 m) wall 336 UAH/m2, "
                                      "i.e. 1344 UAH per m3", "https://www.rabotniki.ua/uk/price/demontazh-kirpichnoy-peregorodki-kirpich"),
    "facade_scaffolding": (111.0, "rabotniki.ua: scaffolding erection and dismantling, average of 452 price lists",
                           "https://www.rabotniki.ua/uk/price/montazh-demontazh-lesov-vertikalnoy-proektsii"),
    "window_glazing_replacement": (717.0, "rabotniki.ua: glass replacement in a window, Kyiv average",
                                   "https://www.rabotniki.ua/uk/price/zamena-stekla-dveri/kiev"),
    "window_unit_replacement": (587.0, "rabotniki.ua: PVC window installation, average of 448 price lists",
                                "https://www.rabotniki.ua/uk/price/montazh-okna-metalloplastikovogo"),
    "window_temporary_closure": (200.0, "rabotniki.ua: OSB board installation, average of 859 price lists",
                                 "https://www.rabotniki.ua/uk/price/montazh-osb-plit"),
    "roof_covering_repair": (310.0, "rabotniki.ua: metal tile laying, average",
                             "https://www.rabotniki.ua/uk/krovelnye-raboty"),
    "roof_covering_replacement": (556.0, "rabotniki.ua: roof dismantling 246 + metal tile laying 310, averages",
                                  "https://www.rabotniki.ua/uk/krovelnye-raboty"),
    "flat_roof_repair": (132.0, "budver.com: torch-on roofing installation, from 132 UAH/m2",
                         "https://budver.com/masters/pokrivelni-roboti"),
    "flat_roof_replacement": (269.0, "torch-on roofing from 132 (budver.com) + old roof dismantling from 137 "
                              "(alpinist.kiev.ua)", "https://alpinist.kiev.ua/ua/prajs-na-krovelnye-raboty/"),
    "roof_structure_repair": (375.0, "rabotniki.ua: rafter structure, average of 847 price lists",
                              "https://www.rabotniki.ua/uk/price/ustroystva-stropilnoy-konstruktsii"),
}
