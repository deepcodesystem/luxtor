# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import math
import logging
_logger = logging.getLogger(__name__)


class WizardDimensionConfigurator(models.TransientModel):
    _name = "wizard.dimension.configurator"
    _description = "Dimension Configurator Wizard"

    order_id = fields.Many2one("sale.order", required=True, readonly=True)
    order_line_id = fields.Many2one("sale.order.line", string="Order Line", required=True, readonly=True)

    product_tmpl_id = fields.Many2one("product.template", string="Product Template", required=True, readonly=True)
    product_id = fields.Many2one("product.product", string="Product Variant", readonly=True, compute="_compute_product_from_line", store=True)

    quantity = fields.Float(string="Quantity", default=1.0, help="Quantity to set on the sale order line.")

    dimension_unit = fields.Selection([("m","m"),("cm","cm"),("mm","mm")], default="m", string="Unit", required=True)
    width  = fields.Float(string="Width",  default=0.0)
    height = fields.Float(string="Height", default=0.0)

    width_m  = fields.Float(string="Width (m)",  compute="_compute_dimensions_and_placeholders", readonly=True)
    height_m = fields.Float(string="Height (m)", compute="_compute_dimensions_and_placeholders", readonly=True)

    width_placeholder  = fields.Char(string="Width Hint",  compute="_compute_dimensions_and_placeholders", readonly=True)
    height_placeholder = fields.Char(string="Height Hint", compute="_compute_dimensions_and_placeholders", readonly=True)

    price_preview = fields.Monetary(string="Price Unit", currency_field="currency_id", readonly=True)
    currency_id   = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id.id, readonly=True)

    # ---------- utils ----------
    def _convert_from_meters(self, value_m, unit):
        if unit == 'm':
            return value_m
        if unit == 'cm':
            return value_m * 100.0
        if unit == 'mm':
            return value_m * 1000.0
        return value_m

    def _fmt_unit(self, value_m, unit):
        v = self._convert_from_meters(value_m or 0.0, unit)
        decimals = 2 if unit == 'm' else 0
        return f"{v:.{decimals}f} {unit}"

    def _convert_to_meters(self, value, unit):
        try:
            v = float(value) if value is not None else 0.0
        except Exception:
            v = 0.0
        return v if unit == 'm' else (v/100.0 if unit == 'cm' else v/1000.0)

    def _lx_find_bom(self, product):
        Bom = self.env['mrp.bom']
        bom = Bom.search([('product_id', '=', product.id)], order='sequence asc', limit=1)
        if bom:
            return bom
        return Bom.search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ('product_id', '=', False),
        ], order='sequence asc', limit=1)

    def _lx_get_partner_pricelist(self, order):
        partner_pl = order.partner_id.property_product_pricelist
        return partner_pl or order.pricelist_id

    def _lx_pick_pricelist_item(self, pricelist, product):
        if not pricelist:
            return None
        items = pricelist.item_ids
        if not items:
            return None
        exact = items.filtered(lambda it: it.product_id and it.product_id.id == product.id)
        if exact:
            return exact[0]
        tmpl = items.filtered(lambda it: it.product_tmpl_id and it.product_tmpl_id.id == product.product_tmpl_id.id)
        if tmpl:
            return tmpl[0]
        generic = items.filtered(lambda it: not it.product_id and not it.product_tmpl_id and not it.categ_id)
        if generic:
            return generic[0]
        return items[0]

    def _lx_factor_from_item(self, item):
        if not item:
            return 1.0
        cp = getattr(item, 'compute_price', None)
        if cp == 'percentage' and hasattr(item, 'percent_price'):
            pct = item.percent_price or 0.0
            return abs(pct) / 100.0 or 1.0
        if cp == 'formula' and hasattr(item, 'price_discount'):
            disc = item.price_discount or 0.0
            if abs(disc) >= 100:
                return abs(disc) / 100.0
            return (1.0 + abs(disc)) if disc < 0.0 else max(1.0 - disc, 0.0) or 1.0
        val = abs(item.price or 0.0)
        if val >= 10.0:
            return val / 100.0
        if val > 0.0:
            return val
        return 1.0

    def _lx_partner_rank_factor(self, order):
        partner = order.partner_id if order else False
        at = partner.lx_account_type_id if partner else False
        if not at:
            return 1.0
        try:
            return float(at.rank) / 100.0 if at.rank else 1.0
        except Exception:
            return 1.0

    # ---------- pricing preview ----------
    def _lx_virtual_total_for_width(self, product, width_m):
        Mrp = self.env['mrp.production']
        bom = self._lx_find_bom(product)
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

    def _lx_refresh_preview_from_width(self):
        self.ensure_one()
        sol = self.order_line_id
        if not sol or not self.product_id:
            return (0.0, 1.0, 0.0)
        amount_total = self._lx_virtual_total_for_width(self.product_id, 1.00)
        factor = self._lx_partner_rank_factor(sol.order_id)
        final_price = math.ceil(amount_total * factor)
        return (amount_total, factor, final_price)

    @api.onchange('width')
    def _onchange_width_live_preview(self):
        for w in self:
            if not w.order_line_id or not w.product_id:
                continue
            amount_total, factor, final_price = w._lx_refresh_preview_from_width()
            w.price_preview = final_price

    # ---------- fabric helpers ----------
    def _lx_extract_code_from_roller_name(self, name):
        # "[QM21-01] Roller Blind" -> "QM21-01"
        if not name:
            return False
        import re
        m = re.search(r'\[([^\]]+)\]\s*Roller\s*Blind', name, flags=re.IGNORECASE)
        return m.group(1).strip() if m else False

    def _lx_find_fabric_by_ref_code(self, code):
        if not code:
            return self.env['product.template']
        Fabric = self.env['product.template']
        return Fabric.search([('default_code', '=', code)], limit=1)

    # ---------- computes ----------
    @api.depends('order_line_id')
    def _compute_product_from_line(self):
        for w in self:
            w.product_id = w.order_line_id.product_id.id if w.order_line_id and w.order_line_id.product_id else False

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

    def _val_unit(self, value_m, unit):
        return self._convert_from_meters(value_m or 0.0, unit or 'm')

    @api.depends('product_tmpl_id', 'width', 'height')
    def _compute_dimensions_and_placeholders(self):
        for w in self:
            unit = 'm'
            raw_w = float(w.width or 0.0)
            raw_h = float(w.height or 0.0)
            w.width_m  = max(0.0, raw_w)
            w.height_m = max(0.0, raw_h)

            tmpl = w.product_tmpl_id

            # Width hint
            min_w_m  = 0.60
            min_w_txt = w._fmt_unit(min_w_m, unit)
            max_w_txt = False
            code = w._lx_extract_code_from_roller_name(tmpl.name if tmpl else '')
            fabric = w._lx_find_fabric_by_ref_code(code) if code else self.env['product.template']
            if fabric and fabric.roller_width_ids:
                vals = [float(getattr(t, 'value_cm', 0.0) or 0.0) for t in fabric.roller_width_ids]
                vals = [v for v in vals if v > 0]
                if vals:
                    max_w_m = max(vals) / 100.0
                    max_w_txt = w._fmt_unit(max_w_m, unit)
            w.width_placeholder = f"min: {min_w_txt}" + (f" / max: {max_w_txt}" if max_w_txt else "")

            # Height hint
            min_h_m  = 0.90
            min_h_txt = w._fmt_unit(min_h_m, unit)
            if w.width_m > 0.0:
                max_h_m = w._compute_max_height_from_width(tmpl, w.width_m)
            else:
                max_h_m = float(getattr(tmpl, 'max_height', 0.0) or 0.0)
            max_h_txt = w._fmt_unit(max_h_m, unit) if max_h_m > 0.0 else False
            w.height_placeholder = f"min: {min_h_txt}" + (f" / max: {max_h_txt}" if max_h_txt else "")

    # ---------- validations & actions ----------
    def _validate_dimensions(self):
        self.ensure_one()
        if self.width_m <= 0 or self.height_m <= 0:
            raise UserError(_("Width and height must be greater than zero."))
        if self.width_m < 0.60:
            raise UserError(_("The width is out of range! Minimum width is 0.60 m."))

        tmpl = self.product_tmpl_id

        max_w_m = 0.0
        code = self._lx_extract_code_from_roller_name(tmpl.name if tmpl else '')
        fabric = self._lx_find_fabric_by_ref_code(code) if code else self.env['product.template']
        if fabric and fabric.roller_width_ids:
            vals = [float(getattr(t, 'value_cm', 0.0) or 0.0) for t in fabric.roller_width_ids]
            vals = [v for v in vals if v > 0]
            if vals:
                max_w_m = max(vals) / 100.0

        # Fallback: legacy product width_cm (no subtraction anymore)
        if not max_w_m and tmpl and getattr(tmpl, 'width_cm', False):
            max_w_m = max(0.0, float(tmpl.width_cm or 0.0) / 100.0)

        if max_w_m and self.width_m > max_w_m:
            raise UserError(_("The width is out of range! Maximum width is %.2f m.") % max_w_m)

        if self.height_m < 0.90:
            raise UserError(_("The height is out of range! Minimum height is 0.90 m."))

        # Max height dynamic (Mechanism 'MS' + lx_weight)
        if self.width_m and self.width_m > 0:
            max_h_m = self._compute_max_height_from_width(tmpl, self.width_m)
        else:
            max_h_m = float(getattr(tmpl, 'max_height', 0.0) or 0.0)

        if max_h_m and self.height_m > max_h_m:
            raise UserError(_("The height is out of range! Maximum height is %.2f m.") % max_h_m)

    def action_confirm(self):
        self.ensure_one()
        self._validate_dimensions()

        sol = self.order_line_id
        width_m = self.width_m if self.width_m is not None else self._convert_to_meters(self.width or 0.0, self.dimension_unit or 'm')
        height_m = self.height_m if self.height_m is not None else self._convert_to_meters(self.height or 0.0, self.dimension_unit or 'm')

        _t, _f, computed_price = self._lx_refresh_preview_from_width()
        final_price = computed_price or sol.price_unit or 0.0

        self.write({'price_preview': final_price})  # keep UI stable

        sol.write({
            'lx_width_m':  width_m,
            'lx_height_m': height_m,
            'price_unit':  final_price,
        })
        self.price_preview = final_price
        return {'type': 'ir.actions.act_window_close'}

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        if self.env.context.get('active_model') == 'sale.order.line':
            sol_id = self.env.context.get('active_id')
            if sol_id:
                sol = self.env['sale.order.line'].browse(sol_id)
                if sol.product_tmpl_id and 'price_preview' in fields_list:
                    res['price_preview'] = sol.price_unit
        return res



# class WizardDimensionConfigurator(models.TransientModel):
#     _name = "wizard.dimension.configurator"
#     _description = "Dimension Configurator Wizard"

#     order_id = fields.Many2one("sale.order", required=True, readonly=True)
#     order_line_id = fields.Many2one("sale.order.line", string="Order Line", required=True, readonly=True)

#     product_tmpl_id = fields.Many2one("product.template", string="Product Template", required=True, readonly=True)
#     product_id = fields.Many2one("product.product", string="Product Variant", readonly=True, compute="_compute_product_from_line", store=True)

#     quantity = fields.Float(string="Quantity", default=1.0, help="Quantity to set on the sale order line.")

#     dimension_unit = fields.Selection([("m","m"),("cm","cm"),("mm","mm")], default="m", string="Unit", required=True)
#     width  = fields.Float(string="Width",  default=0.0)
#     height = fields.Float(string="Height", default=0.0)

#     width_m  = fields.Float(string="Width (m)",  compute="_compute_dimensions_and_placeholders", readonly=True)
#     height_m = fields.Float(string="Height (m)", compute="_compute_dimensions_and_placeholders", readonly=True)

#     width_placeholder  = fields.Char(string="Width Hint",  compute="_compute_dimensions_and_placeholders", readonly=True)
#     height_placeholder = fields.Char(string="Height Hint", compute="_compute_dimensions_and_placeholders", readonly=True)

#     price_preview = fields.Monetary(string="Price Unit", currency_field="currency_id", readonly=True)
#     currency_id   = fields.Many2one("res.currency", default=lambda self: self.env.company.currency_id.id, readonly=True)



#     def _convert_from_meters(self, value_m, unit):
#         """Convert a value in meters to the selected unit."""
#         if unit == 'm':
#             return value_m
#         if unit == 'cm':
#             return value_m * 100.0
#         if unit == 'mm':
#             return value_m * 1000.0
#         return value_m

#     def _fmt_unit(self, value_m, unit):
#         """Format a meter value in the selected unit with sensible decimals."""
#         v = self._convert_from_meters(value_m or 0.0, unit)
#         decimals = 2 if unit == 'm' else 0
#         return f"{v:.{decimals}f} {unit}"
    

#     def _convert_to_meters(self, value, unit):
#         try:
#             v = float(value) if value is not None else 0.0
#         except Exception:
#             v = 0.0
#         return v if unit == 'm' else (v/100.0 if unit == 'cm' else v/1000.0)
    

#     def _lx_find_bom(self, product):
#         """Find BoM for a product (prefer variant BoM; fallback to template BoM)."""
#         Bom = self.env['mrp.bom']
#         # Variant-specific BoM first
#         bom = Bom.search([('product_id', '=', product.id)], order='sequence asc', limit=1)
#         if bom:
#             return bom
#         # Then template-wide BoM
#         return Bom.search([
#             ('product_tmpl_id', '=', product.product_tmpl_id.id),
#             ('product_id', '=', False),
#         ], order='sequence asc', limit=1)

#     def _lx_get_partner_pricelist(self, order):
#         partner_pl = order.partner_id.property_product_pricelist
#         return partner_pl or order.pricelist_id

#     def _lx_pick_pricelist_item(self, pricelist, product):

#         if not pricelist:
#             return None

#         items = pricelist.item_ids  
#         if not items:
#             return None

#         exact = items.filtered(lambda it: it.product_id and it.product_id.id == product.id)
#         if exact:
#             return exact[0]

#         # 2) template (product_tmpl_id)
#         tmpl = items.filtered(lambda it: it.product_tmpl_id and it.product_tmpl_id.id == product.product_tmpl_id.id)
#         if tmpl:
#             return tmpl[0]

#         # 3) global (no product/category)
#         generic = items.filtered(lambda it: not it.product_id and not it.product_tmpl_id and not it.categ_id)
#         if generic:
#             return generic[0]

#         # otherwise first one by sequence as a last resort
#         return items[0]

#     def _lx_factor_from_item(self, item):
#         if not item:
#             return 1.0

#         cp = getattr(item, 'compute_price', None)

#         # percentage rule
#         if cp == 'percentage' and hasattr(item, 'percent_price'):
#             pct = item.percent_price or 0.0
#             return abs(pct) / 100.0 or 1.0

#         # formula rule
#         if cp == 'formula' and hasattr(item, 'price_discount'):
#             disc = item.price_discount or 0.0
#             # if user put -200 or -150 as "percent" in discount
#             if abs(disc) >= 100:
#                 return abs(disc) / 100.0
#             # else treat as decimal fraction
#             return (1.0 + abs(disc)) if disc < 0.0 else max(1.0 - disc, 0.0) or 1.0

#         # fallback: interpret 'price' field as factor or percent
#         val = abs(item.price or 0.0)
#         if val >= 10.0:
#             return val / 100.0
#         if val > 0.0:
#             return val
#         return 1.0

#     def _lx_partner_rank_factor(self, order):
#         """Return multiplicative factor from partner account type.
#         Rank is a % (e.g. 20 -> factor 1.20). Fallback 1.0."""
#         partner = order.partner_id if order else False
#         at = partner.lx_account_type_id if partner else False
#         if not at:
#             return 1.0
#         try:
#             return 1.0 + float(at.rank or 0.0) / 100.0
#         except Exception:
#             return 1.0



#     # --- computes ---

#     def _lx_virtual_total_for_width(self, product, width_m):
#         """Use a VIRTUAL MO (new()) and compute totals from MO components only."""
#         Mrp = self.env['mrp.production']
#         bom = self._lx_find_bom(product)
#         if not bom:
#             return 0.0
#         mo = Mrp.new({
#             'company_id': (self.order_id.company_id.id if self.order_id else self.env.company.id),
#             'product_id': product.id,
#             'bom_id': bom.id,
#             'lx_width_m': width_m,
#         })
#         _cost, amount = mo._lx_virtual_calculate(width_m=width_m)
#         return amount

#     def _lx_refresh_preview_from_width(self):
#         self.ensure_one()
#         sol = self.order_line_id
#         if not sol or not self.product_id:
#             return (0.0, 1.0, 0.0)

#         amount_total = self._lx_virtual_total_for_width(self.product_id, 1.00)

#         factor = self._lx_partner_rank_factor(sol.order_id)

#         final_price = math.ceil(amount_total * factor)
#         return (amount_total, factor, final_price)

#     @api.onchange('width')
#     def _onchange_width_live_preview(self):
#         """Pricing preview: pass ONLY width_m (already normalized) to the virtual MO."""
#         for w in self:
#             if not w.order_line_id or not w.product_id:
#                 continue
#             amount_total, factor, final_price = w._lx_refresh_preview_from_width()
#             w.price_preview = final_price

#     def _lx_extract_code_from_roller_name(self, name):
#         # e.g. "[QM21-01] Roller Blind" -> "QM21-01"
#         if not name:
#             return False
#         import re
#         m = re.search(r'\[([^\]]+)\]\s*Roller\s*Blind', name, flags=re.IGNORECASE)
#         return m.group(1).strip() if m else False

#     def _lx_find_fabric_by_ref_code(self, code):
#         """Find Fabric by exact default_code == code (strict)."""
#         if not code:
#             return self.env['product.template']
#         Fabric = self.env['product.template']
#         return Fabric.search([('default_code', '=', code)], limit=1)

#     @api.depends('order_line_id')
#     def _compute_product_from_line(self):
#         for w in self:
#             w.product_id = w.order_line_id.product_id.id if w.order_line_id and w.order_line_id.product_id else False

    
#     def _compute_max_height_from_width(self, tmpl, width_m):
#         if not tmpl:
#             return 0.0

#         divisor = 1.0
#         cat = tmpl.categ_id
#         if cat and "Day & Night" in (cat.name or ""):
#             divisor = 2.0

#         # Prefer Fabric.lx_weight, else product.lx_weight (no native weight)
#         fabric = getattr(tmpl, 'lx_fabric_ref_id', False)
#         weight = float((getattr(fabric, 'lx_weight', 0.0) or getattr(tmpl, 'lx_weight', 0.0) or 0.0))

#         # Load strictly from Mechanism Set (default_code = 'MS')
#         mech = self.env['product.template'].search([('default_code', '=', 'MS')], limit=1)
#         load = float(getattr(mech, 'maximum_load', 0.0) or 0.0)

#         width_cm = max(0.0, float(width_m or 0.0) * 100.0)
#         if width_cm <= 0.0 or weight <= 0.0 or load <= 0.0 or divisor <= 0.0:
#             return 0.0

#         h_m = (load / (width_cm * weight)) / divisor * 100000.0
#         return max(0.0, round(h_m, 4))


#     def _val_unit(self, value_m, unit):
#         return self._convert_from_meters(value_m or 0.0, unit or 'm')


#     @api.depends('product_tmpl_id', 'width', 'height')
#     def _compute_dimensions_and_placeholders(self):
#         for w in self:
#             unit = 'm'
#             raw_w = float(w.width or 0.0)
#             raw_h = float(w.height or 0.0)
#             w.width_m  = max(0.0, raw_w)
#             w.height_m = max(0.0, raw_h)

#             tmpl = w.product_tmpl_id

#             # ---- Width hint: min fixed; max from FABRIC (by exact default_code) ----
#             min_w_m  = 0.60
#             min_w_txt = w._fmt_unit(min_w_m, unit)

#             max_w_txt = False
#             # try to resolve fabric strictly by default_code from roller name pattern
#             code = w._lx_extract_code_from_roller_name(tmpl.name if tmpl else '')
#             fabric = w._lx_find_fabric_by_ref_code(code) if code else self.env['product.template']
#             if fabric and fabric.roller_width_ids:
#                 # take MAX tag value (cm) from fabric
#                 vals = [float(getattr(t, 'value_cm', 0.0) or 0.0) for t in fabric.roller_width_ids]
#                 vals = [v for v in vals if v > 0]
#                 if vals:
#                     max_w_m = max(vals) / 100.0
#                     max_w_txt = w._fmt_unit(max_w_m, unit)

#             w.width_placeholder = f"min: {min_w_txt}" + (f" / max: {max_w_txt}" if max_w_txt else "")

#             # ---- Height hint: same as before but using Mechanism 'MS' load (see section 4) ----
#             min_h_m  = 0.90
#             min_h_txt = w._fmt_unit(min_h_m, unit)

#             if w.width_m > 0.0:
#                 max_h_m = w._compute_max_height_from_width(tmpl, w.width_m)
#             else:
#                 max_h_m = float(getattr(tmpl, 'max_height', 0.0) or 0.0)

#             max_h_txt = w._fmt_unit(max_h_m, unit) if max_h_m > 0.0 else False
#             w.height_placeholder = f"min: {min_h_txt}" + (f" / max: {max_h_txt}" if max_h_txt else "")


#     # --- validations & actions ---
#     def _validate_dimensions(self):
#         self.ensure_one()
#         if self.width_m <= 0 or self.height_m <= 0:
#             raise UserError(_("Width and height must be greater than zero."))
#         if self.width_m < 0.60:
#             raise UserError(_("The width is out of range! Minimum width is 0.60 m."))

#         tmpl = self.product_tmpl_id
#         if tmpl and getattr(tmpl, 'width_cm', False):
#             max_w_m = (float(tmpl.width_cm) - 3.0) / 100.0
#             if max_w_m > 0 and self.width_m > max_w_m:
#                 raise UserError(_("The width is out of range! Maximum width is %.2f m.") % max_w_m)

#         if self.height_m < 0.90:
#             raise UserError(_("The height is out of range! Minimum height is 0.90 m."))

#         # Max height: same rule as placeholders (no width -> product.max_height; width -> dynamic)
#         if self.width_m and self.width_m > 0:
#             max_h_m = self._compute_max_height_from_width(tmpl, self.width_m)
#         else:
#             max_h_m = float(getattr(tmpl, 'max_height', 0.0) or 0.0)

#         if max_h_m and self.height_m > max_h_m:
#             raise UserError(_("The height is out of range! Maximum height is %.2f m.") % max_h_m)


#     def action_confirm(self):
#         self.ensure_one()
#         self._validate_dimensions()

#         sol = self.order_line_id
#         width_m = self.width_m if self.width_m is not None else self._convert_to_meters(self.width or 0.0, self.dimension_unit or 'm')
#         height_m = self.height_m if self.height_m is not None else self._convert_to_meters(self.height or 0.0, self.dimension_unit or 'm')

#         _t, _f, computed_price = self._lx_refresh_preview_from_width()
#         final_price = computed_price or sol.price_unit or 0.0

#         self.write({'price_preview': final_price})  # keep UI stable

#         sol.write({
#             'lx_width_m':  width_m,
#             'lx_height_m': height_m,
#             'price_unit':  final_price,
#         })
#         self.price_preview = final_price
#         return {'type': 'ir.actions.act_window_close'}


    
#     # # --- validations & actions ---
#     # def _validate_dimensions(self):
#     #     self.ensure_one()
#     #     if self.width_m <= 0 or self.height_m <= 0:
#     #         raise UserError(_("Width and height must be greater than zero."))
#     #     if self.width_m < 0.60:
#     #         raise UserError(_("The width is out of range! Minimum width is 0.60 m."))
#     #     tmpl = self.product_tmpl_id
#     #     if tmpl and getattr(tmpl, 'width_cm', False):
#     #         max_w_m = (float(tmpl.width_cm) - 3.0) / 100.0
#     #         if max_w_m > 0 and self.width_m > max_w_m:
#     #             raise UserError(_("The width is out of range! Maximum width is %.2f m.") % max_w_m)
#     #     if self.height_m < 0.90:
#     #         raise UserError(_("The height is out of range! Minimum height is 0.90 m."))
#     #     # dynamic max height
#     #     max_h_m = self._wiz_max_height_m()
#     #     if max_h_m and self.height_m > max_h_m:
#     #         raise UserError(_("The height is out of range! Maximum height is %.2f m.") % max_h_m)

#     # def action_confirm(self):
#     #     self.ensure_one()
#     #     sol = self.order_line_id
#     #     width_m = self.width_m if self.width_m is not None else self._convert_to_meters(self.width or 0.0, self.dimension_unit or 'm')
#     #     height_m = self.height_m if self.height_m is not None else self._convert_to_meters(self.height or 0.0, self.dimension_unit or 'm')

#     #     _t, _f, computed_price = self._lx_refresh_preview_from_width(width_m=width_m)
#     #     final_price = computed_price or sol.price_unit or 0.0

#     #     # write the FINAL value (not 0) so UI doesn't flash 0
#     #     self.write({'price_preview': final_price})

#     #     sol.write({
#     #         'lx_width_m':  width_m,
#     #         'lx_height_m': height_m,
#     #         'price_unit':  final_price,
#     #     })
        
#     #     self.price_preview = final_price


#     #     return {'type': 'ir.actions.act_window_close'}
    
#     @api.model
#     def default_get(self, fields_list):
#         res = super().default_get(fields_list)
#         if self.env.context.get('active_model') == 'sale.order.line':
#             sol_id = self.env.context.get('active_id')
#             if sol_id:
#                 sol = self.env['sale.order.line'].browse(sol_id)
#                 if sol.product_tmpl_id and 'price_preview' in fields_list:
#                     res['price_preview'] = sol.price_unit
#         return res


    
        

