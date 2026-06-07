# -*- coding: utf-8 -*-
import math
from odoo import api, fields, models


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    width_mrp = fields.Float(string="Width (m)", help="Largeur BoM en mètres")
    height_mrp = fields.Float(string="Height (m)", help="Hauteur BoM en mètres")

    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True,
    )
    lx_total_cost_price = fields.Monetary(
        string="Total Cost Price",
        compute='_compute_lx_totals',
        store=True,
        currency_field='currency_id',
    )
    lx_total_amount = fields.Monetary(
        string="Total Amount",
        compute='_compute_lx_totals',
        store=True,
        currency_field='currency_id',
    )

    @api.depends('bom_line_ids.lx_cost_price', 'bom_line_ids.lx_amount')
    def _compute_lx_totals(self):
        for bom in self:
            bom.lx_total_cost_price = sum(l.lx_cost_price for l in bom.bom_line_ids)
            bom.lx_total_amount = sum(l.lx_amount for l in bom.bom_line_ids)

    # ── Recalcul supports (brackets) ──────────────────────────────────────────

    def _recalc_mounting_bracket_quantities(self, width_param=None):
        for bom in self:
            for line in bom.bom_line_ids:
                tmpl = line.product_id.product_tmpl_id
                if not getattr(tmpl, 'is_mounting_bracket', False):
                    continue
                w = float(width_param or bom.width_mrp or 0.0)
                qty = max(math.floor(((w - 0.3) / 0.95) + 2), 0) if w else 0
                if line.product_qty != qty:
                    line.product_qty = qty

    @api.onchange('width_mrp')
    def _onchange_width_mrp_recalc(self):
        self._recalc_mounting_bracket_quantities()

    @api.model_create_multi
    def create(self, vals_list):
        boms = super().create(vals_list)
        boms._recalc_mounting_bracket_quantities()
        return boms

    def write(self, vals):
        res = super().write(vals)
        if 'width_mrp' in vals and not self.env.context.get('lx_recalc_done'):
            self.with_context(lx_recalc_done=True)._recalc_mounting_bracket_quantities()
        return res


class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True,
    )
    lx_unit_price = fields.Float(
        string='Unit Price',
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
        for line in self:
            product = line.product_id
            if not product and hasattr(line, 'component_template_id') and line.component_template_id:
                product = line.component_template_id.product_variant_ids[:1]
            line.lx_unit_price = product.lx_adjusted_cost or 0.0

    @api.depends('lx_unit_price', 'product_qty')
    def _compute_lx_cost_price(self):
        for line in self:
            line.lx_cost_price = (line.lx_unit_price or 0.0) * (line.product_qty or 0.0)

    @api.depends('lx_cost_price')
    def _compute_lx_amount(self):
        for line in self:
            line.lx_amount = line.lx_cost_price or 0.0

