# -*- coding: utf-8 -*-
import re
from dateutil.relativedelta import relativedelta

from odoo import http, fields
from odoo.http import request


def _lx_get_tracking_order():
    """
    Find the most recent confirmed order for the current visitor.

    Priority:
      1. Logged-in user  → latest sale/done order for their commercial partner
      2. Guest           → the session cart if it is already confirmed
                           (edge case: guest who confirmed without logging in)
    """
    env = request.env

    if not env.user._is_public():
        partner = env.user.sudo().partner_id
        order = env['sale.order'].sudo().search(
            [
                ('partner_id', 'child_of', partner.commercial_partner_id.id),
                ('state', 'in', ('sale', 'done')),
            ],
            order='date_order desc',
            limit=1,
        )
        if order:
            return order

    # Guest fallback — session cart
    try:
        cart = request.website.sale_get_order()
    except AttributeError:
        cart = None
        order_id = request.session.get('sale_order_id')
        if order_id:
            cart = env['sale.order'].sudo().browse(int(order_id)).exists() or None

    if cart and cart.state in ('sale', 'done'):
        return cart

    return env['sale.order'].sudo().browse()


def _parse_eta_hours(s):
    """Parse ETA comme '24h - 48h' → (24, 48)."""
    if not s:
        return (None, None)
    nums = re.findall(r"\d+", s)
    if not nums:
        return (None, None)
    if len(nums) == 1:
        n = int(nums[0])
        return (n, n)
    return (int(nums[0]), int(nums[1]))


def _to_user_tz(dt):
    """Convertir UTC → fuseau utilisateur."""
    if not dt:
        return dt
    return fields.Datetime.context_timestamp(request.env.user, dt)


def _fmt_date_fr(dt):
    """Format français jj/mm/aaaa."""
    if not dt:
        return ""
    return _to_user_tz(dt).strftime("%d/%m/%Y")


class LuxtorSuiviCommande(http.Controller):

    @http.route(['/suivi-de-commande'], type='http', auth='public', website=True, sitemap=True)
    def suivi_de_commande(self, **kw):
        order = _lx_get_tracking_order()

        has_available_order = bool(order)
        contact_name  = order.partner_id.display_name if order else False
        order_name    = order.name if order else False

        ship_zip  = (order.partner_shipping_id.zip  or "").strip() if order else ""
        ship_city = (order.partner_shipping_id.city or "").strip() if order else ""

        # ── Delivery / picking info ──────────────────────────────────────────
        carrier_name  = False
        tracking      = False
        show_shipping = False
        picking       = False

        if order and order.picking_ids:
            outgoing = order.picking_ids.filtered(
                lambda p: getattr(p, 'picking_type_code', '') == 'outgoing'
                          and getattr(p, 'state', '') != 'cancel'
            )
            picking = outgoing[:1] if outgoing else False
            if picking:
                carrier_name  = getattr(getattr(picking, 'carrier_id', False), 'name', False) or False
                tracking      = getattr(picking, 'carrier_tracking_ref', False) or False
                pick_state    = getattr(picking, 'state', '')
                show_shipping = bool(carrier_name or tracking or pick_state in ('assigned', 'done'))

        # ── Base date for ETA calculation ────────────────────────────────────
        if picking and getattr(picking, 'scheduled_date', False):
            base_dt = picking.scheduled_date
        elif order and getattr(order, 'commitment_date', False):
            base_dt = order.commitment_date
        else:
            base_dt = fields.Datetime.now()

        # ── Shipping rate ETA ────────────────────────────────────────────────
        SR   = request.env['shipping.rate'].sudo()
        rate = False
        if ship_zip:
            rate = SR.search([('zip_code', '=', ship_zip)], limit=1)
        if not rate and ship_city:
            rate = SR.search([('name', '=ilike', ship_city)], limit=1)

        estimate = False
        eta_raw  = False
        if rate:
            eta_raw = rate.delivery_eta or False
            hmin, hmax = _parse_eta_hours(eta_raw)
            if hmin is not None:
                dt_min   = base_dt + relativedelta(hours=hmin)
                dt_max   = base_dt + relativedelta(hours=hmax)
                window   = f"{hmin}h–{hmax}h" if hmin != hmax else f"{hmin}h"
                estimate = f"{_fmt_date_fr(dt_min)} – {_fmt_date_fr(dt_max)} ({window})"

        # ── Fallback estimate ────────────────────────────────────────────────
        if not estimate and order:
            if getattr(order, 'delivery_date', False):
                estimate = _fmt_date_fr(order.delivery_date)
            elif getattr(order, 'commitment_date', False):
                estimate = _fmt_date_fr(order.commitment_date)

        ctx = {
            "has_available_order": has_available_order,
            "order_in_production": bool(order and order.state in ('sale', 'done')),
            "contact_name":  contact_name  or False,
            "order_name":    order_name    or False,
            "estimate":      estimate      or False,
            "eta_raw":       eta_raw       or False,
            "carrier_name":  carrier_name  or False,
            "tracking":      tracking      or False,
            "show_shipping": show_shipping,
        }
        return request.render("luxtor_custom.suivi_de_commande_page_qweb", ctx)
