# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request


def _lx_sale_get_order(force_create=False):
    """V19-compatible cart order getter."""
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


class LxOrderVerification(http.Controller):

    def _is_xhr(self):
        return request.httprequest.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def _get_limit_status_payload(self, order=None):
        order = (order or _lx_sale_get_order()).sudo()
        if not (order and order.exists()):
            return {
                'ok': True,
                'has_order': False,
                'limit': 0.0,
                'total': 0.0,
                'verified': False,
                'should_show': False,
                'token': '',
            }

        limit = float(
            request.env['ir.config_parameter'].sudo().get_param(
                'luxtor.lx_order_limit_amount', '0'
            ) or 0.0
        )
        total = float(order.amount_total or 0.0)
        verified = bool(
            order._fields.get('lx_verification_ok') and order.lx_verification_ok
        )
        token = (order.lx_verif_token or '').strip()
        if not token and hasattr(order, 'lx_ensure_verification_token'):
            token = order.lx_ensure_verification_token()

        return {
            'ok': True,
            'has_order': True,
            'limit': limit,
            'total': total,
            'verified': verified,
            'should_show': bool(limit and total >= limit and not verified),
            'token': token,
        }

    def _json_or_redirect(self, payload, redirect='/shop/cart'):
        if self._is_xhr():
            return request.make_json_response(payload)
        if payload.get('ok'):
            request.session['lx_msg_ok'] = payload.get('message') or ''
        else:
            request.session['lx_msg_err'] = payload.get('message') or ''
        return request.redirect(redirect)

    @http.route('/shop/order_limit_status', type='json', auth='public', website=True, csrf=False)
    def order_limit_status(self, **kwargs):
        return self._get_limit_status_payload()

    @http.route('/shop/order/validate_code', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def validate_code(self, **post):
        order = _lx_sale_get_order()
        if not (order and order.exists()):
            return self._json_or_redirect({'ok': False, 'message': _("No active order to validate.")})

        order = order.sudo()
        input_code = (post.get('lx_code') or '').strip()
        request.session['lx_last_code_value'] = input_code

        token = (post.get('lx_token') or order.lx_verif_token or '').strip()
        if not token and hasattr(order, 'lx_ensure_verification_token'):
            token = order.lx_ensure_verification_token()

        if not token:
            return self._json_or_redirect({
                'ok': False,
                'message': _("Missing authorization request. Please click Continue to request a code first."),
            })

        latest_code = request.env['helpdesk.ticket'].sudo().lx_latest_code_for_token(token)
        attempts_map = request.session.get('lx_attempts_map') or {}
        attempts = int(attempts_map.get(token) or 0)

        if not latest_code:
            attempts_map[token] = attempts
            request.session['lx_attempts_map'] = attempts_map
            return self._json_or_redirect({
                'ok': False,
                'message': _("No authorization code has been issued yet for your request. Please try again later or submit another ticket."),
            })

        if input_code == latest_code:
            values = {'lx_verification_ok': True}
            if not order.lx_verif_token:
                values['lx_verif_token'] = token
            order.write(values)

            attempts_map.pop(token, None)
            request.session['lx_attempts_map'] = attempts_map
            request.session['lx_last_code_value'] = ""
            request.env.cr.commit()
            return self._json_or_redirect({
                'ok': True,
                'message': _("Authorization successful. You can proceed to checkout."),
            })

        attempts += 1
        attempts_map[token] = attempts
        request.session['lx_attempts_map'] = attempts_map

        remaining = max(0, 3 - attempts)
        if remaining > 0:
            return self._json_or_redirect({
                'ok': False,
                'message': _("Invalid code. You have %s attempt(s) remaining.") % remaining,
                'remaining_attempts': remaining,
            })

        attempts_map.pop(token, None)
        request.session['lx_attempts_map'] = attempts_map
        return self._json_or_redirect({
            'ok': False,
            'message': _("Too many failed attempts. Please submit a new ticket to receive another authorization code."),
            'remaining_attempts': 0,
        })
