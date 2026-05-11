# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


def _norm(v, default=None):
    if v in (None, '', False):
        return default
    try:
        return str(v).strip().replace(',', '.')
    except Exception:
        return default


def _f(v, d=0.0):
    try:
        return float(v if v not in (None, '') else d)
    except Exception:
        return d


def _lx_read_session_dims():
    sess = request.session.get('lx_dims') or {}
    w = _norm(sess.get('lx_width_m'))
    h = _norm(sess.get('lx_height_m'))
    loc = _norm(sess.get('lx_location_id'))
    return w, h, loc


# ── /shop/lx_virtual_price ───────────────────────────────────────────────────

class LxVirtualPriceController(http.Controller):

    @http.route('/shop/lx_virtual_price', type='jsonrpc', auth='public', website=True, csrf=False)
    def lx_virtual_price(self, product_id=None, width=0.0, height=0.0, **kw):
        try:
            product_id = int(product_id or 0)
        except Exception:
            product_id = 0

        width_m  = _f(width,  1.0)
        height_m = _f(height, 1.0)

        if not product_id:
            return {'ok': False, 'message': 'Missing product_id.'}

        product = request.env['product.product'].sudo().browse(product_id).exists()
        if not product:
            return {'ok': False, 'message': 'Product not found.'}

        tmpl = product.product_tmpl_id
        if not getattr(tmpl, 'is_dimension_product', False) and not getattr(tmpl, 'lx_fabric_ref_id', False):
            return {'ok': False, 'message': 'Not a dimension product.'}

        try:
            order = request.website.sale_get_order(force_create=False)
            line = request.env['sale.order.line'].sudo().with_context(
                lx_skip_dimension_reprice=True,
            ).new({
                'order_id': order and order.id or False,
                'product_id': product.id,
                'lx_width_m': width_m,
                'lx_height_m': height_m,
                'product_uom_qty': 1.0,
            })
            final = float(line._lx_compute_website_final_unit_price(
                width_m=width_m, height_m=height_m,
            ) or 0.0)
        except Exception:
            _logger.exception('[lx_virtual_price] pricing error product=%s', product_id)
            return {'ok': False, 'message': 'Pricing error.'}

        _logger.info('[lx_virtual_price] pid=%s w=%.2f h=%.2f → %.2f',
                     product_id, width_m, height_m, final)
        return {
            'ok': True,
            'product_id': product_id,
            'width_m': width_m,
            'height_m': height_m,
            'size': round(width_m * height_m, 4),
            'final_unit_price': final,
        }


# ── /lx/store_dims ───────────────────────────────────────────────────────────

class LxStoreDimsController(http.Controller):

    @http.route('/lx/store_dims', type='jsonrpc', auth='public', website=True, csrf=False, methods=['POST'])
    def lx_store_dims(self, lx_width_m=None, lx_height_m=None, lx_location_id=None, **kw):
        try:
            payload = request.jsonrequest or {}
        except Exception:
            payload = {}
        w   = _norm(payload.get('lx_width_m')    or lx_width_m,    default='1')
        h   = _norm(payload.get('lx_height_m')   or lx_height_m,   default='1')
        loc = _norm(payload.get('lx_location_id') or lx_location_id, default='')
        request.session['lx_dims'] = {
            'lx_width_m':    w,
            'lx_height_m':   h,
            'lx_location_id': loc or '',
        }
        request.session.modified = True
        return {'ok': True}


# ── /shop/cart/add override ───────────────────────────────────────────────────

def _lx_compute_price(env, product_id, width_m, height_m):
    """Calcule le final_unit_price côté serveur (fallback si JS ne l'a pas envoyé)."""
    try:
        product = env['product.product'].sudo().browse(int(product_id or 0)).exists()
        if not product:
            return None
        line = env['sale.order.line'].sudo().with_context(
            lx_skip_dimension_reprice=True,
        ).new({
            'product_id': product.id,
            'lx_width_m': float(width_m or 1.0),
            'lx_height_m': float(height_m or 1.0),
            'product_uom_qty': 1.0,
        })
        return float(line._lx_compute_website_final_unit_price(
            width_m=float(width_m or 1.0),
            height_m=float(height_m or 1.0),
        ) or 0.0) or None
    except Exception:
        return None


try:
    from odoo.addons.website_sale.controllers.cart import Cart as _WsCart

    class LxCartController(_WsCart):

        @http.route(
            route='/shop/cart/add',
            type='jsonrpc',
            auth='public',
            methods=['POST'],
            website=True,
            sitemap=False,
        )
        def add_to_cart(
            self,
            product_template_id,
            product_id,
            quantity=1.0,
            uom_id=None,
            product_custom_attribute_values=None,
            no_variant_attribute_value_ids=None,
            linked_products=None,
            **kw
        ):
            try:
                payload = request.jsonrequest or {}
            except Exception:
                payload = {}

            # Dims : payload → kw → session
            w = _norm(payload.get('lx_width_m'))   or _norm(kw.get('lx_width_m'))
            h = _norm(payload.get('lx_height_m'))  or _norm(kw.get('lx_height_m'))
            if not w or not h:
                sw, sh, sloc = _lx_read_session_dims()
                w = w or sw
                h = h or sh
                loc = _norm(payload.get('lx_location_id')) or _norm(kw.get('lx_location_id')) or sloc
            else:
                _, __, sloc = _lx_read_session_dims()
                loc = _norm(payload.get('lx_location_id')) or _norm(kw.get('lx_location_id')) or sloc

            if w:
                kw['lx_width_m'] = w
            if h:
                kw['lx_height_m'] = h
            if loc:
                kw['lx_location_id'] = loc

            # Prix : payload → kw → calcul serveur
            pu = _norm(payload.get('lx_final_unit_price')) or _norm(kw.get('lx_final_unit_price'))
            if not pu and w and h:
                computed = _lx_compute_price(request.env, product_id, float(w), float(h))
                if computed:
                    pu = str(computed)
            if pu:
                kw['lx_final_unit_price'] = pu

            _logger.info('[LxCart] add_to_cart pid=%s w=%s h=%s price=%s', product_id, w, h, pu)
            return super().add_to_cart(
                product_template_id=product_template_id,
                product_id=product_id,
                quantity=quantity,
                uom_id=uom_id,
                product_custom_attribute_values=product_custom_attribute_values,
                no_variant_attribute_value_ids=no_variant_attribute_value_ids,
                linked_products=linked_products,
                **kw,
            )

except ImportError:
    _logger.warning('LX: website_sale.controllers.cart.Cart not found — cart override skipped')

