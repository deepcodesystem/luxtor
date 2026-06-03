from odoo import api, fields, models


class FabricPickOption(models.Model):
    _name = "fabric.pick.option"
    _description = "Fabric Pick Option"
    _order = "production_id, sequence, id"

    name = fields.Char(compute="_compute_name", store=True)
    production_id = fields.Many2one(
        "mrp.production",
        required=True,
        ondelete="cascade",
        index=True,
    )
    product_id = fields.Many2one("product.product", required=True, ondelete="restrict")
    option_type = fields.Selection(
        [
            ("remnant", "Remnant"),
            ("lot", "Lot"),
        ],
        required=True,
    )
    remnant_id = fields.Many2one("remnant.stock", ondelete="cascade")
    lot_id = fields.Many2one("stock.lot", ondelete="cascade")
    display_label = fields.Char(required=True)
    dimension_minmax_label = fields.Char(string="Dimensions Min-Max")
    tooltip = fields.Text()
    orientation = fields.Selection(
        [
            ("widthwise", "Widthwise"),
            ("heightwise", "Heightwise"),
        ],
        string="Valid By / Orientation",
    )
    roll_width_m = fields.Float(string="Roll Width (m)")
    waste_area_m2 = fields.Float(string="Waste Area")
    remnant_area_m2 = fields.Float(string="Remnant Area")
    sequence = fields.Integer(default=10)
    is_recommended = fields.Boolean(default=False)
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
    )

    @api.depends("display_label", "is_recommended")
    def _compute_name(self):
        for option in self:
            prefix = "[Best] " if option.is_recommended else ""
            option.name = f"{prefix}{option.display_label or ''}"
