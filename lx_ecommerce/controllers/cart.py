# -*- coding: utf-8 -*-
from odoo import fields, http
from odoo.http import request
from odoo.addons.website_sale.controllers.cart import Cart


class CartLxServices(Cart):

    @http.route()
    def cart(self, **post):
        """Override cart to add lx_services to suggested products"""
        response = super().cart(**post)

        # If response is not a rendered template, return as is
        if not hasattr(response, 'qcontext'):
            return response

        order_sudo = request.cart
        if order_sudo:
            # Add lx_services to the context
            lx_services = order_sudo._cart_lx_services()
            if 'lx_services' not in response.qcontext:
                response.qcontext['lx_services'] = lx_services

        return response

    @http.route()
    def quick_add(self, product_template_id, product_id, quantity=1.0, **kwargs):
        """Override quick_add to include lx_services in cart_lines rendering"""
        values = super().quick_add(product_template_id, product_id, quantity, **kwargs)

        order_sudo = request.cart
        if order_sudo:
            IrUiView = request.env['ir.ui.view']
            # Re-render cart_lines with lx_services
            values['website_sale.cart_lines'] = IrUiView._render_template(
                'website_sale.cart_lines', {
                    'website_sale_order': order_sudo,
                    'date': fields.Date.today(),
                    'suggested_products': order_sudo._cart_accessories(),
                    'lx_services': order_sudo._cart_lx_services(),
                }
            )

        return values

    @http.route()
    def update_cart_line_quantity(self, line_id, quantity, **kwargs):
        """Override to include lx_services when updating cart"""
        values = super().update_cart_line_quantity(line_id, quantity, **kwargs)

        order_sudo = request.cart
        if order_sudo:
            IrUiView = request.env['ir.ui.view']
            # Re-render cart_lines with lx_services
            values['website_sale.cart_lines'] = IrUiView._render_template(
                'website_sale.cart_lines', {
                    'website_sale_order': order_sudo,
                    'date': fields.Date.today(),
                    'suggested_products': order_sudo._cart_accessories(),
                    'lx_services': order_sudo._cart_lx_services(),
                }
            )

        return values
