from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.remnant_fetching.picking_logic import (
    PickingInput,
    RemnantInput,
    best_fit_for_remnant,
)

from ..roll_orientation_logic import RollInput, RollInputCandidate, best_roll_fit, roll_fit_results


class MrpProduction(models.Model):
    _inherit = "mrp.production"

    fabric_category_rule_id = fields.Many2one(
        "remnant.category.rule",
        string="Fabric Category",
        compute="_compute_fabric_defaults",
        store=True,
        readonly=False,
    )
    fabric_order_width_m = fields.Float(
        string="Fabric Width (m)",
        compute="_compute_fabric_defaults",
        store=True,
        readonly=False,
    )
    fabric_order_height_m = fields.Float(
        string="Fabric Height (m)",
        compute="_compute_fabric_defaults",
        store=True,
        readonly=False,
    )
    fabric_layer_count = fields.Integer(
        string="Layer Count",
        compute="_compute_fabric_defaults",
        store=True,
        readonly=False,
    )
    fabric_tolerance = fields.Float(
        string="Remnant Tolerance",
        compute="_compute_fabric_defaults",
        store=True,
        readonly=False,
    )
    fabric_allowance_m = fields.Float(
        string="Fabric Allowance (m)",
        default=0.20,
        help="Roll selector allowance from the workbook. Default is 20 cm.",
    )
    fabric_pick_option_ids = fields.One2many(
        "fabric.pick.option",
        "production_id",
        string="Fabric Pick Options",
        readonly=True,
    )
    fabric_pick_option_id = fields.Many2one(
        "fabric.pick.option",
        string="Recommended Remnant / Lot",
        domain="[('production_id', '=', id)]",
        copy=False,
    )
    fabric_pick_tooltip = fields.Text(
        string="Selection Details",
        related="fabric_pick_option_id.tooltip",
        readonly=True,
    )
    fabric_selected_remnant_id = fields.Many2one(
        "remnant.stock",
        string="Selected Remnant",
        related="fabric_pick_option_id.remnant_id",
        readonly=True,
    )
    fabric_selected_lot_id = fields.Many2one(
        "stock.lot",
        string="Selected Lot",
        related="fabric_pick_option_id.lot_id",
        readonly=True,
    )

    @api.depends("product_id", "product_qty")
    def _compute_fabric_defaults(self):
        Rule = self.env["remnant.category.rule"]
        for production in self:
            rule = False
            product_category = production.product_id.categ_id
            if product_category:
                category_ids = []
                category = product_category
                while category:
                    category_ids.append(category.id)
                    category = category.parent_id
                rule = Rule.search([("product_category_id", "in", category_ids)], limit=1)
                if not rule:
                    rule = Rule.search([("name", "=", product_category.name)], limit=1)
            production.fabric_category_rule_id = rule
            production.fabric_layer_count = rule.layer_count if rule else 1
            production.fabric_tolerance = rule.tolerance if rule else 1.5
            production.fabric_order_width_m = production.fabric_order_width_m or 0.0
            production.fabric_order_height_m = production.fabric_order_height_m or 0.0

    def action_compute_fabric_pick_options(self):
        for production in self:
            production._compute_fabric_pick_options()
        return True

    def _compute_fabric_pick_options(self):
        self.ensure_one()
        if not self.product_id:
            raise UserError("Set a product before computing fabric options.")
        if not self.fabric_category_rule_id:
            raise UserError("Set a fabric category before computing fabric options.")
        if self.fabric_order_width_m <= 0 or self.fabric_order_height_m <= 0:
            raise UserError("Set fabric width and fabric height before computing fabric options.")

        self.fabric_pick_option_ids.unlink()
        remnant_options = self._prepare_remnant_options()
        if remnant_options:
            options = self.env["fabric.pick.option"].create(remnant_options)
            best = min(options, key=lambda option: (option.remnant_area_m2, option.sequence, option.id))
            options.write({"is_recommended": False})
            best.write({"is_recommended": True})
            self.fabric_pick_option_id = best
            return

        lot_options = self._prepare_lot_options()
        if lot_options:
            options = self.env["fabric.pick.option"].create(lot_options)
            best = min(options, key=lambda option: (option.waste_area_m2, option.roll_width_m, option.id))
            options.write({"is_recommended": False})
            best.write({"is_recommended": True})
            self.fabric_pick_option_id = best
            return

        self.fabric_pick_option_id = False
        raise UserError("No suitable remnant or fabric roll lot is available for this manufacturing order.")

    def _prepare_remnant_options(self):
        self.ensure_one()
        picking = PickingInput(
            order_width=self.fabric_order_width_m,
            order_height=self.fabric_order_height_m,
            tolerance=self.fabric_tolerance,
            layer_count=self.fabric_layer_count,
            rule_orientation=self.fabric_category_rule_id.orientation,
        )
        domain = [
            ("state", "=", "available"),
            ("company_id", "=", self.company_id.id),
            ("product_id", "=", self.product_id.id),
            ("category_rule_id", "=", self.fabric_category_rule_id.id),
            ("usable_layer_count", ">=", self.fabric_layer_count),
        ]
        options = []
        remnants = self.env["remnant.stock"].search(domain, order="name asc")
        for sequence, remnant in enumerate(remnants, start=1):
            result = best_fit_for_remnant(
                picking,
                RemnantInput(
                    remnant_id=remnant.name,
                    fabric_width=remnant.width_m,
                    fabric_height=remnant.height_m,
                    sequence=sequence,
                ),
            )
            if not result:
                continue
            label = "%s | Color %s | %s | W.%.2f * H.%.2f" % (
                remnant.product_id.display_name,
                self._get_product_color(remnant.product_id),
                remnant.name,
                remnant.width_m,
                remnant.height_m,
            )
            dimension_minmax = "W.%.2f-%.2f * H.%.2f-%.2f" % (
                result.min_width,
                result.max_width,
                result.min_height,
                result.max_height,
            )
            tooltip = "\n".join(
                [
                    "Remnant",
                    "Product: %s" % remnant.product_id.display_name,
                    "Color: %s" % self._get_product_color(remnant.product_id),
                    "Remnant: %s" % remnant.name,
                    "Size: W.%.2f * H.%.2f" % (remnant.width_m, remnant.height_m),
                    "Dimensions Min-Max: %s" % dimension_minmax,
                    "Orientation: %s" % result.calculation,
                ]
            )
            options.append(
                {
                    "production_id": self.id,
                    "product_id": self.product_id.id,
                    "option_type": "remnant",
                    "remnant_id": remnant.id,
                    "display_label": label,
                    "dimension_minmax_label": dimension_minmax,
                    "tooltip": tooltip,
                    "orientation": result.calculation,
                    "remnant_area_m2": result.area,
                    "sequence": sequence,
                    "company_id": self.company_id.id,
                }
            )
        return options

    def _prepare_lot_options(self):
        self.ensure_one()
        lots = self.env["stock.lot"].search(
            [
                ("product_id", "=", self.product_id.id),
                ("company_id", "in", [False, self.company_id.id]),
                ("is_fabric_roll", "=", True),
                ("roll_width_m", ">", 0),
            ],
            order="name asc",
        )
        roll_input = RollInput(
            order_width=self.fabric_order_width_m,
            order_height=self.fabric_order_height_m,
            layer_count=self.fabric_layer_count,
            rule_orientation=self.fabric_category_rule_id.orientation,
            fabric_allowance_m=self.fabric_allowance_m,
        )
        lot_candidates = [
            RollInputCandidate(
                lot_id=lot.id,
                lot_name=lot.name,
                roll_width_m=lot.roll_width_m,
                sequence=index,
            )
            for index, lot in enumerate(lots, start=1)
        ]
        best_by_lot = {}
        for result in roll_fit_results(roll_input, lot_candidates):
            current = best_by_lot.get(result.lot_id)
            if not current or (
                result.waste_area_m2,
                result.roll_width_m,
                result.orientation,
            ) < (
                current.waste_area_m2,
                current.roll_width_m,
                current.orientation,
            ):
                best_by_lot[result.lot_id] = result

        options = []
        lot_by_id = {lot.id: lot for lot in lots}
        for result in sorted(best_by_lot.values(), key=lambda item: item.sequence):
            lot = lot_by_id[result.lot_id]
            label = "%s | %s | Roll W.%.2f | %s" % (
                lot.product_id.display_name,
                lot.name,
                lot.roll_width_m,
                result.orientation,
            )
            tooltip = "\n".join(
                [
                    "Lot",
                    "Product: %s" % lot.product_id.display_name,
                    "Color: %s" % (lot.fabric_color or self._get_product_color(lot.product_id)),
                    "Roll Width: %.2f m" % lot.roll_width_m,
                    "Orientation: %s" % result.orientation,
                    "Waste: %.3f m2" % result.waste_area_m2,
                ]
            )
            options.append(
                {
                    "production_id": self.id,
                    "product_id": self.product_id.id,
                    "option_type": "lot",
                    "lot_id": lot.id,
                    "display_label": label,
                    "tooltip": tooltip,
                    "orientation": result.orientation,
                    "roll_width_m": lot.roll_width_m,
                    "waste_area_m2": result.waste_area_m2,
                    "sequence": result.sequence,
                    "company_id": self.company_id.id,
                }
            )
        return options

    def _get_product_color(self, product):
        if product.fabric_color:
            return product.fabric_color
        color_values = product.product_template_attribute_value_ids.filtered(
            lambda value: value.attribute_id.name.lower() == "color"
        )
        return ", ".join(color_values.mapped("name")) or ""
