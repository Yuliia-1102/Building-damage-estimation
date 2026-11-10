from core.report_pdf import build_pdf, cost_basis_ua, summary_ua
from core.types import CombinedRatios, CostEstimate, CostLine, DamagedAreas, Decision, Report


def report(escalation="confirmed", is_stub=False, labour=300.0):
    lines = [CostLine("w", "brick", 10, "pcs", 70, 700.0)]
    if labour:
        lines.append(CostLine("w", "labour", 10, "m2", labour / 10, labour))
    total = sum(l.cost for l in lines)
    return Report(
        case_id="house+2", mode="photos", views_assessed=3, frames=[], ratios=CombinedRatios(None, None, None, 0, 0),
        areas=DamagedAreas(wall_area_m2=1000, roof_area_m2=None, damaged_facade_m2=120.0, broken_window_m2=None,
                           damaged_roof_m2=None, visible_wall_area_m2=400),
        decision=Decision(damage_category="II", condition_category=3, confidence=0.8, works=[],
                          escalation=escalation, is_stub=is_stub),
        cost=CostEstimate(lines=lines, total=total, low=total * 0.8, high=total * 1.2, as_of="2026-11-10"))


def test_cost_is_split_into_materials_and_labour():
    k = report().cost
    assert (k.materials, k.labour) == (700.0, 300.0)


def test_summary_has_category_condition_cost_confidence():
    text = summary_ua(report())
    assert "Категорія пошкоджень II" in text and "технічний стан 3" in text and "вартість від" in text and "0.80" in text


def test_a_stub_decision_gives_no_summary():
    assert summary_ua(report(is_stub=True)) is None


def test_insufficient_data_gives_no_category():
    text = summary_ua(report(escalation="insufficient_data"))
    assert "не визначено" in text and "II" not in text


def test_cost_basis_names_only_the_areas_used():
    notes = cost_basis_ua(report())
    assert "матеріали" in notes[0] and "робота" in notes[0]
    assert "пошкоджений фасад" in notes[1] and "дах" not in notes[1]


def test_cost_basis_without_labour_rates():
    assert "розцінок на роботу немає" in cost_basis_ua(report(labour=0))[0]


def test_pdf_builds_with_the_summary():
    assert build_pdf(report()).startswith(b"%PDF")
