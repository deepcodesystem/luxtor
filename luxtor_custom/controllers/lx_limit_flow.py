# -*- coding: utf-8 -*-
from odoo import http, _
from odoo.http import request

class LuxtorVerificationController(http.Controller):

    @http.route('/shop/order/validate_code', type='http', auth='public', website=True, csrf=True, methods=['POST'])
    def lx_validate_code(self, **post):
        """Compare the code linked to token (latest ticket) with user input.
        Allow 3 attempts max; keep input visible on error."""
        so = request.website.sale_get_order()
        # Ensure we have an order context
        if not so:
            request.session['lx_msg_err'] = _("No active order to validate.")
            return request.redirect('/shop/cart')

        # Extract form values
        input_code = (post.get('lx_code') or '').strip()
        token = (post.get('lx_token') or '').strip()

        if not token:
            request.session['lx_msg_err'] = _("Missing token. Please request a new authorization code.")
            return request.redirect('/shop/cart')

        # Try fetch the latest code for this token (from any ticket)
        latest_code = request.env['helpdesk.ticket'].lx_latest_code_for_token(token)

        # Attempts tracking (per token) in session
        attempts_map = request.session.get('lx_attempts_map') or {}
        att = int(attempts_map.get(token) or 0)

        # No code available yet
        if not latest_code:
            attempts_map[token] = att  # unchanged
            request.session['lx_attempts_map'] = attempts_map
            request.session['lx_last_code_value'] = input_code  # keep sticky
            request.session['lx_msg_err'] = _("No authorization code has been issued yet for your request. Please try again later or submit another ticket.")
            return request.redirect('/shop/cart')

        # Compare
        if input_code == latest_code:
            # Success
            so.sudo().write({
                'lx_verification_ok': True,
            })
            # Reset attempts for this token
            if token in attempts_map:
                attempts_map.pop(token)
            request.session['lx_attempts_map'] = attempts_map
            request.session['lx_last_code_value'] = ""  # clear sticky
            request.session['lx_msg_ok'] = _("Authorization successful. You can proceed to checkout.")
            return request.redirect('/shop/cart')

        # Wrong code
        att += 1
        attempts_map[token] = att
        request.session['lx_attempts_map'] = attempts_map
        request.session['lx_last_code_value'] = input_code  # sticky value

        remaining = max(0, 3 - att)
        if remaining > 0:
            request.session['lx_msg_err'] = _("Invalid code. You have %s attempt(s) remaining.") % remaining
            return request.redirect('/shop/cart')

        # Attempts exceeded
        # Clear this token's attempts so the user can request a fresh ticket
        attempts_map.pop(token, None)
        request.session['lx_attempts_map'] = attempts_map
        request.session['lx_msg_err'] = _("Too many failed attempts. Please submit a new ticket to receive another authorization code.")
        return request.redirect('/shop/cart')

# class HelpdeskWebsiteOverride(http.Controller):
#     """
#     If you already use Odoo's default route, you can add a tiny endpoint
#     to normalize the POST before delegating, or you can inherit the route.
#     For simplicity, here is a safe fallback endpoint if you decide to point your form to it.
#     """

#     @http.route(['/helpdesk/lx_submit'], type='http', auth='public', website=True, csrf=True, methods=['POST'])
#     def lx_submit_ticket(self, **post):
#         # Map known fields from website helpdesk form (name/description/team_id etc.)
#         vals = {}
#         vals['name'] = post.get('name') or post.get('subject') or 'New Ticket'
#         vals['description'] = post.get('description') or post.get('msg') or ''
#         team_id = request.env['helpdesk.team'].sudo().search([], limit=1).id
#         vals['team_id'] = int(post.get('team_id') or team_id)
#         # Our custom hidden token
#         if post.get('lx_token'):
#             vals['lx_verif_token'] = post.get('lx_token')

#         t = request.env['helpdesk.ticket'].sudo().create(vals)
#         return request.redirect('/helpdesk/thank-you')  # or default redirect