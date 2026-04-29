# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request

DEFAULT_MSG = _("You can't continue: the related fabric is not enough in stock.")
PARAM_USED_PCT = "luxtor.lx_fabric_freeze_used_pct"  # ex: "95"


def _lx_sale_get_order(force_create=False):
    """V19-compatible cart order getter."""
    try:
        return request.website.sale_get_order(force_create=force_create)
    except AttributeError:
        pass
    Order = request.env['sale.order'].sudo()
    order_id = request.session.get('sale_order_id')
    if order_id:
        order = Order.browse(int(order_id)).exists()
        if order:
            return order
    return Order.browse()


class WebsiteSaleFreeze(http.Controller):

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------
    def _get_used_threshold_pct(self):
        icp = request.env["ir.config_parameter"].sudo()
        val = icp.get_param(PARAM_USED_PCT, default="95")
        try:
            v = float(val)
        except Exception:
            v = 95.0
        # clamp to [0..100]
        return max(0.0, min(100.0, v))

    def _as_product(self, fabric_ref):
        """Support fabric_ref as product.template OR product.product."""
        if not fabric_ref:
            return request.env["product.product"]
        if fabric_ref._name == "product.product":
            return fabric_ref
        if fabric_ref._name == "product.template":
            return fabric_ref.product_variant_id
        # fallback: try variant_id if present
        return getattr(fabric_ref, "product_variant_id", request.env["product.product"])

    def _should_freeze_template(self, pt):
        """
        Freeze rule (interpreting your "up to 95%"):
        - PARAM is "USED % threshold" (e.g. 95)
        - used_pct = 100 - remaining_pct
        - freeze when used_pct >= threshold
        This means: if remaining_pct <= (100 - threshold) -> freeze.
        Example: threshold=95 -> remaining<=5% -> freeze.
        """
        if not pt or not pt.exists():
            return (False, 100.0, "", False)

        # Only check templates that have the fabric ref
        fabric_ref = getattr(pt, "lx_fabric_ref_id", False)
        if not fabric_ref:
            return (False, 100.0, "", False)  # not applicable

        fabric_prod = self._as_product(fabric_ref)
        if not fabric_prod or not fabric_prod.exists():
            return (True, 0.0, DEFAULT_MSG, True)

        # We use "free_qty" for website realism (available to promise).
        # If you prefer qty_available, swap it.
        try:
            free_qty = float(fabric_prod.free_qty)
        except Exception:
            free_qty = 0.0

        # You asked for a percent-based threshold; to compute a percent we need a reference.
        # Here we use the fabric's "qty_available + outgoing" proxy via virtual_available,
        # so remaining_pct = (free_qty / max(virtual_available, 1)) * 100.
        # If you have a better "capacity" field (ex: lx_capacity_qty), replace base_qty with it.
        try:
            base_qty = float(fabric_prod.virtual_available)
        except Exception:
            base_qty = 0.0

        base_qty = max(base_qty, 1.0)
        remaining_pct = max(0.0, min(100.0, (free_qty / base_qty) * 100.0))
        used_pct = 100.0 - remaining_pct

        threshold_used_pct = self._get_used_threshold_pct()
        freeze = used_pct >= threshold_used_pct

        msg = DEFAULT_MSG if freeze else ""
        return (freeze, round(remaining_pct, 2), msg, True)

    def _cart_freeze_status(self, order):
        """
        Check ALL lines in cart; freeze if at least one template triggers freeze.
        Return stable schema for frontend.
        """
        if not order:
            return {
                "ok": True,
                "freeze": False,
                "ratio": 100.0,
                "msg": "",
                "hits": [],
            }

        hits = []
        worst_ratio = 100.0
        freeze_any = False

        for line in order.sudo().order_line:
            if line.display_type:
                continue
            pt = line.product_id.product_tmpl_id
            freeze, ratio, msg, applicable = self._should_freeze_template(pt)
            if not applicable:
                continue
            worst_ratio = min(worst_ratio, ratio)
            if freeze:
                freeze_any = True
                hits.append({
                    "product_tmpl_id": pt.id,
                    "product_name": pt.display_name,
                    "ratio": ratio,
                })

        return {
            "ok": True,
            "freeze": bool(freeze_any),
            "ratio": float(worst_ratio),
            "msg": DEFAULT_MSG if freeze_any else "",
            "hits": hits,
        }

    # ---------------------------------------------------------
    # Routes
    # ---------------------------------------------------------
    @http.route(['/shop/lx_freeze_check'], type='json', auth='public', website=True, csrf=False)
    def lx_freeze_check(self, product_template_id=None, **kw):
        try:
            pt_id = int(product_template_id or 0)
        except Exception:
            pt_id = 0

        pt = request.env["product.template"].sudo().browse(pt_id)
        if not pt or not pt.exists():
            return {"ok": False, "freeze": False, "ratio": 0.0, "msg": _("Product not found.")}

        freeze, ratio, msg, applicable = self._should_freeze_template(pt)

        # If no fabric ref, we return ok=True + freeze=False (so frontend doesn't block)
        return {
            "ok": True,
            "applicable": bool(applicable and bool(getattr(pt, "lx_fabric_ref_id", False))),
            "freeze": bool(freeze),
            "ratio": float(ratio),
            "msg": msg or "",
        }

    @http.route(['/shop/lx_freeze_check_cart'], type='json', auth='public', website=True, csrf=False)
    def lx_freeze_check_cart(self, **kw):
        order = _lx_sale_get_order()
        return self._cart_freeze_status(order)
