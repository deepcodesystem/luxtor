# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request

# --- import/define helpers (reuse your existing ones if already defined) ---
try:
    # If these live in another file in the same module, import them:
    # from .delivery import _reapply_free_logic, _invalidate_totals, _merch_total_excl_services, _get_threshold, _currency_meta, _fmt_money_en
    pass
except Exception:
    pass

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
    total = 0.0
    if not order:
        return total
    for l in order.sudo().order_line:
        if l.display_type:
            continue
        if getattr(l, "is_delivery", False):
            continue
        if getattr(l, "is_tip", False):
            continue
        if getattr(l, "is_downpayment", False):
            continue
        if _is_service_line(l):
            continue
        total += float(l.price_total or 0.0)
    return total

def _currency_meta(order):
    cur = order.currency_id
    return (cur.symbol or " DH"), int(cur.decimal_places or 2)

def _fmt_money_en(amount, decimals=2, currency_symbol=" DH"):
    space = "" if not currency_symbol or currency_symbol.startswith(" ") else " "
    return f"{amount:,.{decimals}f}{space}{currency_symbol}".rstrip()

# If your real implementations already exist, replace these NOPs with the real calls
def _reapply_free_logic(order):
    """Re-apply your free logic (install=100% discount, delivery=0, else restore)."""
    # Use your existing implementation here.
    return

def _invalidate_totals(order):
    fields = ["amount_total", "amount_delivery", "amount_untaxed", "amount_tax"]
    order.invalidate_recordset(fields)
    recompute = getattr(order, "_amount_all", None)
    if callable(recompute):
        recompute()
        order.invalidate_recordset(fields)

# ---------------------- JSON endpoints ----------------------
class LxFreeApi(http.Controller):
    """Endpoints used by JS on /shop/checkout"""

    @http.route("/lx/free/flags", type="json", auth="public", website=True, csrf=False)
    def flags(self, **kw):
        """
        Read-only: return (applies?, merch_total, threshold)
        """
        order = request.website.sale_get_order()
        thr = _get_threshold()
        merch = _merch_total_excl_services(order) if order else 0.0
        return {
            "ok": True,
            "flags": {
                "lx_free_applies": bool(merch >= thr),
                "lx_merch_total": merch,
                "lx_free_threshold": thr,
            }
        }

    @http.route("/lx/free/apply", type="json", auth="public", website=True, csrf=False)
    def apply(self, **kw):
        """
        Mutating: apply backend free-logic + return fresh totals and flags.
        """
        order = request.website.sale_get_order(force_create=1)
        if not order:
            return {"ok": False}
        order = order.sudo()

        # apply logic and recompute
        _reapply_free_logic(order)
        _invalidate_totals(order)

        thr = _get_threshold()
        merch = _merch_total_excl_services(order)
        free = bool(merch >= thr)
        currency_symbol, decimals = _currency_meta(order)

        return {
            "ok": True,
            "flags": {
                "lx_free_applies": free,
                "lx_merch_total": merch,
                "lx_free_threshold": thr,
            },
            "totals": {
                "amount_total": order.amount_total,
                "amount_delivery": order.amount_delivery,
                "amount_untaxed": order.amount_untaxed,
                "amount_tax": order.amount_tax,
                "currency": currency_symbol,
                "decimals": decimals,
                "total_formatted": _fmt_money_en(order.amount_total, decimals, currency_symbol),
            }
        }
    

class LxFreeSessionFlag(http.Controller):
    @http.route("/lx/free/force", type="json", auth="public", website=True, csrf=False)
    def free_force(self, applied=False, **kw):
        request.session["lx_free_force"] = bool(applied)
        return {"ok": True, "forced": request.session.get("lx_free_force", False)}

    @http.route("/lx/free/clear", type="json", auth="public", website=True, csrf=False)
    def free_clear(self, **kw):
        request.session.pop("lx_free_force", None)
        return {"ok": True}
