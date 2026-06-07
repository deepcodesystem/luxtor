# -*- coding: utf-8 -*-
from odoo import fields, http
from odoo.http import request
from odoo.addons.website_sale.controllers.cart import Cart


class CartLxServices(Cart):

    def _apply_cart_free_install(self, order_sudo):
        """Réapplique la logique de gratuité installation et invalide les totaux."""
        if not order_sudo:
            return {}
        order_sudo._reapply_free_install_logic()
        order_sudo.invalidate_recordset([
            'amount_total', 'amount_delivery', 'amount_untaxed', 'amount_tax'
        ])
        return order_sudo._free_install_status()

    def _render_cart_lines(self, order_sudo):
        """Helper pour re-render le template cart_lines avec lx_services"""
        IrUiView = request.env['ir.ui.view']
        return IrUiView._render_template(
            'website_sale.cart_lines', {
                'website_sale_order': order_sudo,
                'date': fields.Date.today(),
                'suggested_products': order_sudo._cart_accessories(),
                'lx_services': order_sudo._cart_lx_services(),
                'lx_free_install_status': order_sudo._free_install_status(),
            }
        )

    @http.route()
    def cart(self, **post):
        """Override cart to add lx_services to suggested products"""
        response = super().cart(**post)

        if not hasattr(response, 'qcontext'):
            return response

        order_sudo = request.cart
        if order_sudo:
            self._apply_cart_free_install(order_sudo)

            lx_services = order_sudo._cart_lx_services()
            if 'lx_services' not in response.qcontext:
                response.qcontext['lx_services'] = lx_services
            response.qcontext['lx_free_install_status'] = order_sudo._free_install_status()

        return response

    @http.route()
    def quick_add(self, product_template_id, product_id, quantity=1.0, **kwargs):
        """Override quick_add to include lx_services in cart_lines rendering"""
        values = super().quick_add(product_template_id, product_id, quantity, **kwargs)

        order_sudo = request.cart
        if order_sudo:
            self._apply_cart_free_install(order_sudo)
            values['website_sale.cart_lines'] = self._render_cart_lines(order_sudo)
            values['lx_free_install_status'] = order_sudo._free_install_status()

        return values

    @http.route()
    def update_cart(self, line_id, quantity, product_id=None, **kwargs):
        """Override to include lx_services when updating cart"""
        values = super().update_cart(line_id, quantity, product_id=product_id, **kwargs)

        order_sudo = request.cart
        if order_sudo:
            self._apply_cart_free_install(order_sudo)
            values['website_sale.cart_lines'] = self._render_cart_lines(order_sudo)
            values['lx_free_install_status'] = order_sudo._free_install_status()

        return values
