from dataclasses import dataclass


WIDTHWISE = "widthwise"
HEIGHTWISE = "heightwise"
BOTH = "both"
WIDTH_DEDUCTION_M = 0.03
PRECISION = 1e-9


@dataclass(frozen=True)
class PickingInput:
    order_width: float
    order_height: float
    tolerance: float
    layer_count: int
    rule_orientation: str
    requested_orientation: str = WIDTHWISE


@dataclass(frozen=True)
class RemnantInput:
    remnant_id: str
    fabric_width: float
    fabric_height: float
    sequence: int = 0

    @property
    def area(self):
        return self.fabric_width * self.fabric_height


@dataclass(frozen=True)
class FitResult:
    remnant_id: str
    calculation: str
    effective_width: float
    effective_height: float
    min_width: float
    max_width: float
    min_height: float
    max_height: float
    width_ok: bool
    height_ok: bool
    area: float
    sequence: int

    @property
    def valid(self):
        return self.width_ok and self.height_ok


def allowed_calculations(rule_orientation, requested_orientation=WIDTHWISE):
    if rule_orientation == BOTH:
        return [WIDTHWISE, HEIGHTWISE]
    if rule_orientation == requested_orientation:
        return [requested_orientation]
    return []


def effective_dimensions(remnant, calculation):
    if calculation == HEIGHTWISE:
        return remnant.fabric_height, remnant.fabric_width
    return remnant.fabric_width, remnant.fabric_height


def calculation_bounds(picking, calculation):
    width_min = max(picking.order_width - WIDTH_DEDUCTION_M, 0.0)
    if calculation == HEIGHTWISE:
        return (
            picking.order_height,
            picking.order_height * picking.tolerance,
            width_min,
            picking.order_width * picking.tolerance * picking.layer_count,
        )
    return (
        width_min,
        picking.order_width * picking.tolerance,
        picking.order_height * picking.layer_count,
        picking.order_height * picking.tolerance * picking.layer_count,
    )


def is_at_least(value, minimum):
    return value + PRECISION >= minimum


def is_between(value, minimum, maximum):
    return is_at_least(value, minimum) and value <= maximum + PRECISION


def fit_results_for_remnant(picking, remnant):
    results = []
    for calculation in allowed_calculations(
        picking.rule_orientation, picking.requested_orientation
    ):
        min_width, max_width, min_height, max_height = calculation_bounds(
            picking, calculation
        )
        effective_width, effective_height = effective_dimensions(remnant, calculation)
        results.append(
            FitResult(
                remnant_id=remnant.remnant_id,
                calculation=calculation,
                effective_width=effective_width,
                effective_height=effective_height,
                min_width=min_width,
                max_width=max_width,
                min_height=min_height,
                max_height=max_height,
                width_ok=is_between(effective_width, min_width, max_width),
                height_ok=is_between(effective_height, min_height, max_height),
                area=remnant.area,
                sequence=remnant.sequence,
            )
        )
    return results


def best_fit_for_remnant(picking, remnant):
    valid_results = [result for result in fit_results_for_remnant(picking, remnant) if result.valid]
    if not valid_results:
        return None
    return sorted(
        valid_results,
        key=lambda result: (
            result.area,
            0 if result.calculation == WIDTHWISE else 1,
            result.sequence,
            result.remnant_id,
        ),
    )[0]


def best_remnant_fit(picking, remnants):
    valid_results = []
    for remnant in remnants:
        result = best_fit_for_remnant(picking, remnant)
        if result:
            valid_results.append(result)
    if not valid_results:
        return None
    return sorted(
        valid_results,
        key=lambda result: (result.area, result.sequence, result.remnant_id),
    )[0]
