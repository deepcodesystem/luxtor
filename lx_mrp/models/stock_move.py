# -*- coding: utf-8 -*-
import math
from odoo import api, fields, models


def _truncate2(v):
    return math.floor((v or 0.0) * 100.0) / 100.0


class StockMove(models.Model):
    _inherit = 'stock.move'

    # Snapshot quantité BoM à la création
    lx_bom_uom_qty = fields.Float(
        string="BoM Qty (snapshot)",
        digits='Product Unit of Measure',
        help="Quantité issue de l'explosion BoM, capturée à la création.",
    )

    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True,
    )
    lx_unit_price = fields.Float(
        string='Cost Unit Price',
        compute='_compute_lx_unit_price',
        store=True,
        help="Coût unitaire ajusté = lx_adjusted_cost du produit (inclut waste_rate + added_margin).",
    )
    lx_cost_price = fields.Monetary(
        string='Cost Price',
        compute='_compute_lx_cost_price',
        store=True,
        currency_field='currency_id',
    )
    lx_amount = fields.Monetary(
        string='Amount',
        compute='_compute_lx_amount',
        store=True,
        currency_field='currency_id',
    )

    @api.depends('product_id')
    def _compute_lx_unit_price(self):
        for m in self:
            m.lx_unit_price = m.product_id.lx_adjusted_cost or 0.0

    @api.depends('lx_unit_price', 'product_uom_qty')
    def _compute_lx_cost_price(self):
        for m in self:
            m.lx_cost_price = _truncate2((m.lx_unit_price or 0.0) * (m.product_uom_qty or 0.0))

    @api.depends('lx_cost_price')
    def _compute_lx_amount(self):
        for m in self:
            m.lx_amount = m.lx_cost_price or 0.0

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if 'lx_bom_uom_qty' not in vals:
                vals['lx_bom_uom_qty'] = float(vals.get('product_uom_qty') or 0.0)
        return super().create(vals_list)

