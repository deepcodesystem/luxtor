# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
import math


class LxVirtualPriceController(http.Controller):

    @http.route('/shop/lx_virtual_price', type='json', auth='public', website=True, csrf=False)
    def lx_virtual_price(self, product_id=None, width=0.0, height=0.0, **kw):
        try:
            product_id = int(product_id or 0)
        except Exception:
            product_id = 0

        width_m  = float(width  or 1.0)
        height_m = float(height or 1.0)

        if not product_id:
            return {'ok': False, 'message': 'Missing product_id.'}

        env = request.env
        product = env['product.product'].sudo().browse(product_id).exists()
        if not product:
            return {'ok': False, 'message': 'Product not found.'}

        # ── Find BoM directly (avoids sale.order.line.new() V19 onchange issues) ──
        Bom = env['mrp.bom'].sudo()
        bom = Bom.search(
            [('product_id', '=', product.id)],
            order='sequence asc', limit=1
        )
        if not bom:
            bom = Bom.search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id),
                ('product_id', '=', False),
            ], order='sequence asc', limit=1)

        if not bom:
            return {'ok': False, 'message': 'No BoM found for this product.'}

        # ── Virtual MO — use W=1 (same convention as wizard/SOL price_unit) ──
        try:
            mo = env['mrp.production'].sudo().new({
                'company_id': env.company.id,
                'product_id': product.id,
                'bom_id': bom.id,
                'lx_width_m': 1.0,
            })
            _cost, base_total_for_w1 = mo._lx_virtual_calculate(width_m=1.0)
        except Exception as e:
            return {'ok': False, 'message': f'Virtual calculation failed: {e}'}

        # ── Browser markup factor ──
        param_val = env['ir.config_parameter'].sudo().get_param(
            'luxtor.lx_browser_factor_pct', default='100'
        )
        try:
            factor = float(param_val) / 100.0
        except Exception:
            factor = 1.0

        unit_virtual = math.ceil(base_total_for_w1 * factor)

        size = max(1.0, width_m) * max(1.0, height_m)
        final_unit_price = unit_virtual * size

        return {
            'ok': True,
            'product_id': product_id,
            'unit_virtual': unit_virtual,
            'width_m': width_m,
            'height_m': height_m,
            'size': size,
            'final_unit_price': final_unit_price,
            'message': (
                f"Virtual unit price (w=1.00): {unit_virtual:.2f}\n"
                f"Width: {width_m:.2f} m, Height: {height_m:.2f} m\n"
                f"Size: {size:.4f} m²\n"
                f"Final unit price = {unit_virtual:.2f} × {size:.2f} = {final_unit_price:.2f}"
            ),
        }

    @http.route('/shop/lx_motor_variants', type='json', auth='public', website=True, csrf=False)
    def lx_motor_variants(self):
        """Return all tubular motor variants for the Motor Only picker on the product page."""
        PT = request.env['product.template'].sudo()
        motor_tmpl = PT.search([('lx_is_tubular_motor', '=', True)], limit=1)
        if not motor_tmpl:
            return []
        result = []
        for variant in motor_tmpl.product_variant_ids:
            code = label = ""
            for ptav in variant.product_template_attribute_value_ids:
                if (ptav.attribute_id.name or "").strip() == "Code":
                    code  = (ptav.product_attribute_value_id.name or "").strip()
                    label = getattr(ptav, 'lx_motor_label', False) or code
                    break
            result.append({
                "id":    variant.id,
                "code":  code,
                "label": label or code or variant.display_name,
            })
        result.sort(key=lambda x: x["code"])
        return result

    # /lx/store_dims is handled by WebsiteSaleDims in controllers/main.py
