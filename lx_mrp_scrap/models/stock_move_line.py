# -*- coding: utf-8 -*-
from odoo import fields, models


class StockMoveLine(models.Model):
    _inherit = 'stock.move.line'

    lx_lot_width = fields.Float(
        string="Largeur rouleau (m)",
        digits=(10, 3),
    )

    def _action_done(self):
        res = super()._action_done()
        for ml in self:
            if ml.lx_lot_width and ml.lot_id and not ml.lot_id.lx_width:
                ml.lot_id.lx_width = ml.lx_lot_width
        return res
