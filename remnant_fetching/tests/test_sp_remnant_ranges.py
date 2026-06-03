"""Pure-Python regression checks for the remnant picking engine.

The test imports ``picking_logic.py`` directly so these checks run without an
Odoo server while still exercising the same calculator used by the Odoo model.
"""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from picking_logic import (  # noqa: E402
    BOTH,
    HEIGHTWISE,
    WIDTHWISE,
    PickingInput,
    RemnantInput,
    best_fit_for_remnant,
    best_remnant_fit,
)


SU_STOCK = [
    RemnantInput("R-SU-12-001", 1.70, 1.10, 1),
    RemnantInput("R-SU-12-002", 0.90, 1.12, 2),
    RemnantInput("R-SU-12-003", 0.95, 1.70, 3),
    RemnantInput("R-SU-12-004", 1.30, 1.60, 4),
    RemnantInput("R-SU-12-005", 0.82, 1.45, 5),
    RemnantInput("R-SU-12-006", 1.05, 1.35, 6),
    RemnantInput("R-SU-12-007", 1.15, 1.80, 7),
    RemnantInput("R-SU-12-008", 1.42, 1.48, 8),
    RemnantInput("R-SU-12-009", 1.55, 1.05, 9),
    RemnantInput("R-SU-12-010", 1.65, 1.45, 10),
    RemnantInput("R-SU-12-011", 1.85, 1.25, 11),
    RemnantInput("R-SU-12-012", 0.78, 2.05, 12),
    RemnantInput("R-SU-12-013", 1.25, 2.20, 13),
    RemnantInput("R-SU-12-014", 2.05, 0.85, 14),
    RemnantInput("R-SU-12-015", 0.88, 0.95, 15),
    RemnantInput("R-SU-12-016", 1.12, 1.12, 16),
    RemnantInput("R-SU-12-017", 0.45, 0.80, 17),
    RemnantInput("R-SU-12-018", 0.55, 0.95, 18),
    RemnantInput("R-SU-12-019", 0.65, 1.05, 19),
    RemnantInput("R-SU-12-020", 0.72, 1.25, 20),
    RemnantInput("R-SU-12-021", 0.60, 1.60, 21),
    RemnantInput("R-SU-12-022", 0.35, 1.10, 22),
]


def picking(width, height, tolerance=1.5, layers=1):
    return PickingInput(
        order_width=width,
        order_height=height,
        tolerance=tolerance,
        layer_count=layers,
        rule_orientation=BOTH,
        requested_orientation=WIDTHWISE,
    )


def valid_candidates(width, height, tolerance=1.5, layers=1):
    request = picking(width, height, tolerance=tolerance, layers=layers)
    found = []
    for remnant in SU_STOCK:
        result = best_fit_for_remnant(request, remnant)
        if result:
            found.append(
                (result.sequence, result.remnant_id, result.calculation, round(result.area, 3))
            )
    return [
        (remnant_id, calculation, area)
        for _, remnant_id, calculation, area in sorted(found)
    ]


def test_width_1_height_1_4_excludes_low_width_remnant():
    candidates = valid_candidates(1.00, 1.40)
    candidate_ids = {candidate[0] for candidate in candidates}
    assert "R-SU-12-012" not in candidate_ids
    assert best_remnant_fit(picking(1.00, 1.40), SU_STOCK).remnant_id == "R-SU-12-007"


def test_each_remnant_has_one_valid_by_value():
    candidates = valid_candidates(1.10, 1.60)
    candidate_ids = [candidate[0] for candidate in candidates]
    assert len(candidate_ids) == len(set(candidate_ids))


def test_height_uses_excel_min_max_range():
    candidates = valid_candidates(0.68, 1.25)
    assert ("R-SU-12-003", WIDTHWISE, 1.615) in candidates
    assert ("R-SU-12-004", HEIGHTWISE, 2.08) not in candidates
    assert best_remnant_fit(picking(0.68, 1.25), SU_STOCK).remnant_id == "R-SU-12-020"


def test_width_0_68_height_1_25_candidate_set():
    candidates = valid_candidates(0.68, 1.25)
    candidate_ids = {candidate[0] for candidate in candidates}
    expected = {
        "R-SU-12-003",
        "R-SU-12-005",
        "R-SU-12-020",
    }
    assert candidate_ids == expected
    assert "R-SU-12-021" not in candidate_ids


def test_heightwise_calculation_rotates_fabric_dimensions():
    request = picking(0.55, 2.10)
    remnant = RemnantInput("R-SU-12-013", 1.25, 2.20, 13)
    result = best_fit_for_remnant(request, remnant)
    assert result is None


def test_r_su_005_is_valid_by_widthwise_range():
    candidates = valid_candidates(0.50, 1.30)
    assert ("R-SU-12-005", WIDTHWISE, 1.189) not in candidates


def test_r_su_013_is_rejected_by_height_max():
    candidates = valid_candidates(0.80, 1.50)
    assert ("R-SU-12-013", HEIGHTWISE, 2.75) not in candidates


def test_r_su_004_is_rejected_by_height_max():
    candidates = valid_candidates(0.55, 1.40)
    assert ("R-SU-12-004", HEIGHTWISE, 2.08) not in candidates


def test_r_su_001_is_rejected_by_height_max_for_tall_narrow_order():
    candidates = valid_candidates(0.60, 1.50)
    assert ("R-SU-12-001", HEIGHTWISE, 1.87) not in candidates


if __name__ == "__main__":
    test_width_1_height_1_4_excludes_low_width_remnant()
    test_each_remnant_has_one_valid_by_value()
    test_height_uses_excel_min_max_range()
    test_width_0_68_height_1_25_candidate_set()
    test_heightwise_calculation_rotates_fabric_dimensions()
    test_r_su_005_is_valid_by_widthwise_range()
    test_r_su_013_is_rejected_by_height_max()
    test_r_su_004_is_rejected_by_height_max()
    test_r_su_001_is_rejected_by_height_max_for_tall_narrow_order()
    print("SU Sunscreen remnant picking regression checks: ok")
