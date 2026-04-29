# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SaleOrderPriorityWizard(models.TransientModel):
    _name = 'sale.order.priority.wizard'
    _description = 'Priority Selection Wizard'

    order_id = fields.Many2one('sale.order', string='Order', required=True, readonly=True)
    priority = fields.Selection(
        [('standard', 'Standard'), ('express', 'Express')],
        string='Priority',
        required=True,
        default='standard',
    )
    quantity = fields.Integer(string='Quantity', default=0)
    price = fields.Float(string='Price')

    # -------------------
    # Helpers
    # -------------------
    def _get_priority_product(self, option):
        """Return product.product variant via XML ID."""
        xmlid = (
            'luxtor_custom.product_priority_express_tmpl'
            if option == 'express'
            else 'luxtor_custom.product_priority_standard_tmpl'
        )
        tmpl = self.env.ref(xmlid)
        return tmpl.product_variant_id

    
    # -------------------
    # Defaults / onchange
    # -------------------
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id:
            order = self.env['sale.order'].browse(active_id)
            res['order_id'] = order.id
            res.setdefault('priority', order.priority or 'standard')

            qty = order._get_mrp_blinds_quantity()
            is_express = res['priority'] == 'express'
            prod = self._get_priority_product('express' if is_express else 'standard')

            res['quantity'] = qty if is_express else qty
            res['price'] = prod.list_price if is_express else 0.0
        return res

    @api.onchange('priority')
    def _onchange_priority(self):
        for wizard in self:
            order = wizard.order_id
            if not order:
                continue
            qty = order._get_mrp_blinds_quantity()
            is_express = wizard.priority == 'express'
            prod = wizard._get_priority_product('express' if is_express else 'standard')

            wizard.quantity = qty if is_express else qty
            wizard.price = prod.list_price if is_express else 0.0

    # -------------------
    # Constraints
    # -------------------
    @api.constrains('quantity')
    def _check_quantity(self):
        for wizard in self:
            if wizard.priority == 'express':
                max_qty = wizard.order_id._get_mrp_blinds_quantity()
                if wizard.quantity > max_qty or wizard.quantity <= 0:
                    raise ValidationError(_(
                        'You cannot specify a priority quantity greater '
                        'than the number of roller blinds in the order.\n'
                        'Maximum allowed: %d' % max_qty
                    ))

    # -------------------
    # Apply
    # -------------------
    def action_confirm(self):
        for wizard in self:
            order = wizard.order_id
            if not order:
                continue

            # Remove old priority lines
            order.order_line.filtered(lambda l: getattr(l, 'is_priority_line', False)).unlink()

            # Save summary fields on order
            order.write({
                'priority': wizard.priority,
                'priority_quantity': wizard.quantity,
                'priority_price': wizard.price,
            })

            # If express, validate qty
            if wizard.priority == 'express':
                max_qty = order._get_mrp_blinds_quantity()
                if wizard.quantity <= 0 or wizard.quantity > max_qty:
                    raise UserError(_('Please enter a quantity between 1 and %d for express delivery.') % max_qty)

            # Determine sequence (after goods, before installation)
            goods_lines = order.order_line.filtered(
                lambda l: l.product_template_id
                          and l.product_template_id.type in ['consu', 'combo']
                          and not getattr(l, 'is_priority_line', False)
                          and not getattr(l, 'is_installation_line', False)
            )
            new_sequence = max(goods_lines.mapped('sequence'), default=0) + 1

            # Product + taxes
            prod = wizard._get_priority_product(wizard.priority)

            # Create SOL (fixes product_uom=False issue)
            self.env['sale.order.line'].create({
                'order_id': order.id,
                'product_id': prod.id,
                'name': prod.get_product_multiline_description_sale(),
                'product_uom_qty': wizard.quantity,
                'product_uom': prod.uom_id.id,   # REQUIRED
                'price_unit': wizard.price,      # 0.0 if standard
                'sequence': new_sequence,
                'is_priority_line': True,
                'lx_width_m': False,
                'lx_height_m': False,
                'size': False,
            })

            order._compute_delivery_date()
            if hasattr(order, '_generate_sequence_numbers_for_lines'):
                order._generate_sequence_numbers_for_lines()

        return {'type': 'ir.actions.act_window_close'}

# class SaleOrderPriorityWizard(models.TransientModel):
#     _name = 'sale.order.priority.wizard'
#     _description = 'Priority Selection Wizard'

#     order_id = fields.Many2one('sale.order', string='Order',
#                                 required=True, readonly=True)
#     priority = fields.Selection([
#         ('standard', 'Standard'),
#         ('express', 'Express'),
#     ], string='Priority', required=True, default='standard')
#     quantity = fields.Integer(string='Quantity', default=0)
#     price = fields.Float(string='Price')

#     @api.model
#     def default_get(self, fields_list):
#         res = super().default_get(fields_list)
#         active_id = self.env.context.get('active_id')
#         if active_id:
#             order = self.env['sale.order'].browse(active_id)
#             res['order_id'] = order.id
#             res.setdefault('priority', order.priority or 'standard')
#             res['quantity'] = order._get_mrp_blinds_quantity()

#             product = self.env['product.product'].search(
#                 [('default_code', '=', 'PRIORITY_SERVICE')], limit=1)
#             price_from_product = product.list_price if product else 0.0
#             res['price'] = price_from_product
#         return res

#     @api.onchange('priority')
#     def _onchange_priority(self):
#         for wizard in self:
#             product = self.env['product.product'].search(
#                 [('default_code', '=', 'PRIORITY_SERVICE')], limit=1)
#             price_from_product = product.list_price if product else 0.0

#             if wizard.priority == 'standard':
#                 wizard.quantity = 0
#                 wizard.price = 0.0
#             else:
#                 order = wizard.order_id
#                 if order:
#                     wizard.quantity = order._get_mrp_blinds_quantity()
#                     wizard.price = price_from_product

#     @api.constrains('quantity')
#     def _check_quantity(self):
#         for wizard in self:
#             if wizard.priority == 'express':
#                 max_qty = wizard.order_id._get_mrp_blinds_quantity()
#                 if wizard.quantity > max_qty or wizard.quantity <= 0:
#                     raise ValidationError(_(
#                         'You cannot specify a priority quantity greater '
#                         'than the number of roller blinds in the order.\n'
#                         'Maximum allowed: %d' % max_qty
#                     ))

#     def action_confirm(self):
#         for wizard in self:
#             order = wizard.order_id
#             if not order:
#                 continue

#             order.order_line.filtered(lambda l: l.is_priority_line).unlink()

#             if wizard.priority == 'standard':
#                 order.write({
#                     'priority': 'standard',
#                     'priority_quantity': 0,
#                     'priority_price': 0.0,
#                 })
#                 order._compute_delivery_date()
#                 order.invalidate_recordset()
#             else:
#                 max_qty = order._get_mrp_blinds_quantity()
#                 if wizard.quantity <= 0 or wizard.quantity > max_qty:
#                     raise UserError(_('Please enter a quantity between 1 and %d for express delivery.') % max_qty)

#                 order.write({
#                     'priority': 'express',
#                     'priority_quantity': wizard.quantity,
#                     'priority_price': wizard.price,
#                 })

#                 goods_lines = order.order_line.filtered(
#                     lambda l: l.product_template_id and
#                               l.product_template_id.type in ['consu', 'combo'] and
#                               not l.is_priority_line and not l.is_installation_line)

#                 new_sequence = max(goods_lines.mapped('sequence'), default=0) + 1

#                 product = self.env['product.product'].search(
#                     [('default_code', '=', 'PRIORITY_SERVICE')], limit=1)
#                 if not product:
#                     product = self.env['product.product'].create({
#                         'name': 'Priority Express Service',
#                         'default_code': 'PRIORITY_SERVICE',
#                         'type': 'service',
#                         'list_price': wizard.price,
#                         'sale_ok': True,
#                         'purchase_ok': False,
#                     })

#                 self.env['sale.order.line'].create({
#                     'order_id': order.id,
#                     'product_id': product.id,
#                     'product_uom_qty': wizard.quantity,
#                     'product_uom': False,
#                     'price_unit': wizard.price,
#                     'sequence': new_sequence,
#                     'is_priority_line': True,
#                     'lx_width_m': False,
#                     'lx_height_m': False,
#                     'size': False,
#                 })

#                 order._compute_delivery_date()
#                 order.invalidate_recordset()

#             order._generate_sequence_numbers_for_lines()

#         return {'type': 'ir.actions.act_window_close'}
