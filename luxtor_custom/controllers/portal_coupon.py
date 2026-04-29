# -*- coding: utf-8 -*-
import logging

from odoo import http
from odoo.addons.portal.controllers.portal import CustomerPortal
from odoo.http import request

from .website_sale_services import _lx_sale_get_order

_logger = logging.getLogger(__name__)


class CustomerPortalCoupon(CustomerPortal):

    def _prepare_portal_layout_values(self):
        values = super()._prepare_portal_layout_values()
        user = request.env.user
        values.update({
            "lx_welcome_coupon_code": False,
            "lx_welcome_coupon_value": False,
            "lx_welcome_coupon_applied": False,
        })
        if not user or user._is_public():
            return values
        try:
            user = user.sudo()
            order = _lx_sale_get_order(force_create=False)
            welcome_data = user._lx_get_welcome_coupon_display_data(
                order=order.sudo() if order else False,
                send_email=True,
            )
            values["lx_welcome_coupon_applied"] = bool(welcome_data.get("applied"))
            if welcome_data.get("show_coupon"):
                values.update({
                    "lx_welcome_coupon_code": welcome_data.get("code"),
                    "lx_welcome_coupon_value": welcome_data.get("pct"),
                })
        except Exception:
            _logger.exception("WELCOME-COUPON portal injection failed for user %s", user.id)
        return values

    @http.route("/my/welcome_debug", type="json", auth="user", website=True)
    def welcome_debug(self):
        vals = self._prepare_portal_layout_values()
        return {
            "lx_welcome_coupon_code": vals.get("lx_welcome_coupon_code"),
            "lx_welcome_coupon_value": vals.get("lx_welcome_coupon_value"),
            "lx_welcome_coupon_applied": vals.get("lx_welcome_coupon_applied"),
        }
