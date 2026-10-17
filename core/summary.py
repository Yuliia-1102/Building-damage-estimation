"""The conclusion in words, built from the numbers by fixed rules (no language model, so it is free and the same
on every run). Used by the UI and the PDF."""
from core.reference import (CONDITION_NAMES_UA, DAMAGE_NAMES_UA, DAMAGE_RECOMMENDATION_UA, STRUCTURE_NAMES_UA,
                            WORK_NAMES_UA)
from core.types import Report


def _degree(share: float) -> str:
    if share >= 0.6:
        return "переважну частину"
    if share >= 0.3:
        return "значну частину"
    if share >= 0.1:
        return "окремі ділянки"
    return "поодинокі місця"


def summary_points(report: Report) -> list[str]:
    """Short points, each one sentence, in the order: the building, facade, windows, roof, verdict, what to do."""
    r, b, d, a = report.ratios, report.building, report.decision, report.areas
    points = []
    if b is not None and b.floors:
        kind = STRUCTURE_NAMES_UA.get(b.structure_type or "unknown", "невідомо")
        points.append(f"Будівля: {b.floors}-поверхова, конструкція — {kind}, оцінено {report.views_assessed} "
                      f"видів з різних сторін.")

    if r.damaged_facade is not None:
        damaged = r.damaged_facade + (r.broken_window or 0)
        text = f"Фасад: пошкоджено {_degree(damaged)} видимої поверхні ({damaged:.0%}"
        if a and a.damaged_facade_m2:
            area = f"{a.damaged_facade_m2:,.0f}".replace(",", " ")
            text += f", ≈ {area} м²"
        text += ")."
        if r.worst_section_damage is not None and r.worst_section_damage >= 0.6 \
                and r.worst_section_damage - damaged >= 0.15:
            text += (f" Пошкодження зосереджені: одна секція фасаду пошкоджена на {r.worst_section_damage:.0%}, "
                     f"тоді як решта — менше.")
        elif r.worst_section_damage is not None and r.worst_section_damage >= 0.9:
            text += f" Щонайменше одна секція фасаду зруйнована майже повністю ({r.worst_section_damage:.0%})."
        if r.damage_by_third:
            low, mid, up = r.damage_by_third
            where = max(("нижній", low), ("середній", mid), ("верхній", up), key=lambda x: x[1])[0]
            text += f" Найбільше пошкоджень у {where} третині висоти"
            text += " — це небезпечніше для всієї будівлі." if where == "нижній" else "."
        points.append(text)

    if r.broken_window is not None:
        if r.broken_window >= 0.03:
            points.append(f"Вікна: виявлено пошкоджені вікна ({r.broken_window:.0%} фасаду).")
        else:
            points.append("Вікна: окремо пошкоджених вікон майже не виявлено. Якщо стіни навколо зруйновані, "
                          "вікна зазвичай враховано у пошкодженнях фасаду.")

    if r.damaged_roof is not None:
        text = f"Дах: пошкоджено {_degree(r.damaged_roof)} видимої покрівлі ({r.damaged_roof:.0%})."
        if r.roof_partly_seen:
            text += " Дах видно лише смугою, оцінка приблизна."
        points.append(text)
    else:
        points.append("Дах: на знімках не видно, не оцінювався.")

    if d is not None:
        points.append(f"Висновок: категорія пошкоджень {d.damage_category} ({DAMAGE_NAMES_UA[d.damage_category]}), "
                      f"технічний стан {d.condition_category} ({CONDITION_NAMES_UA[d.condition_category]}). "
                      f"Рекомендація: {DAMAGE_RECOMMENDATION_UA[d.damage_category]}.")
        if d.condition_category == 4:
            points.append("Увага: аварійний стан — доступ людей у небезпечну зону слід обмежити до обстеження.")
        main = [WORK_NAMES_UA.get(w.work_type, w.work_type).lower() for w in d.works[:4]]
        if main:
            points.append("Основні роботи: " + ", ".join(main) + ".")
    return points
