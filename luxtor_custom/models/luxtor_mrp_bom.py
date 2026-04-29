import math
from odoo import api, fields, models


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    width_mrp = fields.Float(string="Width", help="BoM total width in meters")
    height_mrp = fields.Float(string="Height", help="BoM total height in meters")


    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)

    lx_total_cost_price = fields.Monetary(
        string="Total Cost Price",
        compute='_compute_lx_totals', store=True,
        currency_field='currency_id',
    )
    lx_total_amount = fields.Monetary(
        string="Total Amount",
        compute='_compute_lx_totals', store=True,
        currency_field='currency_id',
    )



    @api.depends('bom_line_ids.lx_cost_price', 'bom_line_ids.lx_amount')
    def _compute_lx_totals(self):
        for bom in self:
            total_cost = sum(line.lx_cost_price for line in bom.bom_line_ids)
            total_amount = sum(line.lx_amount for line in bom.bom_line_ids)
            bom.lx_total_cost_price = total_cost
            bom.lx_total_amount = total_amount

    
    # --- helper ---------------------------------------------------------------
    def _recalc_mounting_bracket_quantities(self, width_param=None):
        """Recompute quantities for mounting bracket lines based on width."""
        for bom in self:
            for line in bom.bom_line_ids:
                tmpl = line.product_id.product_tmpl_id
                if not getattr(tmpl, 'is_mounting_bracket', False):
                    continue

                # Prefer a per-line width if you store one; otherwise BoM width; otherwise param
                effective_width = (
                    getattr(line, 'line_width', None)
                    or bom.width_mrp
                    or width_param
                ) or 0.0

                # quantity = floor(((width - 0.3)/0.95) + 2), clamped at minimum 0
                qty = math.floor(((effective_width - 0.3) / 0.95) + 2)
                qty = max(qty, 0)

                if line.product_qty != qty:
                    line.write({'product_qty': qty})

    @api.onchange('width_mrp')
    def _onchange_width_mrp_recalc(self):
        self._recalc_mounting_bracket_quantities()

    def _lx_related_templates(self):
        templates = self.env['product.template']
        for bom in self:
            templates |= bom.product_tmpl_id
            templates |= bom.product_id.product_tmpl_id
        return templates.exists()

    @api.model_create_multi
    def create(self, vals_list):
        boms = super().create(vals_list)
        boms._recalc_mounting_bracket_quantities()
        boms._lx_related_templates()._lx_sync_lowest_manual_bom_price()
        return boms

    def write(self, vals):
        res = super(MrpBom, self).write(vals)
        if 'width_mrp' in vals and not self.env.context.get('lx_recalc_done'):
            self.with_context(lx_recalc_done=True)._recalc_mounting_bracket_quantities()
        if not self.env.context.get('lx_skip_auto_bom_price_sync'):
            self._lx_related_templates()._lx_sync_lowest_manual_bom_price()
        return res

    def unlink(self):
        templates = self._lx_related_templates()
        res = super().unlink()
        if not self.env.context.get('lx_skip_auto_bom_price_sync'):
            templates._lx_sync_lowest_manual_bom_price()
        return res

class MrpBomLine(models.Model):
    _inherit = 'mrp.bom.line'

    lx_unit_price = fields.Float(
        string='Unit Price',
        compute='_compute_lx_unit_price', store=True)

    lx_cost_price = fields.Monetary(
        string='Cost Price',
        compute='_compute_lx_cost_price', store=True,
        currency_field='currency_id')

    lx_waste_rate = fields.Float(
        string='Waste Rate',
        compute='_compute_lx_rates', store=True)

    lx_added_margin = fields.Float(
        string='Added Margin',
        compute='_compute_lx_rates', store=True)

    lx_amount = fields.Monetary(
        string='Amount',
        compute='_compute_lx_amount', store=True,
        currency_field='currency_id')

    currency_id = fields.Many2one(
        'res.currency', related='company_id.currency_id', readonly=True)

    @api.depends('product_id')
    def _compute_lx_unit_price(self):
        for line in self:
            line.lx_unit_price = line.product_id.standard_price or 0.0

    @api.depends('lx_unit_price', 'product_qty')
    def _compute_lx_cost_price(self):
        for line in self:
            line.lx_cost_price = (line.lx_unit_price or 0.0) * (line.product_qty or 0.0)

    @api.depends('product_id')
    def _compute_lx_rates(self):
        for line in self:
            tmpl = line.product_id.product_tmpl_id
            line.lx_waste_rate = tmpl.waste_rate if tmpl else 0.0
            line.lx_added_margin = tmpl.added_margin if tmpl else 0.0

    @api.depends('lx_cost_price', 'lx_waste_rate', 'lx_added_margin')
    def _compute_lx_amount(self):
        for line in self:
            factor = (line.lx_waste_rate or 0.0) + (line.lx_added_margin or 0.0)
            line.lx_amount = (line.lx_cost_price or 0.0) * factor

    def _lx_related_templates(self):
        templates = self.env['product.template']
        for line in self:
            templates |= line.bom_id.product_tmpl_id
            templates |= line.bom_id.product_id.product_tmpl_id
        return templates.exists()

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        lines._lx_related_templates()._lx_sync_lowest_manual_bom_price()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if not self.env.context.get('lx_skip_auto_bom_price_sync'):
            self._lx_related_templates()._lx_sync_lowest_manual_bom_price()
        return res

    def unlink(self):
        templates = self._lx_related_templates()
        res = super().unlink()
        if not self.env.context.get('lx_skip_auto_bom_price_sync'):
            templates._lx_sync_lowest_manual_bom_price()
        return res
