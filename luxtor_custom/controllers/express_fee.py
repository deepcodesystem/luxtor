# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from contextlib import contextmanager


PRIORITY_CODE = "PRIORITY_SERVICE"


# ---------- helpers ----------

@contextmanager
def _savepoint(env):
    """Avoid partially-removed states on unexpected errors."""
    env.cr.execute("SAVEPOINT lx_priority_rm")
    try:
        yield
    except Exception:
        env.cr.execute("ROLLBACK TO SAVEPOINT lx_priority_rm")
        raise
    finally:
        env.cr.execute("RELEASE SAVEPOINT lx_priority_rm")


def _refresh_totals_dict(order, unit_price, symbol, decimals):
    """Force recomputation of key totals before returning."""
    fields_to_invalidate = ["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"]
    order.invalidate_recordset(fields_to_invalidate)
    recompute = getattr(order, "_amount_all", None)
    if callable(recompute):
        recompute()
        order.invalidate_recordset(fields_to_invalidate)
    return {
        "ok": True,
        "enabled": False,
        "qty": 0.0,
        "unit_price": unit_price,
        "bom_qty": _qty_mrp_total(order),
        "total": order.amount_total,
        "amount_delivery": order.amount_delivery,
        "amount_untaxed": order.amount_untaxed,
        "amount_tax": order.amount_tax,
        "currency": symbol,
        "decimals": decimals,
    }

def _get_priority_product():
    return request.env["product.product"].sudo().search([("default_code", "=", PRIORITY_CODE)], limit=1)


# def _qty_mrp_total(order):
#     """Sum quantities of lines that have a BoM (used as default qty for the service)."""
#     qty_total = 0.0
#     for line in order.sudo().order_line:
#         p = line.product_id
#         if not p or line.display_type:
#             continue
#         if not (p.product_tmpl_id.bom_ids or getattr(p, "bom_count", 0)):
#             continue
#         qty_total += float(line.product_uom_qty or 0.0)
#     return qty_total

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

    # get templates that have at least one BoM
    boms = Bom.search([("product_tmpl_id", "in", list(tmpl_ids))])
    has_bom_tmpl = set(boms.mapped("product_tmpl_id").ids)

    for line, tid in lines:
        if tid in has_bom_tmpl:
            qty_total += float(line.product_uom_qty or 0.0)

    return qty_total



def _find_priority_lines(order, product):
    return order.order_line.filtered(
        lambda l: not l.display_type and (
            l.product_id.id == product.id or
            l.product_id.product_tmpl_id.id == product.product_tmpl_id.id
        )
    )


def _currency_meta(order):
    cur = order.currency_id
    return (cur.symbol or ""), (cur.decimal_places or 2)


def _compute_unit_price(product, order):
    product = product.sudo()
    order = order.sudo()
    return float(product.lst_price or 0.0)


# ---------- controller ----------
class PriorityServiceController(http.Controller):
    """
    Priority-only endpoints (NO free/threshold logic).
    """

    @http.route("/lx/priority/price", type="json", auth="public", website=True, csrf=False)
    def priority_price(self, **kw):
        order = request.website.sale_get_order()
        prod = _get_priority_product()
        if not (order and prod):
            return {"ok": False, "error": "Order or PRIORITY_SERVICE not found"}

        symbol, decimals = _currency_meta(order)
        unit_price = _compute_unit_price(prod, order)

        return {
            "ok": True,
            "default_code": PRIORITY_CODE,
            "unit_price": unit_price,     # already aligned to tax-display/pricelist
            "currency": symbol,
            "decimals": decimals,
        }

    @http.route("/lx/priority/mrp_qty", type="json", auth="public", website=True, csrf=False)
    def priority_mrp_qty(self, **kw):
        order = request.website.sale_get_order()
        if not order:
            return {"ok": True, "qty_total": 0.0}
        return {"ok": True, "qty_total": _qty_mrp_total(order)}

    @http.route("/lx/priority/has", type="json", auth="public", website=True, csrf=False)
    def priority_has(self, **kw):
        order = request.website.sale_get_order()
        prod = _get_priority_product()
        if not (order and prod):
            return {"ok": True, "enabled": False}
        return {"ok": True, "enabled": bool(_find_priority_lines(order.sudo(), prod))}

    @http.route("/lx/priority/apply", type="json", auth="public", website=True, csrf=False)
    def priority_apply(self, enabled=False, qty=0.0, **kw):
        order = request.website.sale_get_order(force_create=1)
        prod = _get_priority_product()
        if not (order and prod):
            return {"ok": False}

        order = order.sudo()
        symbol, decimals = _currency_meta(order)
        unit_price = _compute_unit_price(prod, order)

        try:
            qty = float(qty or 0.0)
        except Exception:
            qty = 0.0

        if enabled and qty <= 0.0:
            qty = _qty_mrp_total(order)

        lines = _find_priority_lines(order, prod)

        if (not enabled) or qty <= 0.0:
            for l in lines:
                order._cart_update(product_id=prod.id, line_id=l.id, set_qty=0)
            order._cart_update(product_id=prod.id, set_qty=0)
        else:
            if lines:
                keep = lines[:1]
                order._cart_update(product_id=prod.id, line_id=keep.id, set_qty=qty)
                for l in (lines - keep):
                    order._cart_update(product_id=prod.id, line_id=l.id, set_qty=0)
            else:
                order._cart_update(product_id=prod.id, set_qty=qty)

        order.invalidate_recordset(["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"])

        return {
            "ok": True,
            "enabled": bool(enabled and qty > 0.0),
            "qty": qty,
            "unit_price": unit_price,
            "bom_qty": _qty_mrp_total(order),
            "total": order.amount_total,
            "amount_delivery": order.amount_delivery,
            "amount_untaxed": order.amount_untaxed,
            "amount_tax": order.amount_tax,
            "currency": symbol,
            "decimals": decimals,
        }





    # -----------------------------
    # Controller Route
    # -----------------------------
    @http.route("/lx/priority/remove", type="json", auth="public", website=True, csrf=False)
    def priority_remove(self, **kw):
        order = request.website.sale_get_order(force_create=1)
        prod = _get_priority_product()
        if not (order and prod):
            return {"ok": False}

        order = order.sudo()
        symbol, decimals = _currency_meta(order)
        unit_price = _compute_unit_price(prod, order)

        with _savepoint(request.env):
            lines = _find_priority_lines(order, prod)
            for l in lines:
                try:
                    order.with_context(skip_cart_verification=True)._cart_update_line_quantity(
                        line_id=l.id, quantity=0
                    )
                except AttributeError:
                    order._cart_update(product_id=l.product_id.id, line_id=l.id, set_qty=0)

            # 2️⃣ Safety cleanup: unlink leftovers if still present
            leftover = _find_priority_lines(order, prod)
            if leftover:
                leftover.unlink()

        # 3️⃣ Return refreshed totals
        return _refresh_totals_dict(order, unit_price, symbol, decimals)