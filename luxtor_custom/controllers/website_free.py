# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale


# ---------- helpers ----------
def _get_threshold():
    ICP = request.env["ir.config_parameter"].sudo()
    val = ICP.get_param("luxtor.lx_free_amount_order", default="5000")
    try:
        return float(val)
    except Exception:
        return 5000.0

def _is_service_line(line):
    p = line.product_id
    if not p:
        return False
    code = (p.default_code or "").strip().upper()
    tcode = (p.product_tmpl_id.default_code or "").strip().upper()
    return code in ("INSTALL_SERVICE", "PRIORITY_SERVICE") or tcode in ("INSTALL_SERVICE", "PRIORITY_SERVICE")

def _merch_total_excl_services(order):
    total = 0.0
    for l in order.order_line:
        if l.display_type:
            continue
        if getattr(l, "is_delivery", False):
            continue
        if hasattr(l, "is_tip") and l.is_tip:
            continue
        if hasattr(l, "is_downpayment") and l.is_downpayment:
            continue
        if _is_service_line(l):
            continue
        total += float(l.price_total or 0.0)
    return total

def _free_applies(order):
    return bool(order) and (_merch_total_excl_services(order) >= _get_threshold())

def _get_install_product():
    return request.env["product.product"].sudo().search([("default_code", "=", "INSTALL_SERVICE")], limit=1)

def _mark_install_free(order):
    prod = _get_install_product()
    if not prod:
        return
    lines = order.order_line.filtered(
        lambda l: not l.display_type and (l.product_id.id == prod.id or l.product_id.product_tmpl_id.id == prod.product_tmpl_id.id)
    )
    if lines:
        keep = lines[:1]
        if (keep.discount or 0.0) < 100.0:
            keep.write({"discount": 100.0})
        for l in (lines - keep):
            order._cart_update(product_id=prod.id, line_id=l.id, set_qty=0)

def _unmark_install_free(order):
    prod = _get_install_product()
    if not prod:
        return
    lines = order.order_line.filtered(
        lambda l: not l.display_type and (l.product_id.id == prod.id or l.product_id.product_tmpl_id.id == prod.product_tmpl_id.id)
    )
    for l in lines:
        if (l.discount or 0.0) >= 100.0:
            l.write({"discount": 0.0})

def _mark_delivery_free(order):
    dlines = order.order_line.filtered(lambda l: getattr(l, "is_delivery", False) and not l.display_type)
    for dl in dlines:
        if dl.price_unit != 0.0 or dl.discount != 0.0:
            dl.write({"price_unit": 0.0, "discount": 0.0})

def _recompute_delivery_price(order):
    carrier = order.carrier_id
    if not carrier:
        return
    try:
        res = carrier.rate_shipment(order)
        if isinstance(res, dict) and res.get("success"):
            price = float(res.get("price", 0.0))
            for dl in order.order_line.filtered(lambda l: getattr(l, "is_delivery", False) and not l.display_type):
                dl.write({"price_unit": price, "discount": 0.0})
    except Exception:
        return

def _reapply_free_logic(order):
    if _free_applies(order):
        _mark_install_free(order)
        _mark_delivery_free(order)
    else:
        _unmark_install_free(order)
        _recompute_delivery_price(order)

def _sum_by_code(order, code):
    total = 0.0
    for l in order.order_line:
        if l.display_type:
            continue
        p = l.product_id
        if not p:
            continue
        if (p.default_code or "").upper() == code or (p.product_tmpl_id.default_code or "").upper() == code:
            total += float(l.price_total or 0.0)
    return total

def _inject_totals(ctx, order):
    """Compute and inject all variables that your template expects."""
    if not order:
        ctx.update({
            "lx_free_applies": False,
            "lx_free_threshold": _get_threshold(),
            "lx_priority_total": 0.0,
            "lx_install_total": 0.0,
        })
        return

    order = order.sudo()
    ctx.update({
        "lx_free_applies": _free_applies(order),
        "lx_free_threshold": _get_threshold(),
        "lx_priority_total": _sum_by_code(order, "PRIORITY_SERVICE"),
        "lx_install_total":  _sum_by_code(order, "INSTALL_SERVICE"),
    })


# ---------- routes ----------
class WebsiteSaleFreeServer(http.Controller):
    def _lx_inject(self, response, order):
        if getattr(response, "qcontext", None) is not None:
            response.qcontext["website_sale_order"] = order
            _inject_totals(response.qcontext, order)
        return response

    @http.route(['/shop/cart'], type='http', auth='public', website=True)
    def cart(self, access_token=None, revive='', **post):
        order = request.website.sale_get_order()
        if order:
            order = order.sudo()
            _reapply_free_logic(order)
            order.invalidate_recordset(['amount_total', 'amount_delivery', 'amount_untaxed', 'amount_tax'])
            order = request.env['sale.order'].sudo().browse(order.id).exists()
        ws = WebsiteSale()
        resp = ws.cart(access_token=access_token, revive=revive, **post)
        fresh_order = order or request.website.sale_get_order()
        if fresh_order:
            fresh_order = fresh_order.sudo()
        return self._lx_inject(resp, fresh_order)

    @http.route(['/shop/cart/update_json'], type='json', auth='public', website=True, csrf=False)
    def cart_update_json(self, **kwargs):
        ws = WebsiteSale()
        result = ws.cart_update_json(**kwargs)
        order = request.website.sale_get_order()
        if order:
            order = order.sudo()
            _reapply_free_logic(order)
            order.invalidate_recordset(['amount_total', 'amount_delivery', 'amount_untaxed', 'amount_tax'])
            result.update({
                "amount_total": order.amount_total,
                "amount_delivery": order.amount_delivery,
                "amount_untaxed": order.amount_untaxed,
                "amount_tax": order.amount_tax,
            })
        return result

    @http.route(['/shop/update_carrier'], type='json', auth='public', website=True, csrf=False)
    def update_carrier(self, **kwargs):
        ws = WebsiteSale()
        result = ws.update_carrier(**kwargs)
        order = request.website.sale_get_order()
        if order:
            order = order.sudo()
            _reapply_free_logic(order)
            order.invalidate_recordset(['amount_total', 'amount_delivery', 'amount_untaxed', 'amount_tax'])
            result.update({
                "amount_total": order.amount_total,
                "amount_delivery": order.amount_delivery,
                "amount_untaxed": order.amount_untaxed,
                "amount_tax": order.amount_tax,
            })
        return result
