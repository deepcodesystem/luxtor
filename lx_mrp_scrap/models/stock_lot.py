# -*- coding: utf-8 -*-
from odoo import api, fields, models


class StockLot(models.Model):
    _inherit = 'stock.lot'

    lx_width = fields.Float(
        string="Largeur rouleau (m)",
        digits=(10, 3),
    )
    lx_is_scrap = fields.Boolean(
        string="Chute réutilisable",
        default=False,
    )
    lx_origin_production_id = fields.Many2one(
        'mrp.production',
        string="OF d'origine",
        ondelete='set null',
    )
