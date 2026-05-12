# -*- coding: utf-8 -*-
import logging
import traceback

from odoo import http, _
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale

# Helpers partagés (env-based) importés depuis le wizard
from odoo.addons.lx_delivery.wizards.lx_wizard_shipping import (
    _get_free_threshold,
    _merch_total_excl_services,
    _compute_express_price,
)

_logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers request-based (controller uniquement)
# ─────────────────────────────────────────────────────────────────────────────

def _lx_sale_get_order(force_create=False):
    """Récupère la commande courante (compatible V19)."""
    try:
        return request.website.sale_get_order(force_create=force_create)
    except AttributeError:
        pass
    Order = request.env["sale.order"].sudo()
    order_id = request.session.get("sale_order_id")
    if order_id:
        order = Order.browse(int(order_id)).exists()
        if order:
            return order
    return Order.browse()


def _apply_free_logic_request(order, raw_price):
    """
    Logique free shipping avec request.session.lx_free_force.

    Retourne (final_price, free_applied, free_reason, threshold, merch_total, forced).
    """
    forced = bool(request.session.get("lx_free_force", False))
    threshold = _get_free_threshold(request.env)
    merch_total = _merch_total_excl_services(request.env, order)

    if forced:
        return 0.0, True, "session_forced", threshold, merch_total, True
    if threshold and merch_total >= threshold:
        return 0.0, True, "order_amount_over_threshold", threshold, merch_total, False
    return float(raw_price or 0.0), False, None, threshold, merch_total, False


def _lx_free_applies_request(order):
    """True si la livraison est gratuite pour la commande (contexte request)."""
    threshold = _get_free_threshold(request.env)
    merch_total = _merch_total_excl_services(request.env, order)
    return bool(order and threshold and merch_total >= threshold)


def _lookup_shipping_rate(zip_code):
    """Recherche shipping.rate par zip_code."""
    if not zip_code:
        return False
    return request.env["shipping.rate"].sudo().search([("zip_code", "=", zip_code)], limit=1)


def _apply_delivery_line(order, carrier, price):
    """Applique carrier + prix livraison sur la commande (robuste V18/V19)."""
    order_sudo = order.sudo()
    try:
        order_sudo.write({"carrier_id": carrier.id})
    except Exception:
        pass

    for meth in ("set_delivery_line", "_set_delivery_line", "_create_delivery_line"):
        fn = getattr(order_sudo, meth, None)
        if not fn:
            continue
        try:
            fn(carrier, price)
            return True
        except TypeError:
            try:
                fn(carrier)
                dl = order_sudo.order_line.filtered(lambda l: getattr(l, "is_delivery", False))[:1]
                if dl:
                    dl.write({"price_unit": float(price or 0.0)})
                return True
            except Exception:
                continue
        except Exception:
            continue

    dl = order_sudo.order_line.filtered(lambda l: getattr(l, "is_delivery", False))[:1]
    if dl:
        dl.write({"price_unit": float(price or 0.0)})
        return True
    return False


def _currency_payload(order):
    """Dict devise pour le frontend."""
    cur = order.currency_id
    return {
        "name": cur.name,
        "symbol": cur.symbol or "",
        "position": cur.position or "after",
        "decimal_places": int(cur.decimal_places or 2),
    }


def _err_name(e):
    try:
        return e.__class__.__name__
    except Exception:
        return "Exception"


def _short_trace(limit_lines=35):
    try:
        lines = (traceback.format_exc() or "").splitlines()
        return "\n".join(lines[-limit_lines:] if len(lines) > limit_lines else lines)
    except Exception:
        return ""


def _save_last_debug(payload):
    try:
        request.session["lx_last_debug"] = payload
    except Exception:
        pass


def _inject_free_flags(ctx, order):
    """Injecte lx_free_threshold / lx_merch_total / lx_free_applies dans le qcontext."""
    if ctx is None:
        return
    threshold = _get_free_threshold(request.env)
    merch_total = _merch_total_excl_services(request.env, order) if order else 0.0
    ctx["lx_free_threshold"] = threshold
    ctx["lx_merch_total"] = merch_total
    ctx["lx_free_applies"] = bool(order and threshold and merch_total >= threshold)


# ─────────────────────────────────────────────────────────────────────────────
# Controller
# ─────────────────────────────────────────────────────────────────────────────

class WebsiteSaleLx(WebsiteSale):

    # ── Debug ─────────────────────────────────────────────────────────────────

    @http.route(["/lx/shipping/last_debug"], type="json", auth="public", website=True, csrf=False)
    def lx_last_debug(self, **kw):
        try:
            return {"status": "success", "lx_debug": request.session.get("lx_last_debug") or {}}
        except Exception:
            return {"status": "success", "lx_debug": {}}

    # ── Preview prices ────────────────────────────────────────────────────────

    @http.route(["/lx/shipping/preview_prices"], type="json", auth="public", website=True, csrf=False)
    def lx_preview_prices(self, **kw):
        """
        Pré-calcule les prix pour TOUS les transporteurs actifs de la commande courante.
        Utilisé par lx_delivery_preview.js pour afficher les prix avant sélection.
        """
        order = _lx_sale_get_order(force_create=True)
        if not order:
            payload = {"status": "no_order", "prices": {}}
            _save_last_debug({"route": "preview_prices", "payload": payload})
            return payload

        zip_code = (order.partner_shipping_id.zip or "").strip()
        shipping_rate = _lookup_shipping_rate(zip_code)
        is_intracity = bool(getattr(shipping_rate, "is_intracity", False)) if shipping_rate else None
        threshold = _get_free_threshold(request.env)
        merch_total = _merch_total_excl_services(request.env, order)
        free_applies = bool(threshold and merch_total >= threshold)

        carriers = request.env["delivery.carrier"].sudo().search([("website_published", "=", True)])
        prices = {}
        debug_by_carrier = {}

        for c in carriers:
            name_norm = (c.name or "").strip().lower()
            try:
                if name_norm == "standard delivery":
                    if not shipping_rate:
                        prices[c.id] = 0.0
                        debug_by_carrier[c.id] = {"ok": False, "reason": "no_shipping_rate_for_zip"}
                        continue
                    raw, _ = _compute_standard_city_raw_price_for_request(order, shipping_rate)
                    final, free_applied, free_reason, thr, mt, forced = _apply_free_logic_request(order, raw)
                    prices[c.id] = float(final or 0.0)
                    debug_by_carrier[c.id] = {
                        "ok": True, "route": "standard_city_strict_preview",
                        "zip": zip_code, "is_intracity": is_intracity,
                        "calc": {"raw_price": float(raw), "final_price": float(final)},
                        "free_logic": {
                            "applied": bool(free_applied), "reason": free_reason,
                            "threshold": float(thr or 0.0),
                            "merch_total_excl_services": float(mt or 0.0),
                            "forced_session": bool(forced),
                        },
                    }

                elif name_norm == "express delivery":
                    if not shipping_rate:
                        prices[c.id] = 0.0
                        debug_by_carrier[c.id] = {"ok": False, "reason": "no_shipping_rate_for_zip"}
                        continue
                    raw = _compute_express_price(request.env, order, bool(shipping_rate.is_intracity))
                    final, free_applied, free_reason, thr, mt, forced = _apply_free_logic_request(order, raw)
                    prices[c.id] = float(final or 0.0)
                    debug_by_carrier[c.id] = {
                        "ok": True, "route": "express_weight_strict_preview",
                        "zip": zip_code, "is_intracity": bool(shipping_rate.is_intracity),
                        "calc": {"raw_price": float(raw), "final_price": float(final)},
                        "free_logic": {
                            "applied": bool(free_applied), "reason": free_reason,
                            "threshold": float(thr or 0.0),
                            "merch_total_excl_services": float(mt or 0.0),
                            "forced_session": bool(forced),
                        },
                    }

                else:
                    prices[c.id] = 0.0
                    debug_by_carrier[c.id] = {"ok": False, "route": "unsupported_carrier_preview"}

            except Exception as e:
                prices[c.id] = 0.0
                debug_by_carrier[c.id] = {
                    "ok": False, "route": "preview_exception",
                    "error": str(e), "error_name": _err_name(e),
                    "error_trace": _short_trace(),
                }

        payload = {
            "status": "success",
            "zip": zip_code,
            "is_intracity": is_intracity,
            "currency": _currency_payload(order),
            "free_flags": {
                "lx_free_applies": free_applies,
                "lx_merch_total": float(merch_total or 0.0),
                "lx_free_threshold": float(threshold or 0.0),
            },
            "prices": prices,
            "lx_debug": {"by_carrier": debug_by_carrier},
        }
        _save_last_debug({"route": "preview_prices", "payload": payload})
        return payload

    # ── carrier_rate_shipment ─────────────────────────────────────────────────

    @http.route(["/shop/carrier_rate_shipment"], type="json", auth="public", website=True, csrf=False)
    def carrier_rate_shipment(self, carrier_id=None, **kw):
        """
        Override /shop/carrier_rate_shipment.

        Pour Standard et Express Delivery : calcule dynamiquement via shipping.rate + brackets.
        Retourne {status, carrier_id, new_amount_delivery, is_free_delivery, lx_debug}.
        """
        order = _lx_sale_get_order(force_create=True)
        if not order:
            debug = {"route": "early_exit", "reason": "no_order"}
            _save_last_debug(debug)
            return {"status": "error", "error": "no_order", "lx_debug": debug}

        if carrier_id is None:
            carrier_id = kw.get("carrier_id")
        try:
            carrier_id = int(carrier_id)
        except Exception as e:
            debug = {"route": "early_exit", "reason": "bad_carrier_id", "error": str(e)}
            _save_last_debug(debug)
            return {"status": "error", "error": "bad_carrier_id", "lx_debug": debug}

        carrier = request.env["delivery.carrier"].sudo().browse(carrier_id)
        if not carrier.exists():
            debug = {"route": "early_exit", "reason": "carrier_not_found", "carrier_id": carrier_id}
            _save_last_debug(debug)
            return {"status": "error", "error": "carrier_not_found", "lx_debug": debug}

        zip_code = (order.partner_shipping_id.zip or "").strip()
        shipping_rate = _lookup_shipping_rate(zip_code)
        is_intracity = bool(getattr(shipping_rate, "is_intracity", False)) if shipping_rate else None

        base_debug = {
            "zip": zip_code, "carrier_id": carrier.id, "carrier_name": carrier.name,
            "currency": _currency_payload(order),
            "order": {
                "id": order.id,
                "amount_total": float(order.amount_total or 0.0),
            },
            "is_intracity": is_intracity,
        }

        carrier_name_norm = (carrier.name or "").strip().lower()

        # Standard Delivery
        if carrier_name_norm == "standard delivery":
            if not shipping_rate:
                debug = dict(base_debug, route="standard_city_strict",
                             reason="missing_zip_or_no_shipping_rate",
                             calc={"raw_price": None, "final_price": None})
                _save_last_debug(debug)
                return {
                    "status": "error", "error": "no_shipping_rate_for_zip",
                    "carrier_id": carrier.id, "new_amount_delivery": 0.0, "lx_debug": debug,
                }
            raw, std_debug = _compute_standard_city_raw_price_for_request(order, shipping_rate)
            final, free_applied, free_reason, thr, mt, forced = _apply_free_logic_request(order, raw)
            applied = _apply_delivery_line(order, carrier, float(final or 0.0))
            debug = dict(base_debug, route="standard_city_strict",
                         shipping_rate_id=shipping_rate.id,
                         apply_delivery_line=bool(applied),
                         calc={"raw_price": float(raw), "final_price": float(final), "details": std_debug},
                         free_logic={
                             "applied": bool(free_applied), "reason": free_reason,
                             "threshold": float(thr or 0.0),
                             "merch_total_excl_services": float(mt or 0.0),
                             "forced_session": bool(forced),
                         })
            _save_last_debug(debug)
            return {
                "status": "success", "carrier_id": carrier.id,
                "new_amount_delivery": float(final or 0.0),
                "is_free_delivery": bool(free_applied), "lx_debug": debug,
            }

        # Express Delivery
        if carrier_name_norm == "express delivery":
            if not shipping_rate:
                debug = dict(base_debug, route="express_weight_strict",
                             reason="missing_zip_or_no_shipping_rate",
                             calc={"raw_price": None, "final_price": None})
                _save_last_debug(debug)
                return {
                    "status": "error", "error": "no_shipping_rate_for_zip",
                    "carrier_id": carrier.id, "new_amount_delivery": 0.0, "lx_debug": debug,
                }
            try:
                raw = _compute_express_price(request.env, order, bool(shipping_rate.is_intracity))
                final, free_applied, free_reason, thr, mt, forced = _apply_free_logic_request(order, raw)
                applied = _apply_delivery_line(order, carrier, float(final or 0.0))
                debug = dict(base_debug, route="express_weight_strict",
                             shipping_rate_id=shipping_rate.id,
                             bracket_kind="intra" if shipping_rate.is_intracity else "inter",
                             apply_delivery_line=bool(applied),
                             calc={"raw_price": float(raw), "final_price": float(final)},
                             free_logic={
                                 "applied": bool(free_applied), "reason": free_reason,
                                 "threshold": float(thr or 0.0),
                                 "merch_total_excl_services": float(mt or 0.0),
                                 "forced_session": bool(forced),
                             })
                _save_last_debug(debug)
                return {
                    "status": "success", "carrier_id": carrier.id,
                    "new_amount_delivery": float(final or 0.0),
                    "is_free_delivery": bool(free_applied), "lx_debug": debug,
                }
            except Exception as e:
                _logger.exception("Express compute error")
                debug = dict(base_debug, route="express_weight_strict",
                             reason="compute_exception",
                             error=str(e), error_name=_err_name(e),
                             error_trace=_short_trace(),
                             calc={"raw_price": None, "final_price": None})
                _save_last_debug(debug)
                return {
                    "status": "error", "error": "compute_exception",
                    "carrier_id": carrier.id, "new_amount_delivery": 0.0, "lx_debug": debug,
                }

        # Transporteur non géré dynamiquement
        debug = dict(base_debug, route="unsupported_carrier",
                     reason="carrier_name_not_supported",
                     calc={"raw_price": None, "final_price": None})
        _save_last_debug(debug)
        return {
            "status": "error", "error": "unsupported_carrier",
            "carrier_id": carrier.id, "new_amount_delivery": 0.0, "lx_debug": debug,
        }

    # ── Checkout / Payment overrides ──────────────────────────────────────────

    def _lx_sync_order_shipping_before_render(self):
        """Synchronise le prix du carrier sélectionné avant rendu checkout/payment."""
        order = _lx_sale_get_order()
        if not order:
            return
        order = order.sudo()
        if hasattr(order, "_lx_sync_dimension_website_prices"):
            order._lx_sync_dimension_website_prices()
        if _lx_free_applies_request(order):
            _lx_force_standard_carrier_if_free(order)
        elif order.carrier_id:
            order._lx_sync_selected_carrier_delivery_line()

    @http.route(["/shop/checkout"], type="http", auth="public", website=True, sitemap=False)
    def checkout(self, **post):
        self._lx_sync_order_shipping_before_render()
        sup = super(WebsiteSaleLx, self)
        response = sup.checkout(**post) if hasattr(sup, "checkout") else sup.shop_checkout(**post)
        if hasattr(response, "qcontext"):
            order = response.qcontext.get("website_sale_order") or _lx_sale_get_order()
            _inject_free_flags(response.qcontext, order.sudo() if order else order)
        return response

    @http.route(["/shop/payment"], type="http", auth="public", website=True, sitemap=False)
    def payment(self, **post):
        self._lx_sync_order_shipping_before_render()
        sup = super(WebsiteSaleLx, self)
        response = sup.payment(**post) if hasattr(sup, "payment") else sup.shop_payment(**post)
        if hasattr(response, "qcontext"):
            order_ctx = response.qcontext.get("website_sale_order")
            if order_ctx and hasattr(order_ctx, "_lx_payment_summary_values"):
                response.qcontext["lx_payment_summary"] = order_ctx._lx_payment_summary_values()
            response.qcontext["lx_payment_choice"] = (
                (order_ctx.lx_payment_terms if order_ctx else None) or "upfront"
            )
            _inject_free_flags(response.qcontext, order_ctx or _lx_sale_get_order())
        return response

    @http.route(["/shop/payment/update_terms"], type="json", auth="public", website=True, csrf=False)
    def lx_payment_update_terms(self, lx_payment_terms=None, **post):
        """Met à jour les termes de paiement et retourne le summary."""
        order = _lx_sale_get_order(force_create=False)
        if not order:
            return {"ok": False, "error": "no_order"}
        order = order.sudo()
        if hasattr(order, "_lx_apply_website_payment_terms"):
            order._lx_apply_website_payment_terms(lx_payment_terms)
        elif hasattr(order, "lx_payment_terms"):
            order.write({"lx_payment_terms": lx_payment_terms})
        summary = order._lx_payment_summary_values() if hasattr(order, "_lx_payment_summary_values") else {}
        return {"ok": True, "summary": summary, "currency": _currency_payload(order)}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers standard price (request.env based, gardé local au controller)
# ─────────────────────────────────────────────────────────────────────────────

def _compute_standard_city_raw_price_for_request(order, shipping_rate):
    """
    Calcule le prix Standard brut dans le contexte request.
    Retourne (raw_price, debug_dict).
    """
    import math as _math

    def _is_service_line_local(line):
        p = line.product_id
        if not p or line.display_type:
            return False
        code = (p.default_code or "").strip().upper()
        tcode = (p.product_tmpl_id.default_code or "").strip().upper()
        return code in ("INSTALL_SERVICE", "PRIORITY_SERVICE") or tcode in ("INSTALL_SERVICE", "PRIORITY_SERVICE")

    def _is_accessory_local(product):
        if not product:
            return False
        try:
            c = product.categ_id
            if c and ("access" in (c.complete_name or "").lower() or "access" in (c.name or "").lower()):
                return True
        except Exception:
            pass
        return False

    def _find_bom_sudo_local(product):
        try:
            p = product.sudo()
            Bom = request.env["mrp.bom"].sudo()
            try:
                bom = Bom._bom_find(product=p)
                if bom:
                    return bom
            except Exception:
                pass
            tmpl = p.product_tmpl_id.sudo()
            if tmpl:
                try:
                    bom = Bom._bom_find(product_tmpl=tmpl)
                    if bom:
                        return bom
                except Exception:
                    pass
                if getattr(tmpl, "bom_ids", False) and tmpl.bom_ids:
                    return tmpl.bom_ids[:1]
        except Exception:
            return False
        return False

    base = float(getattr(shipping_rate, "price", 0.0) or 0.0)
    manufactured_parcels = 0
    has_accessory_group = False
    has_extra_group = False

    for l in order.sudo().order_line:
        if l.display_type:
            continue
        if getattr(l, "is_delivery", False) or getattr(l, "is_tip", False) or getattr(l, "is_downpayment", False):
            continue
        if getattr(l, "is_shipping_line", False) or getattr(l, "is_free_shipping_line", False):
            continue
        if _is_service_line_local(l):
            continue
        p = l.product_id
        qty_f = float(l.product_uom_qty or 0.0)
        if not p or qty_f <= 0 or p.type not in ("product", "consu"):
            continue
        bom = _find_bom_sudo_local(p)
        if bom:
            manufactured_parcels += int(_math.ceil(qty_f))
        elif _is_accessory_local(p):
            has_accessory_group = True
        else:
            has_extra_group = True

    parcels_total = (
        manufactured_parcels
        + (1 if has_accessory_group else 0)
        + (1 if has_extra_group else 0)
    )
    if parcels_total <= 0:
        parcels_total = 1
    raw = float(base * parcels_total)
    return raw, {
        "base_zip_price": base,
        "manufactured_bom_parcels": manufactured_parcels,
        "accessories_group_parcel": 1 if has_accessory_group else 0,
        "extra_tangible_group_parcel": 1 if has_extra_group else 0,
        "parcels_total": parcels_total,
    }


def _lx_find_standard_carrier():
    Carrier = request.env["delivery.carrier"].sudo()
    return (Carrier.search([("name", "=ilike", "Standard Delivery")], limit=1)
            or Carrier.search([("name", "ilike", "standard")], limit=1))


def _lx_force_standard_carrier_if_free(order):
    """Force le carrier Standard à 0 si la livraison est offerte."""
    carrier = _lx_find_standard_carrier()
    if not carrier:
        return False
    return bool(_apply_delivery_line(order, carrier, 0.0))

