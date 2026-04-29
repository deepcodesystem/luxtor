# -*- coding: utf-8 -*-
import logging
from odoo import http
from odoo.http import request
from .express_service import _review_free_active

_logger = logging.getLogger(__name__)

FREE_CODES = ("INSTALL_SERVICE",)  # service codes eligible to become free (via discount)


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


# ── V19 compat helpers ────────────────────────────────────────────────────────

def _cart_remove_line(order, product_id, line_id):
    """Remove a specific order line — works on both V18 and V19."""
    try:
        order.with_context(skip_cart_verification=True)._cart_update_line_quantity(
            line_id=line_id, quantity=0
        )
    except AttributeError:
        order._cart_update(product_id=product_id, line_id=line_id, set_qty=0)


def _cart_add_product(order, product_id, qty):
    """Add/set product quantity — works on both V18 and V19."""
    try:
        order.with_context(skip_cart_verification=True)._cart_add(
            product_id=product_id, quantity=qty
        )
    except AttributeError:
        order._cart_update(product_id=product_id, set_qty=qty)


def _cart_set_line_qty(order, line, qty):
    """Set the quantity on an existing cart line on both V18 and V19."""
    try:
        order.with_context(skip_cart_verification=True)._cart_update_line_quantity(
            line_id=line.id, quantity=qty
        )
    except AttributeError:
        order._cart_update(product_id=line.product_id.id, line_id=line.id, set_qty=qty)


# ── Business logic helpers ─────────────────────────────────────────────────────

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
    return request.env["product.product"].sudo().search(
        [("default_code", "=", "INSTALL_SERVICE")], limit=1
    )


def _get_priority_product():
    return request.env["product.product"].sudo().search(
        [("default_code", "=", "PRIORITY_SERVICE")], limit=1
    )


def _mark_install_free(order):
    prod = _get_install_product()
    if not prod:
        return
    lines = order.order_line.filtered(
        lambda l: not l.display_type and (
            l.product_id.id == prod.id or
            l.product_id.product_tmpl_id.id == prod.product_tmpl_id.id
        )
    )
    if lines:
        keep = lines[:1]
        if (keep.discount or 0.0) < 100.0:
            keep.write({"discount": 100.0})
        for l in (lines - keep):
            _cart_remove_line(order, prod.id, l.id)


def _unmark_install_free(order):
    prod = _get_install_product()
    if not prod:
        return
    lines = order.order_line.filtered(
        lambda l: not l.display_type and (
            l.product_id.id == prod.id or
            l.product_id.product_tmpl_id.id == prod.product_tmpl_id.id
        )
    )
    for l in lines:
        if (l.discount or 0.0) >= 100.0:
            l.write({"discount": 0.0})


def _mark_delivery_free(order):
    dlines = order.order_line.filtered(
        lambda l: getattr(l, "is_delivery", False) and not l.display_type
    )
    for dl in dlines:
        if dl.price_unit != 0.0 or dl.discount != 0.0:
            dl.write({"price_unit": 0.0, "discount": 0.0})


def _find_priority_lines(order, product):
    return order.order_line.filtered(
        lambda l: not l.display_type and (
            l.product_id.id == product.id or
            l.product_id.product_tmpl_id.id == product.product_tmpl_id.id
        )
    )


def _find_install_lines(order, product):
    return order.order_line.filtered(
        lambda l: not l.display_type and (
            l.product_id.id == product.id or
            l.product_id.product_tmpl_id.id == product.product_tmpl_id.id
        )
    )


def _ensure_single_service_line(order, product, qty, finder):
    lines = finder(order, product)
    if lines:
        keep = lines[:1]
        if abs(float(keep.product_uom_qty or 0.0) - float(qty or 0.0)) > 1e-6:
            _cart_set_line_qty(order, keep, qty)
        for extra in (lines - keep):
            _cart_remove_line(order, extra.product_id.id, extra.id)
        return keep

    _cart_add_product(order, product.id, qty)
    return finder(order, product)[:1]


def _priority_is_free(order, product=None):
    product = product or _get_priority_product()
    if not product:
        return False
    base_price = float(product.lst_price or 0.0)
    return bool(base_price <= 0.0 or _review_free_active(order))


def _recompute_delivery_price(order):
    carrier = order.carrier_id
    if not carrier:
        return
    try:
        with request.env.cr.savepoint():
            res = carrier.rate_shipment(order)
        if isinstance(res, dict) and res.get("success"):
            new_price = float(res.get("price", 0.0))
            for dl in order.order_line.filtered(
                lambda l: getattr(l, "is_delivery", False) and not l.display_type
            ):
                dl.write({"price_unit": new_price, "discount": 0.0})
    except Exception:
        return


def _qty_mrp_total(order):
    qty_total = 0.0
    Bom = request.env["mrp.bom"].sudo()
    tmpl_ids = set()
    lines = []
    for line in order.sudo().order_line:
        p = line.product_id
        if not p or line.display_type:
            continue
        tid = p.product_tmpl_id.id
        tmpl_ids.add(tid)
        lines.append((line, tid))
    if not tmpl_ids:
        return 0.0
    boms = Bom.search([("product_tmpl_id", "in", list(tmpl_ids))])
    has_bom_tmpl = set(boms.mapped("product_tmpl_id").ids)
    for line, tid in lines:
        if tid in has_bom_tmpl:
            qty_total += float(line.product_uom_qty or 0.0)
    return qty_total


def _on_services_page():
    path = (request.httprequest.path or "").split("?")[0]
    if path in ("/shop/service", "/shop/services"):
        return True
    ref = request.httprequest.headers.get("Referer", "")
    return ("/shop/service" in ref) or ("/shop/services" in ref)


def _reapply_free_logic_services_only(order):
    if not _on_services_page():
        return
    try:
        with request.env.cr.savepoint():
            if hasattr(order, "_lx_sync_dimension_website_prices"):
                order._lx_sync_dimension_website_prices()
            if _free_applies(order):
                _mark_install_free(order)
                _mark_delivery_free(order)
            else:
                _unmark_install_free(order)
                _recompute_delivery_price(order)
    except Exception:
        _logger.exception("Luxtor services page failed to reapply free logic safely.")


# ── Controller ────────────────────────────────────────────────────────────────

class ServiceController(http.Controller):

    @http.route(['/shop/service', '/shop/services'], type='http', auth='public', website=True)
    def service_select(self, **post):
        order = _lx_sale_get_order()
        if not order:
            return request.redirect('/shop')
        order = order.sudo()

        _reapply_free_logic_services_only(order)

        Product = request.env['product.product'].sudo()
        p_priority = Product.search([('default_code', '=', 'PRIORITY_SERVICE')], limit=1)
        p_install  = Product.search([('default_code', '=', 'INSTALL_SERVICE')], limit=1)

        qty_mrp = _qty_mrp_total(order)
        priority_unit = float(p_priority.lst_price or 0.0) if p_priority else 0.0
        install_unit  = float(p_install.lst_price  or 0.0) if p_install  else 0.0
        priority_is_free = _priority_is_free(order, p_priority)
        install_is_free = _free_applies(order)

        if qty_mrp > 0.0 and p_priority and priority_is_free:
            priority_line = _ensure_single_service_line(order, p_priority, qty_mrp, _find_priority_lines)
            if priority_line:
                priority_line.write({
                    "price_unit": 0.0,
                    "discount": 0.0,
                    "tax_ids": [(5,)],
                })

        if qty_mrp > 0.0 and p_install and install_is_free:
            install_line = _ensure_single_service_line(order, p_install, qty_mrp, _find_install_lines)
            if install_line and abs(float(install_line.product_uom_qty or 0.0) - qty_mrp) > 1e-6:
                _cart_set_line_qty(order, install_line, qty_mrp)

        _reapply_free_logic_services_only(order)

        priority_selected = bool(p_priority and _find_priority_lines(order, p_priority))
        install_selected = bool(p_install and _find_install_lines(order, p_install))

        values = {
            "website_sale_order": order,
            "priority_unit":      priority_unit,
            "install_unit":       install_unit,
            "priority_is_free":   priority_is_free,
            "install_is_free":    install_is_free,
            "priority_selected":  priority_selected,
            "install_selected":   install_selected,
            "lx_free_applies":    install_is_free,
            "lx_free_threshold":  _get_threshold(),
            "qty_mrp":            qty_mrp,
        }
        # V19: inject checkout step navigation context
        try:
            values.update(request.website._get_checkout_step_values())
        except Exception:
            pass

        return request.render("luxtor_custom.service_select", values)

    @http.route(['/lx/mrp_qty'], type='json', auth='public', website=True, csrf=False)
    def mrp_qty(self):
        order = _lx_sale_get_order()
        if not order:
            return {'qty_total': 0.0}
        return {'qty_total': _qty_mrp_total(order)}

    @http.route('/lx/get_price_by_code', type='json', auth='public', website=True, csrf=False)
    def get_price_by_code(self, default_code=None, **kw):
        if not default_code:
            return {"ok": False, "error": "Missing default_code"}
        prod = request.env['product.product'].sudo().search(
            [('default_code', '=', default_code)], limit=1
        )
        if not prod:
            return {"ok": False, "error": f"No product found for code: {default_code}"}
        order = _lx_sale_get_order()
        free_now = _free_applies(order) if (order and _on_services_page()) else False
        return {
            "ok":           True,
            "default_code": default_code,
            "price":        float(prod.lst_price or 0.0),
            "free":         bool(free_now and default_code in FREE_CODES),
        }

    @http.route('/lx/has_service', type='json', auth='public', website=True, csrf=False)
    def has_service(self, code=None):
        order = _lx_sale_get_order()
        if not (order and code):
            return {"ok": True, "enabled": False}
        order = order.sudo()
        prod = request.env["product.product"].sudo().search(
            [("default_code", "=", code)], limit=1
        )
        if not prod:
            return {"ok": True, "enabled": False}
        enabled = bool(order.order_line.filtered(
            lambda l: not l.display_type and (
                l.product_id.id == prod.id or
                l.product_id.product_tmpl_id.id == prod.product_tmpl_id.id
            )
        ))
        return {"ok": True, "enabled": enabled}

    @http.route('/lx/service/apply', type='json', auth='public', website=True, csrf=False)
    def apply_service(self, code=None, enabled=False, qty=0.0):
        order = _lx_sale_get_order(force_create=True)
        if not order or not code:
            return {'ok': False}

        order = order.sudo()
        product = request.env['product.product'].sudo().search(
            [('default_code', '=', code)], limit=1
        )
        if not product:
            return {'ok': False}

        qty = float(qty or 0.0)
        currency = order.currency_id
        decimals = currency.decimal_places or 2
        symbol   = currency.symbol or ''

        # Special case: enabled but qty==0 → return visual preview
        if enabled and qty <= 0.0:
            unit_price = product.lst_price or 0.0
            try:
                bom_qty = _qty_mrp_total(order)
            except Exception:
                bom_qty = 0.0
            adjust = unit_price * bom_qty
            new_total = max(0.0, (order.amount_total or 0.0) - adjust)
            return {
                'ok':               True,
                'total':            new_total,
                'currency':         symbol,
                'decimals':         decimals,
                'applied_exception': True,
                'unit_price':       unit_price,
                'bom_qty':          bom_qty,
                'adjust':           adjust,
            }

        lines = order.order_line.filtered(
            lambda l: not l.display_type and (
                l.product_id.id == product.id or
                l.product_id.product_tmpl_id.id == product.product_tmpl_id.id
            )
        )

        if (not enabled) or qty <= 0.0:
            for l in lines:
                _cart_remove_line(order, product.id, l.id)
        else:
            if lines:
                keep = lines[:1]
                _cart_add_product(order, product.id, qty)
                for l in (lines - keep):
                    _cart_remove_line(order, product.id, l.id)
                keep.invalidate_recordset(['discount'])
            else:
                _cart_add_product(order, product.id, qty)

        _reapply_free_logic_services_only(order)
        order.invalidate_recordset(['amount_total', 'amount_delivery'])

        return {
            'ok':       True,
            'total':    order.amount_total,
            'currency': symbol,
            'decimals': decimals,
        }

    @http.route('/lx/service/remove', type='json', auth='public', website=True, csrf=False)
    def remove_service(self, code=None):
        order = _lx_sale_get_order(force_create=True)
        if not order or not code:
            return {'ok': False}
        order = order.sudo()
        product = request.env['product.product'].sudo().search(
            [('default_code', '=', code)], limit=1
        )
        if not product:
            return {'ok': False}

        lines = order.order_line.filtered(
            lambda l: not l.display_type and (
                l.product_id.id == product.id or
                l.product_id.product_tmpl_id.id == product.product_tmpl_id.id
            )
        )
        for l in lines:
            _cart_remove_line(order, product.id, l.id)

        _reapply_free_logic_services_only(order)
        order.invalidate_recordset(['amount_total', 'amount_delivery'])
        return {
            'ok':       True,
            'total':    order.amount_total,
            'currency': order.currency_id.symbol or 'DH',
            'decimals': order.currency_id.decimal_places or 2,
        }
