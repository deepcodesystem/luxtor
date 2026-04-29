# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
from contextlib import contextmanager
from odoo.addons.website_sale.controllers.main import WebsiteSale


INSTALL_CODE = "INSTALL_SERVICE"
PRIORITY_CODE = "PRIORITY_SERVICE"


def _lx_sale_get_order(force_create=False):
    """V19-compatible cart order getter — replaces website.sale_get_order()."""
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


def _cart_remove_line(order, product_id, line_id):
    """V19-compatible: remove a specific order line."""
    try:
        order.with_context(skip_cart_verification=True)._cart_update_line_quantity(
            line_id=line_id, quantity=0
        )
    except AttributeError:
        order._cart_update(product_id=product_id, line_id=line_id, set_qty=0)


def _cart_add_product(order, product_id, qty):
    """V19-compatible: add or update a product in the cart."""
    try:
        order.with_context(skip_cart_verification=True)._cart_add(
            product_id=product_id, quantity=qty
        )
    except AttributeError:
        order._cart_update(product_id=product_id, set_qty=qty)


def _cart_set_line_qty(order, line, qty):
    """V19-compatible: set the quantity on an existing cart line."""
    try:
        order.with_context(skip_cart_verification=True)._cart_update_line_quantity(
            line_id=line.id, quantity=qty
        )
    except AttributeError:
        order._cart_update(product_id=line.product_id.id, line_id=line.id, set_qty=qty)


# =========================
# Helpers (free logic etc.)
# =========================

@contextmanager
def _savepoint(env, name="lx_install_sp"):
    """Avoid partially-removed states on unexpected errors."""
    env.cr.execute(f"SAVEPOINT {name}")
    try:
        yield
    except Exception:
        env.cr.execute(f"ROLLBACK TO {name}")
        raise
    finally:
        env.cr.execute(f"RELEASE SAVEPOINT {name}")


def _get_threshold():
    ICP = request.env["ir.config_parameter"].sudo()
    val = ICP.get_param("luxtor.lx_free_amount_order", default="5000")
    try:
        return float(val)
    except Exception:
        return 5000.0


def _is_service_line(line):
    p = line.product_id
    if not p or line.display_type:
        return False
    code = (p.default_code or "").strip().upper()
    tcode = (p.product_tmpl_id.default_code or "").strip().upper()
    return code in ("INSTALL_SERVICE", "PRIORITY_SERVICE") or tcode in ("INSTALL_SERVICE", "PRIORITY_SERVICE")


def _merch_total_excl_services(order):
    """Sum order price_total excluding delivery and service SKUs."""
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
    return request.env["product.product"].sudo().search([("default_code", "=", INSTALL_CODE)], limit=1)


def _find_install_lines(order, product):
    return order.order_line.filtered(
        lambda l: not l.display_type and (
            l.product_id.id == product.id or
            l.product_id.product_tmpl_id.id == product.product_tmpl_id.id
        )
    )


def _find_service_lines_by_code(order, code):
    service_code = (code or "").strip().upper()
    return order.order_line.filtered(
        lambda l: not l.display_type
        and l.product_id
        and (
            (l.product_id.default_code or "").strip().upper() == service_code
            or (l.product_id.product_tmpl_id.default_code or "").strip().upper() == service_code
        )
    )


def _sync_selected_service_quantities(order):
    """
    Keep already-enabled service lines aligned with the current BoM-based quantity.
    This makes qty changes reliable after cart edits and back/forward navigation.
    """
    if not order:
        return

    target_qty = float(_qty_mrp_total(order) or 0.0)
    for code in (PRIORITY_CODE, INSTALL_CODE):
        lines = _find_service_lines_by_code(order, code)
        if not lines:
            continue

        if target_qty <= 0.0:
            for line in lines:
                _cart_remove_line(order, line.product_id.id, line.id)
            continue

        keep = lines[:1]
        current_qty = float(keep.product_uom_qty or 0.0)
        if abs(current_qty - target_qty) > 1e-6:
            _cart_set_line_qty(order, keep, target_qty)

        for extra in (lines - keep):
            _cart_remove_line(order, extra.product_id.id, extra.id)


def _mark_install_free(order):
    """
    Installation free via 100% discount (keep price_unit visible for UI).
    Deduplicate extra install lines.
    """
    prod = _get_install_product()
    if not prod:
        return
    lines = _find_install_lines(order, prod)
    if lines:
        keep = lines[:1]
        if (keep.discount or 0.0) < 100.0:
            keep.write({"discount": 100.0})
        for l in (lines - keep):
            _cart_remove_line(order, prod.id, l.id)


def _unmark_install_free(order):
    """Remove forced 100% discount if present."""
    prod = _get_install_product()
    if not prod:
        return
    lines = _find_install_lines(order, prod)
    for l in lines:
        if (l.discount or 0.0) >= 100.0:
            l.write({"discount": 0.0})


def _mark_delivery_free(order):
    """Delivery free = set price_unit=0 (no discount)."""
    dlines = order.order_line.filtered(lambda l: getattr(l, "is_delivery", False) and not l.display_type)
    for dl in dlines:
        if dl.price_unit != 0.0 or (getattr(dl, "discount", 0.0) or 0.0) != 0.0:
            dl.write({"price_unit": 0.0, "discount": 0.0})


def _recompute_delivery_price(order):
    """Restore real carrier price when not free."""
    carrier = order.carrier_id
    if not carrier:
        return
    try:
        with request.env.cr.savepoint():
            res = carrier.rate_shipment(order)
        if isinstance(res, dict) and res.get("success"):
            new_price = float(res.get("price", 0.0))
            for dl in order.order_line.filtered(lambda l: getattr(l, "is_delivery", False) and not l.display_type):
                dl.write({"price_unit": new_price, "discount": 0.0})
    except Exception:
        return


def _on_free_pages():
    """
    Free logic and qweb flags must be active on services + cart/checkout/payment.
    """
    path = (request.httprequest.path or "").split("?")[0]
    if path in ("/shop/service", "/shop/services", "/shop/cart", "/shop/checkout", "/shop/payment"):
        return True
    ref = request.httprequest.headers.get("Referer", "") or ""
    return any(p in ref for p in ("/shop/service", "/shop/services", "/shop/cart", "/shop/checkout", "/shop/payment"))


def _reapply_free_logic(order):
    """Apply/remove free rules on eligible pages."""
    if not order:
        return
    if hasattr(order, "_lx_sync_dimension_website_prices"):
        order._lx_sync_dimension_website_prices()
    _sync_selected_service_quantities(order)
    if _on_free_pages():
        if _free_applies(order):
            _mark_install_free(order)   # install → discount=100 (keep price_unit)
            _mark_delivery_free(order)  # delivery → price_unit=0
        else:
            _unmark_install_free(order)
            _recompute_delivery_price(order)


# def _qty_mrp_total(order):
#     """Sum quantities of lines that have a BoM — default qty for the service."""
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



def _currency_meta(order):
    cur = order.currency_id
    return (cur.symbol or " DH"), int(cur.decimal_places or 2)


def _fmt_money_en(amount, decimals=2, currency_symbol=" DH"):
    """Format like 3,250.50 DH regardless of user locale."""
    space = "" if not currency_symbol or currency_symbol.startswith(" ") else " "
    return f"{amount:,.{decimals}f}{space}{currency_symbol}".rstrip()


def _compute_unit_price(product, order):
    """Use list price; UI shows price_unit, discount handles free."""
    product = product.sudo()
    return float(product.lst_price or 0.0)


def _invalidate_totals(order):
    fields = ["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"]
    order.invalidate_recordset(fields)
    recompute = getattr(order, "_amount_all", None)
    if callable(recompute):
        recompute()
        order.invalidate_recordset(fields)


def _inject_lx(ctx, order):
    """
    Expose flags so <t t-if='lx_free_applies'> and comparisons work on all pages.
    IMPORTANT: also expose lx_merch_total to avoid template errors when compared.
    """
    if ctx is None or order is None:
        return
    ctx["lx_free_threshold"] = _get_threshold()
    ctx["lx_merch_total"] = _merch_total_excl_services(order)
    ctx["lx_free_applies"] = bool(ctx["lx_merch_total"] >= ctx["lx_free_threshold"])


# =========================
# Controller (Installation)
# =========================
class InstallServiceController(http.Controller):
    """
    Installation endpoints (with free threshold logic for install & delivery).
    """

    # ---- Read-only endpoints ----
    @http.route("/lx/install/price", type="json", auth="public", website=True, csrf=False)
    def install_price(self, **kw):
        order = _lx_sale_get_order()
        prod = _get_install_product()
        if not (order and prod):
            return {"ok": False, "error": "Order or INSTALL_SERVICE not found"}

        currency_symbol, decimals = _currency_meta(order)
        unit_price = _compute_unit_price(prod, order)
        is_free = _free_applies(order)

        return {
            "ok": True,
            "default_code": INSTALL_CODE,
            "unit_price": unit_price,
            "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
            "unit_label": "Free" if is_free else f"+({unit_price:.2f} {currency_symbol})",
            "is_free": is_free,
            "currency": currency_symbol,
            "decimals": decimals,
        }

    @http.route("/lx/install/mrp_qty", type="json", auth="public", website=True, csrf=False)
    def install_mrp_qty(self, **kw):
        order = _lx_sale_get_order()
        if not order:
            return {"ok": True, "qty_total": 0.0}
        return {"ok": True, "qty_total": _qty_mrp_total(order)}

    @http.route("/lx/install/has", type="json", auth="public", website=True, csrf=False)
    def install_has(self, **kw):
        order = _lx_sale_get_order()
        prod = _get_install_product()
        if not (order and prod):
            return {"ok": True, "enabled": False, "is_free": False}
        enabled = bool(_find_install_lines(order.sudo(), prod))
        return {"ok": True, "enabled": enabled, "is_free": _free_applies(order)}

    # ---- Mutating endpoints ----
    @http.route("/lx/install/apply", type="json", auth="public", website=True, csrf=False)
    def install_apply(self, enabled=False, qty=0.0, **kw):
        """
        Toggle/add Installation service with the given qty (defaults to BoM qty).
        Applies free rules (on eligible pages):
          - Install: 100% discount (price_unit kept for UI)
          - Delivery: price_unit=0
        """
        order = _lx_sale_get_order(force_create=True)
        prod = _get_install_product()
        if not (order and prod):
            return {"ok": False}

        order = order.sudo()
        currency_symbol, decimals = _currency_meta(order)
        unit_price = _compute_unit_price(prod, order)

        try:
            qty = float(qty or 0.0)
        except Exception:
            qty = 0.0

        if enabled and qty <= 0.0:
            qty = _qty_mrp_total(order)

        lines = _find_install_lines(order, prod)

        if (not enabled) or qty <= 0.0:
            with _savepoint(request.env, "lx_install_rm1"):
                for l in lines:
                    _cart_remove_line(order, prod.id, l.id)
                _find_install_lines(order, prod).unlink()
        else:
            if lines:
                keep = lines[:1]
                _cart_add_product(order, prod.id, qty)
                for l in (lines - keep):
                    _cart_remove_line(order, prod.id, l.id)
                keep.invalidate_recordset(["discount"])
            else:
                _cart_add_product(order, prod.id, qty)

        # Re-apply FREE logic (install discount & delivery zero) on eligible pages
        _reapply_free_logic(order)
        _invalidate_totals(order)

        return {
            "ok": True,
            "enabled": bool(enabled and qty > 0.0),
            "qty": qty if enabled else 0.0,
            "unit_price": unit_price,
            "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
            "unit_label": "Free" if _free_applies(order) else f"+({unit_price:.2f} {currency_symbol})",
            "is_free": _free_applies(order),
            "bom_qty": _qty_mrp_total(order),
            "total": order.amount_total,
            "total_formatted": _fmt_money_en(order.amount_total, decimals, currency_symbol),
            "amount_delivery": order.amount_delivery,
            "amount_untaxed": order.amount_untaxed,
            "amount_tax": order.amount_tax,
            "currency": currency_symbol,
            "decimals": decimals,
        }

    @http.route("/lx/install/remove", type="json", auth="public", website=True, csrf=False)
    def install_remove(self, **kw):
        """
        Robust remove with a DB savepoint + hard cleanup,
        then re-apply free logic for delivery and totals.
        """
        order = _lx_sale_get_order(force_create=True)
        prod = _get_install_product()
        if not (order and prod):
            return {"ok": False}

        order = order.sudo()
        currency_symbol, decimals = _currency_meta(order)
        unit_price = _compute_unit_price(prod, order)

        with _savepoint(request.env, "lx_install_rm2"):
            lines = _find_install_lines(order, prod)
            for l in lines:
                _cart_remove_line(order, l.product_id.id, l.id)
            _find_install_lines(order, prod).unlink()

        # Re-apply FREE logic (delivery may change after removing install)
        _reapply_free_logic(order)
        _invalidate_totals(order)

        return {
            "ok": True,
            "enabled": False,
            "qty": 0.0,
            "unit_price": unit_price,
            "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
            "unit_label": "Free" if _free_applies(order) else f"+({unit_price:.2f} {currency_symbol})",
            "is_free": _free_applies(order),
            "bom_qty": _qty_mrp_total(order),
            "total": order.amount_total,
            "total_formatted": _fmt_money_en(order.amount_total, decimals, currency_symbol),
            "amount_delivery": order.amount_delivery,
            "amount_untaxed": order.amount_untaxed,
            "amount_tax": order.amount_tax,
            "currency": currency_symbol,
            "decimals": decimals,
        }

    @http.route("/lx/services/resync_active", type="json", auth="public", website=True, csrf=False)
    def services_resync_active(self, **kw):
        """
        Re-apply currently active website services after a cart quantity change.
        This gives the same effect as toggling active services off/on again,
        but keeps the operation server-side and preserves the current UI state.
        """
        order = _lx_sale_get_order()
        if not order:
            return {"ok": True, "resynced": False}

        order = order.sudo()
        priority_lines = _find_service_lines_by_code(order, PRIORITY_CODE)
        install_lines = _find_service_lines_by_code(order, INSTALL_CODE)
        had_active_services = bool(priority_lines or install_lines)

        if not had_active_services:
            return {
                "ok": True,
                "resynced": False,
                "priority_enabled": False,
                "install_enabled": False,
                "bom_qty": _qty_mrp_total(order),
                "amount_total": order.amount_total,
                "amount_delivery": order.amount_delivery,
                "amount_untaxed": order.amount_untaxed,
                "amount_tax": order.amount_tax,
            }

        _reapply_free_logic(order)
        _invalidate_totals(order)

        return {
            "ok": True,
            "resynced": True,
            "priority_enabled": bool(_find_service_lines_by_code(order, PRIORITY_CODE)),
            "install_enabled": bool(_find_service_lines_by_code(order, INSTALL_CODE)),
            "bom_qty": _qty_mrp_total(order),
            "amount_total": order.amount_total,
            "amount_delivery": order.amount_delivery,
            "amount_untaxed": order.amount_untaxed,
            "amount_tax": order.amount_tax,
        }


# =========================
# WebsiteSale extension
# - Keep your working /shop/cart route override
# - Avoid overriding routes for checkout/payment
#   -> inject flags via *_values helpers
# =========================
class LxWebsiteSaleInstallExt(WebsiteSale):

    # Keep your existing cart route override (working)
    @http.route(['/shop/cart'], type='http', auth='public', website=True, sitemap=False)
    def cart(self, access_token=None, revive='', **post):
        order = _lx_sale_get_order()
        _reapply_free_logic(order)
        res = super().cart(access_token=access_token, revive=revive, **post)
        if hasattr(res, "qcontext"):
            _inject_lx(res.qcontext, order)
        return res


    def _get_shop_payment_values(self, order, **kwargs):
        _reapply_free_logic(order)
        values = super()._get_shop_payment_values(order, **kwargs)
        _inject_lx(values, order)
        return values

    def _get_shop_cart_values(self, **kw):
        values = super()._get_shop_cart_values(**kw)
        order = _lx_sale_get_order()
        _inject_lx(values, order)
        return values

    # Keep your JSON endpoints as-is (no change)
    @http.route(['/shop/cart/update_json'], type='json', auth='public', website=True, csrf=False)
    def cart_update_json(self, **kwargs):
        result = super().cart_update_json(**kwargs)
        order = _lx_sale_get_order()
        if order:
            order = order.sudo()
            _reapply_free_logic(order)
            _invalidate_totals(order)
            if _on_free_pages():
                result.update({
                    "amount_total": order.amount_total,
                    "amount_delivery": order.amount_delivery,
                    "amount_untaxed": order.amount_untaxed,
                    "amount_tax": order.amount_tax,
                })
        return result

    @http.route(['/shop/update_carrier'], type='json', auth='public', website=True, csrf=False)
    def update_carrier(self, **kwargs):
        result = super().update_carrier(**kwargs)
        order = _lx_sale_get_order()
        if order:
            order = order.sudo()
            _reapply_free_logic(order)
            _invalidate_totals(order)
            if _on_free_pages():
                result.update({
                    "amount_total": order.amount_total,
                    "amount_delivery": order.amount_delivery,
                    "amount_untaxed": order.amount_untaxed,
                    "amount_tax": order.amount_tax,
                })
        return result

class LxDebugFlags(http.Controller):
    @http.route("/lx/debug/flags", type="json", auth="public", website=True, csrf=False)
    def debug_flags(self, **kw):
        order = _lx_sale_get_order()
        if not order:
            return {"ok": True, "flags": {}, "note": "no active order"}
        flags = {
            "lx_free_threshold": _get_threshold(),
            "lx_merch_total": _merch_total_excl_services(order),
            "lx_free_applies": _free_applies(order),
            "path": (request.httprequest.path or "").split("?")[0],
        }
        return {"ok": True, "flags": flags}




# # =========================
# # Helpers (free logic etc.)
# # =========================
# @contextmanager
# def _savepoint(env):
#     """Avoid partially-removed states on unexpected errors."""
#     env.cr.execute("SAVEPOINT lx_install_rm")
#     try:
#         yield
#     except Exception:
#         env.cr.execute("ROLLBACK TO SAVEPOINT lx_install_rm")
#         raise
#     finally:
#         env.cr.execute("RELEASE SAVEPOINT lx_install_rm")


# def _get_threshold():
#     ICP = request.env["ir.config_parameter"].sudo()
#     val = ICP.get_param("luxtor.lx_free_amount_order", default="5000")
#     try:
#         return float(val)
#     except Exception:
#         return 5000.0


# def _is_service_line(line):
#     p = line.product_id
#     if not p or line.display_type:
#         return False
#     code = (p.default_code or "").strip().upper()
#     tcode = (p.product_tmpl_id.default_code or "").strip().upper()
#     return code in ("INSTALL_SERVICE", "PRIORITY_SERVICE") or tcode in ("INSTALL_SERVICE", "PRIORITY_SERVICE")


# def _merch_total_excl_services(order):
#     total = 0.0
#     for l in order.order_line:
#         if l.display_type:
#             continue
#         if getattr(l, "is_delivery", False):
#             continue
#         if hasattr(l, "is_tip") and l.is_tip:
#             continue
#         if hasattr(l, "is_downpayment") and l.is_downpayment:
#             continue
#         if _is_service_line(l):
#             continue
#         total += float(l.price_total or 0.0)
#     return total


# def _free_applies(order):
#     return bool(order) and (_merch_total_excl_services(order) >= _get_threshold())


# def _get_install_product():
#     return request.env["product.product"].sudo().search([("default_code", "=", INSTALL_CODE)], limit=1)


# def _find_install_lines(order, product):
#     return order.order_line.filtered(
#         lambda l: not l.display_type and (
#             l.product_id.id == product.id or
#             l.product_id.product_tmpl_id.id == product.product_tmpl_id.id
#         )
#     )


# def _mark_install_free(order):
#     """
#     Installation free via 100% discount (keep price_unit visible for UI).
#     Deduplicate extra install lines.
#     """
#     prod = _get_install_product()
#     if not prod:
#         return
#     lines = _find_install_lines(order, prod)
#     if lines:
#         keep = lines[:1]
#         if (keep.discount or 0.0) < 100.0:
#             keep.write({"discount": 100.0})
#         for l in (lines - keep):
#             order._cart_update(product_id=prod.id, line_id=l.id, set_qty=0)


# def _unmark_install_free(order):
#     """Remove forced 100% discount if present."""
#     prod = _get_install_product()
#     if not prod:
#         return
#     lines = _find_install_lines(order, prod)
#     for l in lines:
#         if (l.discount or 0.0) >= 100.0:
#             l.write({"discount": 0.0})


# def _mark_delivery_free(order):
#     """Delivery free = set price_unit=0 (no discount)."""
#     dlines = order.order_line.filtered(lambda l: getattr(l, "is_delivery", False) and not l.display_type)
#     for dl in dlines:
#         if dl.price_unit != 0.0 or dl.discount != 0.0:
#             dl.write({"price_unit": 0.0, "discount": 0.0})


# def _recompute_delivery_price(order):
#     """Restore real carrier price when not free."""
#     carrier = order.carrier_id
#     if not carrier:
#         return
#     try:
#         res = carrier.rate_shipment(order)
#         if isinstance(res, dict) and res.get("success"):
#             new_price = float(res.get("price", 0.0))
#             for dl in order.order_line.filtered(lambda l: getattr(l, "is_delivery", False) and not l.display_type):
#                 dl.write({"price_unit": new_price, "discount": 0.0})
#     except Exception:
#         return


# def _on_services_page():
#     """Free logic runs only on /shop/service(s) or when referred from it."""
#     path = (request.httprequest.path or "").split("?")[0]
#     if path in ("/shop/service", "/shop/services"):
#         return True
#     ref = request.httprequest.headers.get("Referer", "") or ""
#     return ("/shop/service" in ref) or ("/shop/services" in ref)


# def _reapply_free_logic_services_only(order):
#     """Apply/remove free rules only in the services funnel."""
#     if not _on_services_page():
#         return
#     if _free_applies(order):
#         _mark_install_free(order)
#         _mark_delivery_free(order)
#     else:
#         _unmark_install_free(order)
#         _recompute_delivery_price(order)


# def _qty_mrp_total(order):
#     """Sum quantities of lines that have a BoM — default qty for the service."""
#     qty_total = 0.0
#     for line in order.sudo().order_line:
#         p = line.product_id
#         if not p or line.display_type:
#             continue
#         if not (p.product_tmpl_id.bom_ids or getattr(p, "bom_count", 0)):
#             continue
#         qty_total += float(line.product_uom_qty or 0.0)
#     return qty_total


# def _currency_meta(order):
#     cur = order.currency_id
#     return (cur.symbol or " DH"), int(cur.decimal_places or 2)


# def _fmt_money_en(amount, decimals=2, currency_symbol=" DH"):
#     """Format like 3,250.50 DH regardless of user locale."""
#     return f"{amount:,.{decimals}f}{currency_symbol}"


# def _compute_unit_price(product, order):
#     """Use list price; keep price_unit visible (discount handles free)."""
#     product = product.sudo()
#     order = order.sudo()
#     return float(product.lst_price or 0.0)


# def _refresh_totals_dict(order, unit_price, currency_symbol, decimals, enabled=False):
#     # Ensure fresh totals
#     fields_to_invalidate = ["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"]
#     order.invalidate_recordset(fields_to_invalidate)
#     recompute = getattr(order, "_amount_all", None)
#     if callable(recompute):
#         recompute()
#         order.invalidate_recordset(fields_to_invalidate)

#     total_formatted = _fmt_money_en(order.amount_total, decimals, f" {currency_symbol}" if currency_symbol else "")

#     return {
#         "ok": True,
#         "enabled": enabled,
#         "qty": 0.0 if not enabled else _qty_mrp_total(order),
#         "unit_price": unit_price,
#         "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
#         "bom_qty": _qty_mrp_total(order),
#         "total": order.amount_total,
#         "total_formatted": total_formatted,
#         "amount_delivery": order.amount_delivery,
#         "amount_untaxed": order.amount_untaxed,
#         "amount_tax": order.amount_tax,
#         "currency": currency_symbol,
#         "decimals": decimals,
#     }


# # =========================
# # Controller (Installation)
# # =========================
# class InstallServiceController(http.Controller):
#     """
#     Installation endpoints (with free threshold logic for install & delivery).
#     """

#     # ---- Read-only endpoints ----
#     @http.route("/lx/install/price", type="json", auth="public", website=True, csrf=False)
#     def install_price(self, **kw):
#         order = _lx_sale_get_order()
#         prod = _get_install_product()
#         if not (order and prod):
#             return {"ok": False, "error": "Order or INSTALL_SERVICE not found"}

#         currency_symbol, decimals = _currency_meta(order)
#         unit_price = _compute_unit_price(prod, order)

#         return {
#             "ok": True,
#             "default_code": INSTALL_CODE,
#             "unit_price": unit_price,
#             "unit_formatted": f"+({unit_price:.2f} {currency_symbol})",
#             "currency": currency_symbol,
#             "decimals": decimals,
#         }

#     @http.route("/lx/install/mrp_qty", type="json", auth="public", website=True, csrf=False)
#     def install_mrp_qty(self, **kw):
#         order = _lx_sale_get_order()
#         if not order:
#             return {"ok": True, "qty_total": 0.0}
#         return {"ok": True, "qty_total": _qty_mrp_total(order)}

#     @http.route("/lx/install/has", type="json", auth="public", website=True, csrf=False)
#     def install_has(self, **kw):
#         order = _lx_sale_get_order()
#         prod = _get_install_product()
#         if not (order and prod):
#             return {"ok": True, "enabled": False}
#         enabled = bool(_find_install_lines(order.sudo(), prod))
#         return {"ok": True, "enabled": enabled}

#     # ---- Mutating endpoints ----
#     @http.route("/lx/install/apply", type="json", auth="public", website=True, csrf=False)
#     def install_apply(self, enabled=False, qty=0.0, **kw):
#         """
#         Toggle/add Installation service with the given qty (defaults to BoM qty).
#         Applies free rules only on the services page:
#           - Install: 100% discount (price_unit kept for UI)
#           - Delivery: price_unit=0
#         """
#         order = _lx_sale_get_order(force_create=True)
#         prod = _get_install_product()
#         if not (order and prod):
#             return {"ok": False}

#         order = order.sudo()
#         currency_symbol, decimals = _currency_meta(order)
#         unit_price = _compute_unit_price(prod, order)

#         try:
#             qty = float(qty or 0.0)
#         except Exception:
#             qty = 0.0

#         if enabled and qty <= 0.0:
#             qty = _qty_mrp_total(order)

#         lines = _find_install_lines(order, prod)

#         if (not enabled) or qty <= 0.0:
#             for l in lines:
#                 order._cart_update(product_id=prod.id, line_id=l.id, set_qty=0)
#             order._cart_update(product_id=prod.id, set_qty=0)
#         else:
#             if lines:
#                 keep = lines[:1]
#                 order._cart_update(product_id=prod.id, line_id=keep.id, set_qty=qty)
#                 for l in (lines - keep):
#                     order._cart_update(product_id=prod.id, line_id=l.id, set_qty=0)
#                 keep.invalidate_recordset(["discount"])
#             else:
#                 order._cart_update(product_id=prod.id, set_qty=qty)

#         # Re-apply FREE logic (only on services page)
#         _reapply_free_logic_services_only(order)

#         return _refresh_totals_dict(order, unit_price, currency_symbol, decimals, enabled=bool(enabled and qty > 0.0))

#     @http.route("/lx/install/remove", type="json", auth="public", website=True, csrf=False)
#     def install_remove(self, **kw):
#         """
#         Robust remove with a DB savepoint + hard cleanup,
#         then re-apply free logic for delivery and totals.
#         """
#         order = _lx_sale_get_order(force_create=True)
#         prod = _get_install_product()
#         if not (order and prod):
#             return {"ok": False}

#         order = order.sudo()
#         currency_symbol, decimals = _currency_meta(order)
#         unit_price = _compute_unit_price(prod, order)

#         with _savepoint(request.env):
#             lines = _find_install_lines(order, prod)
#             for l in lines:
#                 order._cart_update(product_id=l.product_id.id, line_id=l.id, set_qty=0)
#             # hard cleanup
#             _find_install_lines(order, prod).unlink()

#         # Re-apply FREE logic (delivery may change)
#         _reapply_free_logic_services_only(order)

#         return _refresh_totals_dict(order, unit_price, currency_symbol, decimals, enabled=False)
