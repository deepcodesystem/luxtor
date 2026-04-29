# -*- coding: utf-8 -*-
from datetime import datetime, time
from dateutil.relativedelta import relativedelta
from odoo import api, fields, models, _
import logging
from odoo.exceptions import UserError
import math

# ===========================
#   SALE ORDER LINE
# ===========================

_logger = logging.getLogger(__name__)


def _round_up_to_half(value):
    """
    Round UP to the next 0.5 step.
    Examples:
      1.2 -> 1.5
      1.7 -> 2.0
      2.0 -> 2.0
    """
    try:
        v = float(value or 0.0)
    except Exception:
        return 0.0
    return math.ceil(v * 2.0) / 2.0


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    sequence_number = fields.Char(
        string='Line Sequence', readonly=True, copy=False,
        help="Auto-generated sequence number for goods and combo products. "
             "Service products are marked with '#'."
    )

    lx_width_m = fields.Float(
        string="Width",
        help="Width of the configured product expressed in metres."
    )
    lx_height_m = fields.Float(
        string="Height",
        help="Height of the configured product expressed in metres."
    )
    lx_final_unit_price = fields.Float(
        string="Website Final Unit Price",
        copy=False,
        help="Final configured website price for one product unit before cart quantity."
    )

    size = fields.Float(string='Size', compute='_compute_size', store=True)

    is_priority_line = fields.Boolean(
        string='Priority Service Line', default=False,
        help="Indicates that this line was created by the priority wizard.")
    is_installation_line = fields.Boolean(
        string='Installation Service Line', default=False,
        help="Indicates that this line was created by the installation wizard.")
    is_shipping_line = fields.Boolean(default=False, index=True)
    is_free_shipping_line = fields.Boolean(default=False, index=True)

    is_mounting_bracket = fields.Boolean(string="Mounting Bracket")
    is_ceiling_clip = fields.Boolean(string="Ceiling Clip")
    waste_rate = fields.Float(string="Waste Rate (%)")
    added_margin = fields.Float(string="Added Margin (%)")

    # ---------------------  size logic ---------------------
    @api.depends('lx_width_m', 'lx_height_m')
    def _compute_size(self):
        for line in self:
            if line.lx_width_m and line.lx_height_m:
                line.size = line.lx_width_m * line.lx_height_m  # m²
            else:
                line.size = 0.0

    @api.onchange('lx_width_m', 'lx_height_m')
    def _onchange_size(self):
        self._compute_size()

    def _lx_is_electric_accessory(self):
        self.ensure_one()
        pt = self.product_id.product_tmpl_id
        return bool(
            pt.lx_is_remote_control
            or pt.lx_is_zigbee_gateway
            or pt.lx_is_electric_charger
            or pt.lx_is_solar_charger
            or pt.lx_is_tubular_motor
        )
    
    def _lx_partner_vendor_markdown(self):
        partner = self.order_id.partner_id
        if not partner:
            return 0.0

        at = partner.lx_account_type_id
        if not at:
            return 0.0

        return float(partner.lx_vendor_markdown or 0.0)
    
    def _lx_apply_vendor_markdown(self):
        for line in self:

            if not line.product_id:
                continue

            if not line._lx_is_electric_accessory():
                continue

            markdown = line._lx_partner_vendor_markdown()

            if not markdown:
                continue

            base_price = float(line.price_unit or 0.0)

            new_price = base_price * (1.0 - markdown / 100.0)

            line.price_unit = new_price

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
                width_m=width_m, height_m=height_m
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

    # ---------------------  amount logic  -------------------
    # Odoo 19: taxes field on sale.order.line is `tax_ids` (not `tax_id`)
    @api.depends(
        'size', 'product_uom_qty', 'discount', 'price_unit', 'tax_ids',
        'display_type', 'order_id.partner_id', 'order_id.currency_id'
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

            # Apply "round up by half" to computed amounts
            price_subtotal = taxes.get('total_excluded', 0.0)
            price_total = taxes.get('total_included', 0.0)
            price_tax = price_total - price_subtotal

            line.update({
                'price_tax': price_tax,
                'price_total': price_total,
                'price_subtotal': price_subtotal,
            })

    # --------------------- Wizard launcher -------------------------
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
            'width':  (self.lx_width_m or 0.0),
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

    # ======================  mirror wizard logic ===========================

    # --- Local BoM finder (variant first, then template) ---
    def _lx_find_bom_local(self, product):
        Bom = self.env['mrp.bom']
        bom = Bom.search([('product_id', '=', product.id)], order='sequence asc', limit=1)
        if bom:
            return bom
        return Bom.search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ('product_id', '=', False),
        ], order='sequence asc', limit=1)

    # --- Extract fabric code from roller name "[CODE] Roller Blind" ---
    def _lx_extract_code_from_roller_name(self, name):
        if not name:
            return False
        import re
        m = re.search(r'\[([^\]]+)\]\s*Roller\s*Blind', name, flags=re.IGNORECASE)
        return m.group(1).strip() if m else False

    # --- Find Fabric by exact default_code ---
    def _lx_find_fabric_by_ref_code(self, code):
        if not code:
            return self.env['product.template']
        return self.env['product.template'].search([('default_code', '=', code)], limit=1)

    # --- Partner Account Type factor: 1 + rank% ---
    def _lx_partner_rank_factor(self):
        partner = self.order_id.partner_id if self.order_id else False
        at = partner.lx_account_type_id if partner else False
        if not at:
            return 1.0
        try:
            return float(at.rank) / 100.0 if at.rank else 1.0
        except Exception:
            return 1.0

    # --- Max-height from Mechanism 'MS' + lx_weight (same as wizard) ---
    def _compute_max_height_from_width(self, tmpl, width_m):
        if not tmpl:
            return 0.0
        divisor = 1.0
        cat = tmpl.categ_id
        if cat and "Day & Night" in (cat.name or ""):
            divisor = 2.0

        fabric = getattr(tmpl, 'lx_fabric_ref_id', False)
        weight = float((getattr(fabric, 'lx_weight', 0.0) or getattr(tmpl, 'lx_weight', 0.0) or 0.0))

        mech = self.env['product.template'].search([('default_code', '=', 'MS')], limit=1)
        load = float(getattr(mech, 'maximum_load', 0.0) or 0.0)

        width_cm = max(0.0, float(width_m or 0.0) * 100.0)
        if width_cm <= 0.0 or weight <= 0.0 or load <= 0.0 or divisor <= 0.0:
            return 0.0

        h_m = (load / (width_cm * weight)) / divisor * 100000.0
        return max(0.0, round(h_m, 4))

    # --- Virtual MO total (width_m passed to MO as in wizard) ---
    def _lx_virtual_total_for_width(self, product, width_m):
        Mrp = self.env['mrp.production']
        bom = self._lx_find_bom_local(product)
        if not bom:
            return 0.0
        mo = Mrp.new({
            'company_id': (self.order_id.company_id.id if self.order_id else self.env.company.id),
            'product_id': product.id,
            'bom_id': bom.id,
            'lx_width_m': width_m,
        })
        _cost, amount = mo._lx_virtual_calculate(width_m=width_m)
        return amount

    def _lx_virtual_total_for_width_lowest_no_motor(self, product, width_m):
        Mrp = self.env['mrp.production']
        bom = self._lx_find_bom_local(product)
        if not bom:
            return 0.0
        mo = Mrp.new({
            'company_id': (self.order_id.company_id.id if self.order_id else self.env.company.id),
            'product_id': product.id,
            'bom_id': bom.id,
            'lx_width_m': width_m,
        })
        _cost, amount = mo._lx_virtual_calculate_lowest_no_motor(width_m=width_m)
        return amount

    # --- Price unit like wizard: ceil( virtual_total(width=1.00) * factor ) ---
    # Updated: round UP by 0.5 steps (instead of integer ceil)
    def _lx_compute_price_unit_like_wizard(self):
        if not self.product_id:
            return 0.0
        base = self._lx_virtual_total_for_width(self.product_id, 1.00)
        return base * self._lx_partner_rank_factor()

    def _lx_validate_dimensions(self, width_m=None, height_m=None):
        self.ensure_one()

        tmpl = self.product_template_id
        if not tmpl or not getattr(tmpl, 'is_dimension_product', False):
            return  # only dimension products are validated

        _width_m = self.lx_width_m if width_m is None else float(width_m or 0.0)
        _height_m = self.lx_height_m if height_m is None else float(height_m or 0.0)

        #  Skip validation if both width and height are zero (initial state)
        if _width_m == 0.0 and _height_m == 0.0:
            return

        # --- Validation rules ---
        if _width_m <= 0 or _height_m <= 0:
            raise UserError(_("Width and height must be greater than zero."))

        if _width_m < 0.60:
            raise UserError(_("The width is out of range! Minimum width is 0.60 m."))

        # Max width from Fabric by strict default_code; fallback to template width_cm
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

        # Max height dynamic (Mechanism 'MS' + lx_weight)
        if _width_m and _width_m > 0:
            max_h_m = self._compute_max_height_from_width(tmpl, _width_m)
        else:
            max_h_m = float(getattr(tmpl, 'max_height', 0.0) or 0.0)

        if max_h_m and _height_m > max_h_m:
            raise UserError(_("The height is out of range! Maximum height is %.2f m.") % max_h_m)

    # --- Onchange: validate + reprice like the wizard when dims change ---
    @api.onchange('lx_width_m', 'lx_height_m', 'product_id')
    def _onchange_dims_validate_and_reprice(self):
        for line in self:
            tmpl = line.product_template_id
            if not tmpl or not getattr(tmpl, 'is_dimension_product', False):
                continue
            # Validate (raises on error → UI shows the message and blocks)
            # line._lx_validate_dimensions()
            # Reprice like wizard
            line.price_unit = line._lx_compute_price_unit_like_wizard()
            line._lx_apply_vendor_markdown()

    # --- Server-side guardrails on create/write ---
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
                        line._lx_apply_vendor_markdown()
        return line

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get('lx_skip_dimension_reprice'):
            return res
        dims_changed = any(k in vals for k in (
            'lx_width_m', 'lx_height_m', 'lx_motor_only_variant_id'
        ))
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
            # Motor Only lines: price depends on the selected motor's idler.
            # _lx_recalc_motor_only_price (from the Electric write) is
            # idler-aware; _lx_compute_price_unit_like_wizard is not.
            # Use _lx_recalc_motor_only_price for Motor Only lines so the
            # correct single-idler cost is used in all cases (variant change,
            # width change, etc.).
            if (line.product_id
                    and hasattr(line.product_id, 'lx_is_motor_only_variant')
                    and line.product_id.lx_is_motor_only_variant()):
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
                line._lx_apply_vendor_markdown()
        return res

    def _prepare_base_line_for_taxes_computation(self, **kwargs):
        self.ensure_one()
        qty_eff = (self.size or 1.0) * (self.product_uom_qty or 0.0)
        return self.env['account.tax']._prepare_base_line_for_taxes_computation(
            self,
            **{
                'tax_ids': self.tax_ids,  # Odoo 19: was tax_id
                'quantity': qty_eff,
                'partner_id': self.order_id.partner_id,
                'currency_id': self.order_id.currency_id or self.order_id.company_id.currency_id,
                **kwargs,
            },
        )


