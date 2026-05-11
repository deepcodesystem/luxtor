# -*- coding: utf-8 -*-
import re
import math
import logging
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


def _round_up_to_half(value):
    try:
        v = float(value or 0.0)
    except Exception:
        return 0.0
    return math.ceil(v * 2.0) / 2.0


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    lx_width_m = fields.Float(string="Width", help="Width in metres.")
    lx_height_m = fields.Float(string="Height", help="Height in metres.")
    lx_final_unit_price = fields.Float(
        string="Website Final Unit Price",
        copy=False,
    )
    size = fields.Float(string='Size', compute='_compute_size', store=True)

    # ------------------------------------------------------------------
    # SIZE
    # ------------------------------------------------------------------
    @api.depends('lx_width_m', 'lx_height_m')
    def _compute_size(self):
        for line in self:
            if line.lx_width_m and line.lx_height_m:
                line.size = line.lx_width_m * line.lx_height_m
            else:
                line.size = 0.0

    @api.onchange('lx_width_m', 'lx_height_m')
    def _onchange_size(self):
        self._compute_size()

    # ------------------------------------------------------------------
    # AMOUNT OVERRIDE (m² pricing)
    # ------------------------------------------------------------------
    @api.depends(
        'size', 'product_uom_qty', 'discount', 'price_unit', 'tax_ids',
        'display_type', 'order_id.partner_id', 'order_id.currency_id',
    )
    def _compute_amount(self):
        for line in self:
            if line.display_type:
                line.update({'price_tax': 0.0, 'price_total': 0.0, 'price_subtotal': 0.0})
                continue
            qty_effective = (line.size or 1.0) * (line.product_uom_qty or 0.0)
            unit_price = (line.price_unit or 0.0) * (1 - (line.discount or 0.0) / 100.0)
            taxes = line.tax_ids.compute_all(
                unit_price,
                line.order_id.currency_id,
                qty_effective,
                product=line.product_id,
                partner=line.order_id.partner_id,
            )
            price_subtotal = taxes.get('total_excluded', 0.0)
            price_total = taxes.get('total_included', 0.0)
            line.update({
                'price_tax': price_total - price_subtotal,
                'price_total': price_total,
                'price_subtotal': price_subtotal,
            })

    def _prepare_base_line_for_taxes_computation(self, **kwargs):
        self.ensure_one()
        qty_eff = (self.size or 1.0) * (self.product_uom_qty or 0.0)
        return self.env['account.tax']._prepare_base_line_for_taxes_computation(
            self,
            **{
                'tax_ids': self.tax_ids,
                'quantity': qty_eff,
                'partner_id': self.order_id.partner_id,
                'currency_id': self.order_id.currency_id or self.order_id.company_id.currency_id,
                **kwargs,
            },
        )

    # ------------------------------------------------------------------
    # DIMENSION PRICING HELPERS
    # ------------------------------------------------------------------
    def _lx_price_area(self, width_m=None, height_m=None):
        self.ensure_one()
        width = float(width_m if width_m is not None else (self.lx_width_m or 0.0))
        height = float(height_m if height_m is not None else (self.lx_height_m or 0.0))
        return max(width, 1.0) * max(height, 1.0)

    def _lx_browser_factor(self):
        self.ensure_one()
        ICP = self.env['ir.config_parameter'].sudo()
        raw = ICP.get_param('luxtor.lx_browser_factor_pct', default='100')
        try:
            return float(raw or 100.0) / 100.0
        except Exception:
            return 1.0

    def _lx_find_bom_local(self, product):
        Bom = self.env['mrp.bom']
        bom = Bom.search([('product_id', '=', product.id)], order='sequence asc', limit=1)
        if bom:
            return bom
        return Bom.search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ('product_id', '=', False),
        ], order='sequence asc', limit=1)

    def _lx_extract_code_from_roller_name(self, name):
        if not name:
            return False
        m = re.search(r'\[([^\]]+)\]\s*Roller\s*Blind', name, flags=re.IGNORECASE)
        return m.group(1).strip() if m else False

    def _lx_find_fabric_by_ref_code(self, code):
        if not code:
            return self.env['product.template']
        return self.env['product.template'].search([('default_code', '=', code)], limit=1)

    def _lx_partner_rank_factor(self):
        partner = self.order_id.partner_id if self.order_id else False
        at = getattr(partner, 'lx_account_type_id', False) if partner else False
        if not at:
            return 1.0
        try:
            return float(at.rank) / 100.0 if at.rank else 1.0
        except Exception:
            return 1.0

    def _lx_virtual_total_for_width(self, product, width_m):
        bom = self._lx_find_bom_local(product)
        if not bom:
            return 0.0
        mo = self.env['mrp.production'].new({
            'company_id': (self.order_id.company_id.id if self.order_id else self.env.company.id),
            'product_id': product.id,
            'bom_id': bom.id,
            'lx_width_m': float(width_m or 1.0),
        })
        _cost, amount = mo._lx_virtual_calculate(width_m=float(width_m or 1.0))
        return amount

    def _lx_compute_price_unit_like_wizard(self):
        if not self.product_id:
            return 0.0
        base = self._lx_virtual_total_for_width(self.product_id, 1.00)
        return base * self._lx_partner_rank_factor()

    def _lx_compute_website_final_unit_price(self, width_m=None, height_m=None):
        self.ensure_one()
        if not self.product_id:
            return 0.0
        base_total = float(self._lx_virtual_total_for_width(self.product_id, 1.00) or 0.0)
        if base_total <= 0.0:
            return 0.0
        unit_virtual = math.ceil(base_total * self._lx_browser_factor())
        return unit_virtual * self._lx_price_area(width_m=width_m, height_m=height_m)

    def _lx_sync_dimension_website_price(self, final_unit_price=None, width_m=None, height_m=None):
        self.ensure_one()
        tmpl = self.product_template_id
        if not tmpl or not getattr(tmpl, 'is_dimension_product', False):
            return 0.0
        final_price = float(final_unit_price or 0.0)
        if final_price <= 0.0:
            final_price = float(self._lx_compute_website_final_unit_price(
                width_m=width_m, height_m=height_m,
            ) or 0.0)
        if final_price <= 0.0:
            return 0.0
        area = self._lx_price_area(width_m=width_m, height_m=height_m)
        rate = final_price / (area if area > 0.0 else 1.0)
        super(SaleOrderLine, self.with_context(lx_skip_dimension_reprice=True)).write({
            'price_unit': rate,
            'lx_final_unit_price': final_price,
        })
        return final_price

    # ------------------------------------------------------------------
    # VALIDATION
    # ------------------------------------------------------------------
    def _compute_max_height_from_width(self, tmpl, width_m):
        if not tmpl:
            return 0.0
        res = tmpl._lx_max_height_from_width(float(width_m or 0.0))
        return res.get(tmpl.id, 0.0)

    def _lx_validate_dimensions(self, width_m=None, height_m=None):
        self.ensure_one()
        tmpl = self.product_template_id
        if not tmpl or not getattr(tmpl, 'is_dimension_product', False):
            return

        _width_m = self.lx_width_m if width_m is None else float(width_m or 0.0)
        _height_m = self.lx_height_m if height_m is None else float(height_m or 0.0)

        if _width_m == 0.0 and _height_m == 0.0:
            return

        if _width_m <= 0 or _height_m <= 0:
            raise UserError(_("Width and height must be greater than zero."))
        if _width_m < 0.60:
            raise UserError(_("The width is out of range! Minimum width is 0.60 m."))

        max_w_m = 0.0
        code = self._lx_extract_code_from_roller_name(tmpl.name if tmpl else '')
        fabric = self._lx_find_fabric_by_ref_code(code) if code else self.env['product.template']
        if fabric and fabric.roller_width_ids:
            vals = [float(getattr(t, 'value_cm', 0.0) or 0.0) for t in fabric.roller_width_ids]
            vals = [v for v in vals if v > 0]
            if vals:
                max_w_m = max(vals) / 100.0
        if not max_w_m and tmpl and getattr(tmpl, 'width_cm', False):
            max_w_m = max(0.0, float(tmpl.width_cm or 0.0) / 100.0)
        if max_w_m and _width_m > max_w_m:
            raise UserError(_("The width is out of range! Maximum width is %.2f m.") % max_w_m)

        if _height_m < 0.90:
            raise UserError(_("The height is out of range! Minimum height is 0.90 m."))

        if _width_m and _width_m > 0:
            max_h_m = self._compute_max_height_from_width(tmpl, _width_m)
        else:
            max_h_m = float(getattr(tmpl, 'max_height', 0.0) or 0.0)
        if max_h_m and _height_m > max_h_m:
            raise UserError(_("The height is out of range! Maximum height is %.2f m.") % max_h_m)

    # ------------------------------------------------------------------
    # ONCHANGE
    # ------------------------------------------------------------------
    @api.onchange('lx_width_m', 'lx_height_m', 'product_id')
    def _onchange_dims_validate_and_reprice(self):
        for line in self:
            tmpl = line.product_template_id
            if not tmpl or not getattr(tmpl, 'is_dimension_product', False):
                continue
            line.price_unit = line._lx_compute_price_unit_like_wizard()

    # ------------------------------------------------------------------
    # WIZARD LAUNCHER
    # ------------------------------------------------------------------
    def action_open_dimension_wizard(self):
        self.ensure_one()
        tmpl = self.product_template_id or (self.product_id and self.product_id.product_tmpl_id)
        if not tmpl:
            raise UserError(_("Please select a product first."))
        if not getattr(tmpl, "is_dimension_product", False):
            raise UserError(_("This product is not a dimension-based product."))
        wiz = self.env['wizard.dimension.configurator'].create({
            'order_id': self.order_id.id,
            'order_line_id': self.id,
            'product_tmpl_id': tmpl.id,
            'dimension_unit': 'm',
            'width': (self.lx_width_m or 0.0),
            'height': (self.lx_height_m or 0.0),
            'quantity': self.product_uom_qty,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Configure Product Dimensions'),
            'res_model': 'wizard.dimension.configurator',
            'view_mode': 'form',
            'target': 'new',
            'res_id': wiz.id,
        }

    # ------------------------------------------------------------------
    # CREATE / WRITE GUARDS
    # ------------------------------------------------------------------
    @api.model
    def create(self, vals):
        line = super().create(vals)
        if self.env.context.get('lx_skip_dimension_reprice'):
            return line
        tmpl = line.product_template_id
        if tmpl and getattr(tmpl, 'is_dimension_product', False):
            if 'lx_width_m' in vals or 'lx_height_m' in vals:
                line._lx_validate_dimensions(
                    width_m=vals.get('lx_width_m', line.lx_width_m),
                    height_m=vals.get('lx_height_m', line.lx_height_m),
                )
                explicit_rate = float(vals.get('price_unit') or 0.0)
                explicit_final = float(vals.get('lx_final_unit_price') or 0.0)
                if explicit_final > 0.0:
                    line._lx_sync_dimension_website_price(
                        final_unit_price=explicit_final,
                        width_m=vals.get('lx_width_m', line.lx_width_m),
                        height_m=vals.get('lx_height_m', line.lx_height_m),
                    )
                elif explicit_rate > 0.0:
                    super(SaleOrderLine, line.with_context(lx_skip_dimension_reprice=True)).write({
                        'lx_final_unit_price': explicit_rate * line._lx_price_area(
                            width_m=vals.get('lx_width_m', line.lx_width_m),
                            height_m=vals.get('lx_height_m', line.lx_height_m),
                        ),
                    })
                else:
                    final_price = line._lx_sync_dimension_website_price(
                        width_m=vals.get('lx_width_m', line.lx_width_m),
                        height_m=vals.get('lx_height_m', line.lx_height_m),
                    )
                    if final_price <= 0.0:
                        line.price_unit = line._lx_compute_price_unit_like_wizard()
        return line

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('lx_skip_dimension_reprice'):
            return res
        dims_changed = any(k in vals for k in ('lx_width_m', 'lx_height_m'))
        # Guard for lx_motor_only_variant_id from electric module
        if 'lx_motor_only_variant_id' in self._fields and 'lx_motor_only_variant_id' in vals:
            dims_changed = True
        product_changed = 'product_id' in vals
        explicit_rate = float(vals.get('price_unit') or 0.0)
        explicit_final = float(vals.get('lx_final_unit_price') or 0.0)
        if not dims_changed and not product_changed and explicit_rate <= 0.0 and explicit_final <= 0.0:
            return res
        for line in self:
            tmpl = line.product_template_id
            if not tmpl or not getattr(tmpl, 'is_dimension_product', False):
                continue
            if explicit_final > 0.0:
                line._lx_sync_dimension_website_price(
                    final_unit_price=explicit_final,
                    width_m=vals.get('lx_width_m', line.lx_width_m),
                    height_m=vals.get('lx_height_m', line.lx_height_m),
                )
                continue
            if explicit_rate > 0.0:
                super(SaleOrderLine, line.with_context(lx_skip_dimension_reprice=True)).write({
                    'lx_final_unit_price': explicit_rate * line._lx_price_area(
                        width_m=vals.get('lx_width_m', line.lx_width_m),
                        height_m=vals.get('lx_height_m', line.lx_height_m),
                    ),
                })
                continue
            # Motor Only guard (electric module)
            if (
                line.product_id
                and hasattr(line.product_id, 'lx_is_motor_only_variant')
                and line.product_id.lx_is_motor_only_variant()
            ):
                if hasattr(line, '_lx_recalc_motor_only_price'):
                    line._lx_recalc_motor_only_price()
                continue
            line._lx_validate_dimensions(
                width_m=vals.get('lx_width_m', line.lx_width_m),
                height_m=vals.get('lx_height_m', line.lx_height_m),
            )
            final_price = line._lx_sync_dimension_website_price(
                width_m=vals.get('lx_width_m', line.lx_width_m),
                height_m=vals.get('lx_height_m', line.lx_height_m),
            )
            if final_price <= 0.0:
                line.price_unit = line._lx_compute_price_unit_like_wizard()
        return res

