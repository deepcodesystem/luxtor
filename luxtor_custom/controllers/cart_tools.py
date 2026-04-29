# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


def _lx_sale_get_order(force_create=False):
    """V19-compatible cart order getter — replaces website.sale_get_order()."""
    try:
        return request.website.sale_get_order(force_create=force_create)
    except AttributeError:
        pass
    # V19: session-based fallback
    Order = request.env['sale.order'].sudo()
    order_id = request.session.get('sale_order_id')
    if order_id:
        order = Order.browse(int(order_id)).exists()
        if order:
            return order
    return Order.browse()

def _find_product_by_code(code):
    code = (code or "").strip()
    if not code:
        return None, None
    Product = request.env["product.product"].sudo()
    variant = Product.search([("default_code", "=", code)], limit=1)
    if variant:
        return variant, None
    Tmpl = request.env["product.template"].sudo()
    tmpl = Tmpl.search([("default_code", "=", code)], limit=1)
    if tmpl and tmpl.product_variant_id:
        return tmpl.product_variant_id, tmpl
    return None, None

def _render_cart_fragments(order):
    View = request.env["ir.ui.view"].sudo()
    return {
        "website_sale.cart_lines": View._render_template(
            "website_sale.cart_lines", {"website_sale_order": order}
        ),
        "cart_quantity": order.cart_quantity,
        "amount_total": order.amount_total,
    }

class LxCartTools(WebsiteSale):

    @http.route("/lx/cart/remove_by_code", type="json", auth="public", website=True, csrf=False)
    def lx_cart_remove_by_code(self, default_code=None, **kw):
        """
        Remove any order line(s) whose product or template default_code matches,
        using sale.order._cart_update(..., set_qty=0). Always returns JSON.
        """
        try:
            _logger.info("[LXT] /lx/cart/remove_by_code called with default_code=%s", default_code)

            order = _lx_sale_get_order(force_create=True)
            if not order:
                _logger.warning("[LXT] No sale order in session.")
                return {"ok": False, "reason": "no_order"}

            product, tmpl = _find_product_by_code(default_code)
            if not product:
                _logger.warning("[LXT] Product not found for code=%s", default_code)
                payload = _render_cart_fragments(order)
                payload.update({"ok": False, "reason": "product_not_found"})
                return payload

            lines = order.order_line.filtered(
                lambda l: not l.display_type and l.product_id and (
                    l.product_id.id == product.id
                    or (tmpl and l.product_id.product_tmpl_id.id == tmpl.id)
                )
            )

            removed = 0
            for line in lines:
                _logger.info("[LXT] Removing line_id=%s product_id=%s",
                             line.id, line.product_id.id)
                try:
                    order.with_context(skip_cart_verification=True)._cart_update_line_quantity(
                        line_id=line.id, quantity=0
                    )
                except AttributeError:
                    order._cart_update(product_id=line.product_id.id, line_id=line.id, set_qty=0)
                removed += 1

            request.session["sale_order_id"] = order.id
            payload = _render_cart_fragments(order)
            payload.update({"ok": True, "removed": removed})
            _logger.info("[LXT] Removal finished. removed=%s cart_qty=%s total=%s",
                         removed, order.cart_quantity, order.amount_total)
            return payload

        except Exception as e:
            # Never let the RPC explode; return a JSON error and log the traceback.
            _logger.exception("[LXT] remove_by_code failed: %s", e)
            return {
                "ok": False,
                "reason": "exception",
                "error": str(e),
            }
