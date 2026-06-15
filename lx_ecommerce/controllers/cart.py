# -*- coding: utf-8 -*-
from odoo import fields, http
from odoo.exceptions import UserError
from odoo.http import request
from odoo.tools.translate import _
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
        """Helper pour re-render le template cart_lines avec lx_services et lx_associated_products"""
        IrUiView = request.env['ir.ui.view']
        return IrUiView._render_template(
            'website_sale.cart_lines', {
                'website_sale_order': order_sudo,
                'date': fields.Date.today(),
                'suggested_products': order_sudo._cart_accessories(),
                'lx_services': order_sudo._cart_lx_services(),
                'lx_associated_products': order_sudo._cart_lx_associated_products(),
                'lx_free_install_status': order_sudo._free_install_status(),
            }
        )

    @http.route()
    def add_to_cart(
        self,
        product_template_id,
        product_id,
        quantity=1.0,
        uom_id=None,
        product_custom_attribute_values=None,
        no_variant_attribute_value_ids=None,
        linked_products=None,
        **kwargs
    ):
        order_sudo = request.cart or request.website._create_cart()
        quantity = int(quantity)

        product = request.env['product.product'].sudo().browse(product_id).exists()
        if not product or not product._is_add_to_cart_allowed():
            raise UserError(_(
                "The given product does not exist therefore it cannot be added to cart."
            ))

        added_qty_per_line = {}
        values = order_sudo.with_context(skip_cart_verification=True)._cart_add(
            product_id=product_id,
            quantity=quantity,
            uom_id=uom_id,
            product_custom_attribute_values=product_custom_attribute_values,
            no_variant_attribute_value_ids=no_variant_attribute_value_ids,
            **kwargs,
        )
        line_ids = {product_template_id: values['line_id']}
        added_qty_per_line[values['line_id']] = values['added_qty']
        is_combo = product.type == 'combo'
        updated_line = (
            values['line_id']
            and order_sudo.order_line.filtered(lambda line: line.id == values['line_id'])
        ) or order_sudo.env['sale.order.line']

        if linked_products and values['line_id']:
            for product_data in linked_products:
                product_sudo = request.env['product.product'].sudo().browse(
                    product_data['product_id']
                ).exists()
                if product_data['quantity'] and (
                    not product_sudo
                    or (
                        not product_sudo._is_add_to_cart_allowed()
                        and not product_data.get('combo_item_id')
                    )
                ):
                    raise UserError(_(
                        "The given product does not exist therefore it cannot be added to cart."
                    ))

                product_values = order_sudo.with_context(skip_cart_verification=True)._cart_add(
                    product_id=product_data['product_id'],
                    quantity=product_data['quantity'],
                    uom_id=product_data.get('uom_id'),
                    product_custom_attribute_values=product_data['product_custom_attribute_values'],
                    no_variant_attribute_value_ids=[
                        int(value_id) for value_id in product_data['no_variant_attribute_value_ids']
                    ],
                    linked_line_id=line_ids[product_data['parent_product_template_id']],
                    **self._get_additional_cart_update_values(product_data),
                    **kwargs,
                )
                if is_combo and not product_values.get('quantity'):
                    updated_line.unlink()
                    return {
                        'cart_quantity': order_sudo.cart_quantity,
                        'notification_info': {
                            'warning': product_values.get('warning', ''),
                        },
                        'quantity': 0,
                        'tracking_info': [],
                    }

                line_ids[product_data['product_template_id']] = product_values['line_id']
                added_qty_per_line[product_values['line_id']] = product_values['added_qty']

        warning = values.pop('warning', '')
        if is_combo and order_sudo._check_combo_quantities(updated_line):
            added_qty_per_line = {
                line.id: updated_line.product_uom_qty
                for line in (updated_line + updated_line.linked_line_ids)
            }
            warning = updated_line.shop_warning
            values['quantity'] = updated_line.product_uom_qty

        order_sudo._verify_cart_after_update()

        main_product_line = request.env['sale.order.line'].browse(values['line_id'])
        if main_product_line.product_type == 'combo':
            main_product_line._check_validity()

        positive_added_qty_per_line = {
            line_id: qty for line_id, qty in added_qty_per_line.items() if qty > 0
        }

        return {
            'cart_quantity': order_sudo.cart_quantity,
            'notification_info': {
                **self._get_cart_notification_information(
                    order_sudo, positive_added_qty_per_line
                ),
                'warning': warning,
            },
            'quantity': values.pop('quantity', 0),
            'tracking_info': self._get_tracking_information(order_sudo, line_ids.values()),
        }

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
            if 'lx_associated_products' not in response.qcontext:
                response.qcontext['lx_associated_products'] = order_sudo._cart_lx_associated_products()
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
