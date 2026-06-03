from odoo import api, fields, models
from odoo.exceptions import UserError


class SaleOrderLine(models.Model):
    _inherit = "sale.order.line"

    remnant_category_rule_id = fields.Many2one(
        "remnant.category.rule",
        string="Remnant Category",
        compute="_compute_remnant_defaults",
        store=True,
        readonly=False,
    )
    remnant_required_length_m = fields.Float(
        string="Required Length (m)",
        compute="_compute_remnant_defaults",
        store=True,
        readonly=False,
    )
    remnant_required_width_m = fields.Float(
        string="Required Width (m)",
        compute="_compute_remnant_defaults",
        store=True,
        readonly=False,
    )
    remnant_required_height_m = fields.Float(
        string="Required Height (m)",
        compute="_compute_remnant_defaults",
        store=True,
        readonly=False,
    )
    remnant_orientation = fields.Selection(
        [
            ("widthwise", "Widthwise"),
            ("heightwise", "Heightwise"),
        ],
        compute="_compute_remnant_defaults",
        store=True,
        readonly=False,
    )
    remnant_required_layer_count = fields.Integer(
        compute="_compute_remnant_defaults",
        store=True,
        readonly=False,
    )
    remnant_tolerance = fields.Float(
        compute="_compute_remnant_defaults",
        store=True,
        readonly=False,
    )
    remnant_fetch_request_id = fields.Many2one(
        "remnant.fetch.request",
        string="Remnant Picking",
        readonly=True,
        copy=False,
    )
    selected_remnant_id = fields.Many2one(
        "remnant.stock",
        string="Selected Remnant",
        related="remnant_fetch_request_id.best_remnant_id",
        store=True,
    )

    @api.depends("product_id", "product_uom_qty")
    def _compute_remnant_defaults(self):
        Rule = self.env["remnant.category.rule"]
        for line in self:
            rule = False
            product_category = line.product_id.categ_id
            if product_category:
                category_ids = []
                category = product_category
                while category:
                    category_ids.append(category.id)
                    category = category.parent_id
                rule = Rule.search([("product_category_id", "in", category_ids)], limit=1)
                if not rule:
                    rule = Rule.search([("name", "=", product_category.name)], limit=1)
            line.remnant_category_rule_id = rule
            line.remnant_tolerance = rule.tolerance if rule else 1.5
            line.remnant_required_layer_count = rule.layer_count if rule else 1
            line.remnant_orientation = "widthwise"
            line.remnant_required_length_m = line.product_uom_qty or 0.0
            line.remnant_required_width_m = line.product_uom_qty or 0.0
            line.remnant_required_height_m = line.product_uom_qty or 0.0

    def action_pick_best_remnant(self):
        Request = self.env["remnant.fetch.request"]
        for line in self:
            if not line.remnant_category_rule_id:
                raise UserError("Set a remnant category before picking stock.")
            request = Request.create(
                {
                    "sale_line_id": line.id,
                    "product_id": line.product_id.id,
                    "category_rule_id": line.remnant_category_rule_id.id,
                    "required_length_m": line.remnant_required_length_m,
                    "required_width_m": line.remnant_required_width_m,
                    "required_height_m": line.remnant_required_height_m,
                    "tolerance": line.remnant_tolerance,
                    "required_layer_count": line.remnant_required_layer_count,
                    "orientation": line.remnant_orientation,
                    "company_id": line.company_id.id,
                }
            )
            line.remnant_fetch_request_id = request
        return True

    def action_fetch_best_remnant(self):
        return self.action_pick_best_remnant()
