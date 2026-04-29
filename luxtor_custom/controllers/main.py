# controllers/main.py
# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request, route
from odoo.addons.website_sale.controllers.main import WebsiteSale
import logging
import math

_logger = logging.getLogger(__name__)


def _norm(v, default=None):
    if v in (None, '', False):
        return default
    try:
        return str(v).strip().replace(',', '.')
    except Exception:
        return default


def _lx_read_session_dims():
    """Read width/height/location from session."""
    sess = request.session.get("lx_dims") or {}
    w = _norm(sess.get("lx_width_m"))
    h = _norm(sess.get("lx_height_m"))
    loc = _norm(sess.get("lx_location_id"))
    return w, h, loc


def _lx_compute_price_fn(env, product_id, width_m, height_m):
    """
    Compute the custom dimension-based price for a product.
    Returns final_unit_price (float) or None if not a dimension product.
    """
    try:
        product_id = int(product_id or 0)
    except Exception:
        return None
    if not product_id:
        return None

    product = env['product.product'].sudo().browse(product_id).exists()
    if not product:
        return None

    Bom = env['mrp.bom'].sudo()
    bom = Bom.search([('product_id', '=', product.id)], order='sequence asc', limit=1)
    if not bom:
        bom = Bom.search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ('product_id', '=', False),
        ], order='sequence asc', limit=1)
    if not bom:
        return None  # not a dimension product

    try:
        mo = env['mrp.production'].sudo().new({
            'company_id': env.company.id,
            'product_id': product.id,
            'bom_id': bom.id,
            'lx_width_m': 1.0,
        })
        _cost, base_total = mo._lx_virtual_calculate(width_m=1.0)
    except Exception as e:
        _logger.warning("LX: price compute failed for product %s: %s", product_id, e)
        return None

    try:
        factor = float(
            env['ir.config_parameter'].sudo().get_param('luxtor.lx_browser_factor_pct', default='100')
        ) / 100.0
    except Exception:
        factor = 1.0

    unit_virtual = math.ceil(base_total * factor)
    size = max(1.0, float(width_m)) * max(1.0, float(height_m))
    final_price = unit_virtual * size
    _logger.info("LX: computed price product=%s w=%.2f h=%.2f → %.2f", product_id, width_m, height_m, final_price)
    return final_price


def _inject_lx_kwargs(kw, payload=None):
    """
    Read dims and price from payload → kw → session, compute price if missing.
    Mutates kw in-place. Returns updated kw.
    """
    payload = payload or {}

    # Dims: payload first, then kw, then session
    w = _norm(payload.get("lx_width_m")) or _norm(kw.get("lx_width_m"))
    h = _norm(payload.get("lx_height_m")) or _norm(kw.get("lx_height_m"))
    if not w or not h:
        sw, sh, sloc = _lx_read_session_dims()
        w = w or sw
        h = h or sh
    else:
        _sw, _sh, sloc = _lx_read_session_dims()

    loc = _norm(payload.get("lx_location_id")) or _norm(kw.get("lx_location_id")) or sloc

    if w:
        kw["lx_width_m"] = w
    if h:
        kw["lx_height_m"] = h
    if loc:
        kw["lx_location_id"] = loc

    # Price: payload first, then kw — compute from BoM if still missing
    pu = _norm(payload.get("lx_final_unit_price") or payload.get("lx_price_override"))
    if not pu:
        pu = _norm(kw.get("lx_final_unit_price") or kw.get("lx_price_override"))
    if not pu:
        pid = kw.get("product_id") or payload.get("product_id")
        computed = _lx_compute_price_fn(
            request.env, pid, float(w or 1), float(h or 1)
        )
        if computed:
            pu = str(computed)

    if pu:
        kw["lx_final_unit_price"] = pu
        kw["lx_price_override"] = pu

    _logger.info("LX inject: %s", {k: kw[k] for k in kw if k.startswith("lx_")})
    return kw


# ── V19: override CartController.add_to_cart (/shop/cart/add) ─────────────────
# In V19, Odoo moved cart routes to website_sale/controllers/cart.py.
# The configurator dialog and "Add to Cart" button both POST to /shop/cart/add.
# We must intercept here to inject dims + price before _prepare_order_line_values.

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
            kw["product_id"] = product_id
            _inject_lx_kwargs(kw, payload)
            kw.pop("product_id", None)
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
    _logger.warning("LX: website_sale.controllers.cart.Cart not found — V19 add_to_cart override skipped")


# ── /lx/store_dims endpoint ───────────────────────────────────────────────────
# Stores dims in session so the server-side price fallback can read them.

class WebsiteSaleDims(WebsiteSale):

    @route(['/lx/store_dims'], type='json', auth='public', website=True, csrf=False, methods=['POST'])
    def lx_store_dims(self, lx_width_m=None, lx_height_m=None, lx_location_id=None, **kw):
        try:
            payload = request.jsonrequest or {}
        except Exception:
            payload = {}
        w = _norm(payload.get("lx_width_m") or lx_width_m, default="1")
        h = _norm(payload.get("lx_height_m") or lx_height_m, default="1")
        loc = _norm(payload.get("lx_location_id") or lx_location_id, default="")
        request.session["lx_dims"] = {
            "lx_width_m": w,
            "lx_height_m": h,
            "lx_location_id": loc or "",
        }
        request.session.modified = True
        _logger.info("LX: stored dims in session: w=%s h=%s loc=%s", w, h, loc or "")
        return {"ok": True}
