from dataclasses import dataclass


WIDTHWISE = "widthwise"
HEIGHTWISE = "heightwise"
BOTH = "both"
WIDTH_DEDUCTION_M = 0.03
HEIGHTWISE_SIDE_ALLOWANCE_M = 0.06


@dataclass(frozen=True)
class RollInput:
    order_width: float
    order_height: float
    layer_count: int
    rule_orientation: str
    fabric_allowance_m: float = 0.20


@dataclass(frozen=True)
class RollInputCandidate:
    lot_id: int
    lot_name: str
    roll_width_m: float
    sequence: int = 0


@dataclass(frozen=True)
class RollFitResult:
    lot_id: int
    lot_name: str
    roll_width_m: float
    orientation: str
    waste_width_m: float
    cut_height_m: float
    waste_area_m2: float
    sequence: int

    @property
    def valid(self):
        return self.waste_width_m >= 0 and self.cut_height_m > 0


def allowed_orientations(rule_orientation):
    if rule_orientation == BOTH:
        return [WIDTHWISE, HEIGHTWISE]
    return [rule_orientation]


def roll_fit_result(roll_input, lot, orientation):
    if orientation == HEIGHTWISE:
        waste_width = (
            lot.roll_width_m
            - HEIGHTWISE_SIDE_ALLOWANCE_M
            - roll_input.order_height
            - roll_input.fabric_allowance_m
        )
        cut_height = roll_input.order_width - WIDTH_DEDUCTION_M
    else:
        waste_width = lot.roll_width_m - roll_input.order_width - WIDTH_DEDUCTION_M
        cut_height = (
            roll_input.order_height * roll_input.layer_count
            + roll_input.fabric_allowance_m
        )
    return RollFitResult(
        lot_id=lot.lot_id,
        lot_name=lot.lot_name,
        roll_width_m=lot.roll_width_m,
        orientation=orientation,
        waste_width_m=waste_width,
        cut_height_m=cut_height,
        waste_area_m2=waste_width * cut_height,
        sequence=lot.sequence,
    )


def roll_fit_results(roll_input, lots):
    results = []
    for lot in lots:
        for orientation in allowed_orientations(roll_input.rule_orientation):
            result = roll_fit_result(roll_input, lot, orientation)
            if result.valid:
                results.append(result)
    return results


def best_roll_fit(roll_input, lots):
    valid_results = roll_fit_results(roll_input, lots)
    if not valid_results:
        return None
    return sorted(
        valid_results,
        key=lambda result: (
            result.waste_area_m2,
            result.roll_width_m,
            0 if result.orientation == WIDTHWISE else 1,
            result.sequence,
            result.lot_name,
        ),
    )[0]
