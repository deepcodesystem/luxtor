# controllers/lx_price.py
# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

class LxPriceController(http.Controller):

    def _safe_float(self, v, default=0.0):
        try:
            return float(v or 0.0)
        except Exception:
            return default

    def _virtual_unit_price(self, product):
        """Return wizard-like virtual unit price (width=1, height=1 logic), ignoring size."""
        SaleOrderLine = request.env['sale.order.line'].sudo()
        line = SaleOrderLine.new({'product_id': product.id})
        try:
            return float(line._lx_compute_price_unit_like_wizard() or 0.0)
        except Exception:
            return 0.0

    def _tax_totals(self, product, unit_price, qty_eff):
        env = request.env.sudo()
        website = request.website
        currency = website.currency_id or env.company.currency_id
        partner = (request.env.user.partner_id
                   if request.env.user and request.env.user.id
                   else website.user_id.partner_id)
        taxes = product.taxes_id
        try:
            fpos = website._get_current_fiscal_position(partner=partner)
            if fpos:
                taxes = fpos.map_tax(taxes, product, partner)
        except Exception:
            pass
        res = taxes.compute_all(
            unit_price,
            currency,
            qty_eff,
            product=product,
            partner=partner,
        )
        return res, currency

    @http.route("/lx/product/priceinfo", type="json", auth="public", website=True, csrf=False)
    def product_priceinfo(self, product_id=None, width=None, height=None, qty=1, mode=None):
        """mode:
           - 'virtual' -> return pure virtual unit price (wizard-like), ignore size
           - default   -> (legacy) compute with size if provided
        """
        # --- resolve product
        try:
            pid = int(product_id or 0)
        except Exception:
            return {'ok': False, 'error': 'bad_product_id', 'detail': str(product_id)}
        if not pid:
            return {'ok': False, 'error': 'missing_product_id'}
        Product = request.env['product.product'].sudo().browse(pid)
        if not Product.exists():
            return {'ok': False, 'error': 'product_not_found', 'detail': pid}

        qty_f = max(1.0, self._safe_float(qty, 1.0))

        try:
            if (mode or "").lower() == "virtual":
                # ---------- PURE VIRTUAL UNIT PRICE ----------
                unit = self._virtual_unit_price(Product)  # width=1 logic under the hood
                tax_res, currency = self._tax_totals(Product, unit, qty_f)  # qty only; no size
                return {
                    'ok': True,
                    'mode': 'virtual',
                    'unit_price': unit,
                    'qty': qty_f,
                    'price_subtotal': tax_res['total_excluded'],
                    'price_total': tax_res['total_included'],
                    'currency': {
                        'symbol': currency.symbol,
                        'position': currency.position,
                        'decimal_places': currency.decimal_places or 2,
                    },
                }

            # ---------- (optional) keep your previous “size-aware” path ----------
            width_m  = self._safe_float(width, 0.0)
            height_m = self._safe_float(height, 0.0)
            # Use your wizard-like unit price anyway, but totals with size
            unit = self._virtual_unit_price(Product)
            size = (width_m * height_m) if (width_m > 0 and height_m > 0) else 0.0
            qty_eff = (size or 1.0) * qty_f
            tax_res, currency = self._tax_totals(Product, unit, qty_eff)
            return {
                'ok': True,
                'mode': 'size',
                'unit_price': unit,
                'size': size,
                'qty_effective': qty_eff,
                'price_subtotal': tax_res['total_excluded'],
                'price_total': tax_res['total_included'],
                'currency': {
                    'symbol': currency.symbol,
                    'position': currency.position,
                    'decimal_places': currency.decimal_places or 2,
                },
            }
        except Exception as e:
            return {'ok': False, 'error': 'exception', 'detail': str(e)}
