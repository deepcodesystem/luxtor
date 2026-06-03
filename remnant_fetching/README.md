# Remnant Picking

Odoo 19 addon for picking the smallest suitable fabric remnant for roller blind orders.

## Logic

For each request, the module selects a remnant only when all rules pass:

- Same remnant category.
- Same exact ordered fabric/product.
- Remnant is available.
- The category calculation rule allows the requested cut direction.
- Usable layer count is greater than or equal to the requested layer count.
- Both relevant remnant dimensions must fit.
- Widthwise follows the workbook formulas:
  - Fabric width minimum is `roller blind width - 0.03`.
  - Fabric width maximum is `roller blind width * tolerance`.
  - Fabric height minimum is `roller blind height * layer count`.
  - Fabric height maximum is `roller blind height * tolerance * layer count`.
- Heightwise follows the workbook formulas:
  - Fabric width minimum is `roller blind height`.
  - Fabric width maximum is `roller blind height * tolerance`.
  - Fabric height minimum is `roller blind width - 0.03`.
  - Fabric height maximum is `roller blind width * tolerance * layer count`.
- Heightwise calculation rotates the remnant dimensions, so effective fabric width is stored fabric height and effective fabric height is stored fabric width.

When several remnants match, the picker sorts by remnant area, then sequence, so the smallest usable remnant is selected first.

If one remnant fits both widthwise and heightwise calculations, the module records one selected calculation only. Widthwise is used as the tie-breaker when both fits have the same area.

For categories configured as `Widthwise & Heightwise`, such as Sunscreen, the module checks both directions:

- Widthwise candidates use `required_width_m`.
- Heightwise candidates use `required_height_m`.
- The final result is the smallest remnant across both candidate sets.

Each remnant stock record belongs to one exact fabric product and one remnant code. It has physical fabric dimensions only: `width_m` and `height_m`, labeled in the UI as fabric width and fabric height. Stock records do not store orientation. The displayed `size_m` is computed as area: `width_m * height_m`.

Remnant dimensions are displayed using this format: `W.x * H.y`, for example `W.1.70 * H.1.10`.
Candidate ranges are displayed using this format: `W.min-max * H.min-max`, for example `W.1.17-1.80 * H.1.80-2.70`.

Each remnant has a product-specific counter code: `001`, `002`, `003`, and so on. Remnant IDs use the product code prefix plus this counter, for example product `SU`, color `12`, with remnant code `001` displays as `R-SU-12-001`.

## Main Models

- `remnant.category.rule`: Category setup for orientation, layer count, and tolerance.
- `remnant.stock`: Available, reserved, consumed, or scrapped fabric remnants with product-specific remnant code and physical dimensions. Source LOT is optional/internal traceability only.
- `remnant.fetch.request`: Stores each remnant picking result and confirmation checks.
- `sale.order.line`: Adds remnant fields and a button to pick the best remnant.

## Tests

- `picking_logic.py` is the single source of truth for dimension ranges, heightwise rotation, fit validation, and best-remnant ordering.
- `tests/test_sp_remnant_ranges.py` contains pure-Python regression checks for the SU/Sunscreen range rules.
- `tests/test_remnant_picking_odoo.py` contains Odoo `TransactionCase` checks for ORM picking and batch remnant numbering.

## Setup

1. Copy `remnant_fetching` into an Odoo addons path.
2. Update the app list.
3. Install **Remnant Picking**.
4. Open Inventory > Remnants.
5. Configure category rules and remnant stock.

The module creates two internal warehouse locations:

- `WH/Stock`
- `WH/Remnants`

Seeded remnant records are stored in `WH/Remnants`.

The module seeds the five category rules from the workbook overview:

- Day & Night: widthwise, 2 layers.
- Translucent: widthwise, 1 layer.
- Silhouette: widthwise, 1 layer.
- Blackout: widthwise, 1 layer.
- Sunscreen: widthwise and heightwise, 1 layer.
