# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request
from odoo.addons.website_sale.controllers.main import WebsiteSale


class WebsiteSaleLx(WebsiteSale):
    """
    /shop/carrier_rate_shipment with LX logic and ALWAYS an lx_debug payload.
    """
    @http.route(["/shop/carrier_rate_shipment"], type="json", auth="public", website=True)
    def carrier_rate_shipment(self, carrier_id, **kw):
        order = request.website.sale_get_order(force_create=1)
        if not order:
            return {"status": "error"}

        try:
            carrier_id = int(carrier_id)
        except Exception:
            return {"status": "error"}

        carrier = request.env["delivery.carrier"].sudo().browse(carrier_id)
        if not carrier.exists():
            return {"status": "error"}

        # Base debug so we always send something
        base_debug = {
            "zip": (order.partner_shipping_id.zip or "").strip(),
            "carrier_id": carrier.id,
            "carrier_name": carrier.name,
            "amount_total": float(order.amount_total or 0.0),
            "free_threshold": carrier._lx_get_free_threshold(),
        }

        # Priority: "Standard Delivery" is free
        if carrier._lx_is_standard_delivery_free():
            debug = dict(base_debug, **{
                "is_intracity": None,
                "free_applied": True,
                "free_reason": "carrier_name_is_standard_delivery",
                # updated formula text to match the new behavior
                "formula": "BoM per-unit sum + aggregated non-BoM total-weight bracket (1 unit)",
                "calc": {"raw_price": 0.0, "final_price": 0.0},
                "order_lines": [],  # we don't compute rows when we short-circuit to free
            })
            return {
                "status": "success",
                "carrier_id": carrier.id,
                "new_amount_delivery": 0.0,
                "is_free_delivery": True,
                "lx_debug": debug,
            }

        # ZIP → shipping.rate
        shipping_rate = False
        if base_debug["zip"]:
            shipping_rate = request.env["shipping.rate"].sudo().search(
                [("zip_code", "=", base_debug["zip"])], limit=1
            )

        if shipping_rate:
            try:
                price, debug_inner = carrier._lx_compute_rate_for_order(order, shipping_rate)
                debug = dict(base_debug, **debug_inner)  # keep all details
                return {
                    "status": "success",
                    "carrier_id": carrier.id,
                    "new_amount_delivery": price,
                    "is_free_delivery": (price == 0.0),
                    "lx_debug": debug,
                }
            except Exception as e:
                native = super(WebsiteSaleLx, self).carrier_rate_shipment(carrier_id, **kw)
                debug = dict(base_debug, **{
                    "is_intracity": bool(getattr(shipping_rate, "is_intracity", False)),
                    "free_applied": None,
                    "free_reason": "compute_exception",
                    "error": str(e),
                    "formula": "native_fallback",
                    "calc": {"raw_price": None, "final_price": native.get("new_amount_delivery")},
                    "order_lines": [],
                })
                native.setdefault("lx_debug", debug)
                return native

        # No ZIP or no shipping.rate → native fallback, but keep lx_debug
        native = super(WebsiteSaleLx, self).carrier_rate_shipment(carrier_id, **kw)
        reason = "missing_zip" if not base_debug["zip"] else "no_shipping_rate_for_zip"
        debug = dict(base_debug, **{
            "is_intracity": None,
            "free_applied": None,
            "free_reason": reason,
            "formula": "native_fallback",
            "calc": {"raw_price": None, "final_price": native.get("new_amount_delivery")},
            "order_lines": [],
        })
        native.setdefault("lx_debug", debug)
        return native
