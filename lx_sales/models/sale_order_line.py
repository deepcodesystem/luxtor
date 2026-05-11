# -*- coding: utf-8 -*-
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.addons.lx_base.utils import (
    LX_MIN_WIDTH_M, LX_MIN_HEIGHT_M,
)

_logger = logging.getLogger(__name__)


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # ── Champs dimensions ─────────────────────────────────────────────────────
    lx_width_m = fields.Float(string="Width (m)", digits=(16, 4), default=0.0)
    lx_height_m = fields.Float(string="Height (m)", digits=(16, 4), default=0.0)

    is_dimension_product = fields.Boolean(
        related='product_id.product_tmpl_id.is_dimension_product',
        store=False,
    )

    size = fields.Float(
        string="Size (m²)",
        compute='_compute_size',
        store=True,
        digits=(16, 4),
    )

    # =========================================================================
    # COMPUTES
    # =========================================================================

    @api.depends('lx_width_m', 'lx_height_m')
    def _compute_size(self):
        for line in self:
            w = line.lx_width_m or 0.0
            h = line.lx_height_m or 0.0
            line.size = w * h if (w > 0 and h > 0) else 0.0

    @api.depends('lx_width_m', 'lx_height_m', 'product_uom_qty', 'price_unit', 'tax_ids', 'discount')
    def _compute_amount(self):
        # Déclenche le recalcul quand les dims changent — la vraie logique est dans _prepare_base_line
        return super()._compute_amount()

    def _prepare_base_line_for_taxes_computation(self, **kwargs):
        """Pour les produits dimensionnels : quantity = size × product_uom_qty."""
        self.ensure_one()
        res = super()._prepare_base_line_for_taxes_computation(**kwargs)
        if self.size > 0.0:
            res['quantity'] = self.size * (self.product_uom_qty or 0.0)
        return res

    # =========================================================================
    # VALIDATION DIMENSIONS
    # =========================================================================

    def lx_validate_dimensions(self, width_m=None, height_m=None):
        """Valide W et H selon les contraintes du template produit.
        Lève UserError si invalide."""
        self.ensure_one()
        tmpl = self.product_id.product_tmpl_id if self.product_id else False
        if not tmpl or not tmpl.is_dimension_product:
            return

        w = float(width_m if width_m is not None else (self.lx_width_m or 0.0))
        h = float(height_m if height_m is not None else (self.lx_height_m or 0.0))

        if w == 0.0 and h == 0.0:
            return
        if w <= 0 or h <= 0:
            raise UserError(_("Width and height must be greater than zero."))
        if w < LX_MIN_WIDTH_M:
            raise UserError(_("Minimum width is %.2f m.") % LX_MIN_WIDTH_M)
        if h < LX_MIN_HEIGHT_M:
            raise UserError(_("Minimum height is %.2f m.") % LX_MIN_HEIGHT_M)

        hints = tmpl.lx_dims_hints(width_m=w)
        max_w = hints.get('max_width_m', 0.0)
        max_h = hints.get('max_height_m', 0.0)
        if max_w and w > max_w:
            raise UserError(_("Maximum width is %.2f m.") % max_w)
        if max_h and h > max_h:
            raise UserError(_("Maximum height is %.2f m.") % max_h)

    # =========================================================================
    # CREATE / WRITE
    # =========================================================================

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if self.env.context.get('lx_skip_reprice'):
            return lines
        for line, vals in zip(lines, vals_list):
            if not line.product_id:
                continue
            if not line.product_id.product_tmpl_id.is_dimension_product:
                continue
            if vals.get('lx_width_m') or vals.get('lx_height_m'):
                line.lx_validate_dimensions()
        return lines

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('lx_skip_reprice'):
            return res
        if not any(k in vals for k in ('lx_width_m', 'lx_height_m', 'product_id')):
            return res
        for line in self:
            if not line.product_id:
                continue
            if not line.product_id.product_tmpl_id.is_dimension_product:
                continue
            line.lx_validate_dimensions()
        return res

