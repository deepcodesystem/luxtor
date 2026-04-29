# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import math
import logging

_logger = logging.getLogger(__name__)


class LxVirtualPriceController(http.Controller):

    @http.route('/shop/lx_virtual_price', type='json', auth='public', website=True, csrf=False)
    def lx_virtual_price(self, product_id=None, width=0.0, height=0.0, debug=1, **kw):
        """
        Returns preview pricing for a variant.
        Adds a rich 'debug_info' payload and server-side logs to trace the calculation.
        Pass debug=0 to suppress debug_info in the response.
        """
        # ---- input coercion ---------------------------------------------------
        try:
            product_id = int(product_id or 0)
        except Exception:
            product_id = 0

        def _f(v, d):
            try:
                return float(v if v not in (None, "") else d)
            except Exception:
                return d

        width_m  = _f(width,  1.0)
        height_m = _f(height, 1.0)

        dbg_enabled = False
        try:
            dbg_enabled = bool(int(debug))
        except Exception:
            dbg_enabled = True  # default ON for visibility

        if not product_id:
            return {'ok': False, 'message': 'Missing product_id.'}

        # ---- product lookup ---------------------------------------------------
        Product = request.env['product.product'].sudo()
        product = Product.browse(product_id).exists()
        if not product:
            return {'ok': False, 'message': 'Product not found.'}

        # ---- transient line to reuse helpers ---------------------------------
        order = request.website.sale_get_order(force_create=False)
        line = request.env['sale.order.line'].sudo().new({
            'order_id': order and order.id,
            'product_id': product.id,
            'lx_width_m': width_m,
            'lx_height_m': height_m,
            'product_uom_qty': 1.0,
        })

        # ---- compute base_total_for_w1 using your new helper ------------------
        try:
            # IMPORTANT: this relies on the helper you wired in sale.order.line
            #            _lx_virtual_total_for_width_lowest_no_motor(product, 1.00)
            base_total_for_w1 = float(line._lx_virtual_total_for_width_lowest_no_motor(product, 1.00))
        except Exception as e:
            _logger.exception("lx_virtual_price: error in _lx_virtual_total_for_width_lowest_no_motor")
            return {'ok': False, 'message': f'Pricing error: {e}'}

        # ---- browser factor ---------------------------------------------------
        param_val = request.env['ir.config_parameter'].sudo().get_param(
            "luxtor.lx_browser_factor_pct", default="100"
        )
        try:
            markupbrowserfactor = float(param_val) / 100.0
        except Exception:
            markupbrowserfactor = 1.0

        unit_virtual = math.ceil(base_total_for_w1 * markupbrowserfactor)

        # ---- area and final ---------------------------------------------------
        size = max(1.0, width_m) * max(1.0, height_m)
        final_unit_price = unit_virtual * size

        # ---- human debug lines ------------------------------------------------
        human_lines = [
            f"Product: {product.display_name} (ID {product.id})",
            f"Inputs → width={width_m:.2f} m, height={height_m:.2f} m",
            f"Base at w=1.00 (non-motorized, cheapest-per-BOM): {base_total_for_w1:.2f}",
            f"Browser factor param: {param_val}% → {markupbrowserfactor:.2f}",
            f"Unit virtual (ceil): {unit_virtual:.2f}",
            f"Area (size): {size:.4f} m²",
            f"Final unit price = {unit_virtual:.2f} × {size:.2f} = {final_unit_price:.2f}",
        ]
        msg = "\n".join(human_lines)

        # ---- server logs (helpful when tailing logs) --------------------------
        _logger.info("[lx_virtual_price] pid=%s w=%.3f h=%.3f base_w1=%.2f factor=%s(%.3f) unit=%s size=%.4f final=%s",
                     product_id, width_m, height_m, base_total_for_w1, param_val, markupbrowserfactor,
                     unit_virtual, size, final_unit_price)

        # ---- payload ----------------------------------------------------------
        payload = {
            'ok': True,
            'product_id': product_id,
            'unit_virtual': float(unit_virtual),
            'width_m': float(width_m),
            'height_m': float(height_m),
            'size': float(size),
            'final_unit_price': float(final_unit_price),
            'message': msg,
        }

        # Optionally include a structured debug block for your UI or console
        if dbg_enabled:
            payload['debug_info'] = {
                'inputs': {
                    'product_id': product_id,
                    'product_name': product.display_name,
                    'width_m': width_m,
                    'height_m': height_m,
                },
                'base': {
                    'base_total_for_w1': base_total_for_w1,
                    'browser_param_percent': param_val,
                    'browser_factor': markupbrowserfactor,
                },
                'computed': {
                    'unit_virtual': unit_virtual,
                    'area_size_m2': size,
                    'final_unit_price': final_unit_price,
                },
            }

        return payload

    @http.route('/lx/store_dims', type='json', auth='public', website=True, csrf=False)
    def store_dims(self, pid=0, w=0.0, h=0.0):
        """Persist last used dimensions per product in the website session."""
        try:
            pid_int = int(pid or 0)
        except Exception:
            pid_int = 0

        def _f(v):
            try:
                return float(v or 0.0)
            except Exception:
                return 0.0

        s = request.session.setdefault('lx_dims', {})
        s[str(pid_int)] = {'w': _f(w), 'h': _f(h)}
        request.session.modified = True
        return {'ok': True}
