# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from markupsafe import Markup

def _coerce_dim(v):
    try:
        f = float(v or 0.0)
    except Exception:
        f = 0.0
    return 1.0 if f <= 0.0 else f

def _coerce_int(v):
    try:
        i = int(v or 0)
    except Exception:
        i = 0
    return i if i > 0 else 0

def _has_bom(product):
    tmpl = product.product_tmpl_id
    return bool(tmpl and tmpl.bom_ids)

class LxCartDimsController(http.Controller):

    @http.route("/lx/cart/update_dims", type="json", auth="public", website=True, csrf=True)
    def lx_update_dims(self, line_id=None, width_m=None, height_m=None):
        order = request.website.sale_get_order()
        if not order:
            return {"ok": False, "error": "no_cart"}

        try:
            line_id = int(line_id or 0)
        except Exception:
            line_id = 0
        line = order.order_line.browse(line_id)
        if not line or not line.exists() or line.order_id.id != order.id:
            return {"ok": False, "error": "line_not_found"}

        if _has_bom(line.product_id):
            vals = {}
            if width_m is not None:  vals["lx_width_m"] = _coerce_dim(width_m)
            if height_m is not None: vals["lx_height_m"] = _coerce_dim(height_m)
            if vals: line.sudo(False).write(vals)
        else:
            vals = {}
            if width_m is not None:  vals["lx_width_m"] = 1.0
            if height_m is not None: vals["lx_height_m"] = 1.0
            if vals: line.sudo(False).write(vals)

        order.invalidate_recordset()

        def _money(v):
            return request.env["ir.qweb.field.monetary"].value_to_html(v, {"display_currency": order.currency_id})

        lines_payload = []
        for l in order.order_line.filtered(lambda r: not r.display_type):
            size = (l.lx_width_m or 0.0) * (l.lx_height_m or 0.0)
            if not _has_bom(l.product_id) or size <= 0:
                size = 1.0
            eff_qty = size * (l.product_uom_qty or 0.0)
            lines_payload.append({
                "line_id": l.id,
                "qty": l.product_uom_qty,
                "width_m": l.lx_width_m or 1.0,
                "height_m": l.lx_height_m or 1.0,
                "size": size,
                "effective_qty": eff_qty,
                "subtotal": Markup(_money(l.price_subtotal)).unescape(),
                "tax": Markup(_money(l.price_tax)).unescape(),
                "total": Markup(_money(l.price_total)).unescape(),
            })

        totals = {
            "untaxed": Markup(_money(order.amount_untaxed)).unescape(),
            "tax":     Markup(_money(order.amount_tax)).unescape(),
            "total":   Markup(_money(order.amount_total)).unescape(),
        }
        return {"ok": True, "order_totals": totals, "lines": lines_payload}


# Hook add-to-cart to copy your product page dims onto the new SOL
from odoo.addons.website_sale.controllers.main import WebsiteSale

class WebsiteSaleDimsHook(WebsiteSale):

    @http.route(['/shop/cart/update'], type='http', auth="public", website=True, sitemap=False)
    def cart_update(self, product_id, add_qty=1, set_qty=0, **kw):
        resp = super().cart_update(product_id, add_qty=add_qty, set_qty=set_qty, **kw)
        width  = _coerce_dim(kw.get("lx_width_m"))
        height = _coerce_dim(kw.get("lx_height_m"))
        location_id = _coerce_int(kw.get("lx_location_id"))

        order = request.website.sale_get_order()
        if order:
            pid = int(product_id)
            matched_lines = order._cart_find_product_line(
                product_id=pid,
                lx_width_m=width,
                lx_height_m=height,
                lx_location_id=location_id or False,
            )
            if not matched_lines:
                matched_lines = order.order_line.filtered(
                    lambda x: not x.display_type and x.product_id.id == pid
                )[:1]
            for l in matched_lines:
                vals = (
                    {"lx_width_m": width, "lx_height_m": height}
                    if _has_bom(l.product_id)
                    else {"lx_width_m": 1.0, "lx_height_m": 1.0}
                )
                if location_id:
                    vals["lx_location_id"] = location_id
                l.sudo(False).write(vals)
            order.invalidate_recordset()
        return resp
