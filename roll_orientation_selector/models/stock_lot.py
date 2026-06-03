from odoo import api, fields, models


class StockLot(models.Model):
    _inherit = "stock.lot"

    is_fabric_roll = fields.Boolean(
        string="Fabric Roll",
        help="Enable when this lot is an available fabric roll for roll/orientation selection.",
    )
    roll_width_m = fields.Float(
        string="Roll Width (m)",
        help="Physical roll width in meters, for example 2.00, 2.50, or 3.00.",
    )
    fabric_color = fields.Char(string="Fabric Color")
    roll_selector_label = fields.Char(
        string="Roll Selector Label",
        compute="_compute_roll_selector_label",
        store=True,
    )

    @api.depends("name", "product_id", "fabric_color", "roll_width_m")
    def _compute_roll_selector_label(self):
        for lot in self:
            lot_color = lot.fabric_color or lot.product_id.fabric_color
            color = f", {lot_color}" if lot_color else ""
            width = f", W.{lot.roll_width_m:.2f}" if lot.roll_width_m else ""
            lot.roll_selector_label = f"{lot.name or ''}: {lot.product_id.display_name or ''}{color}{width}"
