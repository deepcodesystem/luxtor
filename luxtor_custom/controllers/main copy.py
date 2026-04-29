# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request

class LxOrderVerification(http.Controller):

    # ---------- helpers ----------
    def _is_xhr(self):
        return request.httprequest.headers.get('X-Requested-With') == 'XMLHttpRequest'

    def _json_or_redirect(self, payload, redirect='/shop/cart'):
        if self._is_xhr():
            return request.make_json_response(payload)
        # fall back to classic flow
        if payload.get('ok'):
            request.session['lx_msg_ok'] = payload.get('message') or ''
        else:
            request.session['lx_msg_err'] = payload.get('message') or ''
        return request.redirect(redirect)

    # re-renderable snippet (frontend will fetch it)
    @http.route('/shop/order/verification_block', type='http', auth='public', website=True, csrf=False)
    def verification_block(self, **kw):
        order = request.website.sale_get_order(force_create=False)
        return request.render('luxtor_custom.lx_cart_verification_block', {
            'website_sale_order': order,
        })

    # ---------- actions ----------
    @http.route('/shop/order/send_code', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def send_code(self, **post):
        order = request.website.sale_get_order()
        if not (order and order.exists()):
            return self._json_or_redirect({'ok': False, 'message': _("No active order.")})
        if not getattr(order, 'lx_verification_required', False):
            return self._json_or_redirect({'ok': True, 'message': _("No verification required for this order.")})

        try:
            order.sudo().action_send_verification_code()
            return self._json_or_redirect({'ok': True, 'message': _("A verification code has been sent to your email.")})
        except Exception as e:
            return self._json_or_redirect({'ok': False, 'message': _("Unable to send code: %s") % e})

    @http.route('/shop/order/validate_code', type='http', auth='public', website=True, methods=['POST'], csrf=True)
    def validate_code(self, **post):
        order = request.website.sale_get_order()
        if not (order and order.exists()):
            return self._json_or_redirect({'ok': False, 'message': _("No active order.")})

        code = (post.get('lx_code') or '').strip()
        try:
            order.sudo().action_validate_verification_code(code)
            request.env.cr.commit()  # persist flag instantly
            return self._json_or_redirect({'ok': True, 'message': _("Code validated. You can now proceed.")})
        except Exception as e:
            return self._json_or_redirect({'ok': False, 'message': _("Invalid code: %s") % e})
