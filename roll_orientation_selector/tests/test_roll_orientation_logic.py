"""Pure-Python checks for workbook-based roll/orientation selection."""

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roll_orientation_logic import (  # noqa: E402
    BOTH,
    WIDTHWISE,
    HEIGHTWISE,
    RollInput,
    RollInputCandidate,
    best_roll_fit,
    roll_fit_results,
)


LOTS = [
    RollInputCandidate(1, "LOT-W200-SU-12-001", 2.00, 1),
    RollInputCandidate(2, "LOT-W250-SU-12-001", 2.50, 2),
    RollInputCandidate(3, "LOT-W300-SU-12-001", 3.00, 3),
]


def test_sunscreen_uses_lowest_waste_orientation_from_workbook():
    roll_input = RollInput(
        order_width=1.60,
        order_height=1.80,
        layer_count=1,
        rule_orientation=BOTH,
        fabric_allowance_m=0.20,
    )
    best = best_roll_fit(roll_input, LOTS)
    assert best.lot_name == "LOT-W250-SU-12-001"
    assert best.orientation == HEIGHTWISE
    assert round(best.waste_area_m2, 4) == 0.6908


def test_widthwise_category_uses_widthwise_only():
    roll_input = RollInput(
        order_width=1.60,
        order_height=1.80,
        layer_count=2,
        rule_orientation=WIDTHWISE,
        fabric_allowance_m=0.20,
    )
    results = roll_fit_results(roll_input, LOTS)
    assert {result.orientation for result in results} == {WIDTHWISE}
    best = best_roll_fit(roll_input, LOTS)
    assert best.lot_name == "LOT-W200-SU-12-001"
    assert round(best.waste_area_m2, 3) == 1.406


def test_day_night_fallback_uses_widthwise_roll():
    lots = [
        RollInputCandidate(1, "LOT-W200-DN-001", 2.00, 1),
        RollInputCandidate(2, "LOT-W250-DN-001", 2.50, 2),
        RollInputCandidate(3, "LOT-W300-DN-001", 3.00, 3),
    ]
    roll_input = RollInput(
        order_width=0.90,
        order_height=2.00,
        layer_count=2,
        rule_orientation=WIDTHWISE,
        fabric_allowance_m=0.20,
    )
    results = roll_fit_results(roll_input, lots)
    assert {result.orientation for result in results} == {WIDTHWISE}
    best = best_roll_fit(roll_input, lots)
    assert best.lot_name == "LOT-W200-DN-001"
    assert round(best.waste_area_m2, 3) == 4.494


if __name__ == "__main__":
    test_sunscreen_uses_lowest_waste_orientation_from_workbook()
    test_widthwise_category_uses_widthwise_only()
    test_day_night_fallback_uses_widthwise_roll()
    print("Roll orientation selector regression checks: ok")
