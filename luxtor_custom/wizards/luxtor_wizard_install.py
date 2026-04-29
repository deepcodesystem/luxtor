# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SaleOrderInstallationWizard(models.TransientModel):
    _name = 'sale.order.installation.wizard'
    _description = 'Installation Service Wizard'

    order_id = fields.Many2one('sale.order', string='Order', required=True, readonly=True)
    installation = fields.Selection(
        [('paid', 'Paid'), ('free', 'Free')],
        string='Installation Option',
        required=True,
        default='paid',
    )
    quantity = fields.Integer(string='Quantity', default=0)
    price = fields.Float(string='Price')  # editable for paid

    # ──────────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────────
    def _get_install_product(self, option):
        """Return product.product (single variant) by XML ID for 'paid' or 'free'."""
        xmlid = (
            'luxtor_custom.product_install_paid_tmpl'
            if option == 'paid'
            else 'luxtor_custom.product_install_free_tmpl'
        )
        tmpl = self.env.ref(xmlid)
        return tmpl.product_variant_id

    
    # ──────────────────────────────────────────────────────────────────────────────
    # Defaults & onchange
    # ──────────────────────────────────────────────────────────────────────────────
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id:
            order = self.env['sale.order'].browse(active_id)
            res['order_id'] = order.id
            # keep your persisted choice if present
            res.setdefault('installation', order.installation_type or 'paid')

            # quantity equals blinds count for both options (so free will create a line)
            qty = order._get_mrp_blinds_quantity()
            is_paid = res['installation'] == 'paid'
            prod = self._get_install_product('paid' if is_paid else 'free')

            res['quantity'] = qty
            res['price'] = (prod.list_price if is_paid else 0.0)
        return res

    @api.onchange('installation')
    def _onchange_installation(self):
        for wizard in self:
            order = wizard.order_id
            if not order:
                continue
            qty = order._get_mrp_blinds_quantity()
            is_paid = wizard.installation == 'paid'
            prod = wizard._get_install_product('paid' if is_paid else 'free')

            wizard.quantity = qty
            wizard.price = (prod.list_price if is_paid else 0.0)

    # ──────────────────────────────────────────────────────────────────────────────
    # Constraints (keep your original rule: only enforce on paid)
    # ──────────────────────────────────────────────────────────────────────────────
    @api.constrains('quantity')
    def _check_quantity(self):
        for wizard in self:
            if wizard.installation == 'paid':
                max_qty = wizard.order_id._get_mrp_blinds_quantity()
                if wizard.quantity > max_qty or wizard.quantity <= 0:
                    raise ValidationError(_(
                        'You cannot specify an installation quantity greater '
                        'than the number of roller blinds in the order.\n'
                        'Maximum allowed: %d'
                    ) % max_qty)

    # ──────────────────────────────────────────────────────────────────────────────
    # Apply (always create a SOL; paid or free)
    # ──────────────────────────────────────────────────────────────────────────────
    def action_confirm(self):
        for wizard in self:
            order = wizard.order_id
            if not order:
                continue

            # remove previous installation lines (keep your logic)
            order.order_line.filtered(lambda l: getattr(l, 'is_installation_line', False)).unlink()

            # persist summary fields on order (keep your logic)
            order.write({
                'installation_type': wizard.installation,
                'installation_quantity': wizard.quantity,
                'installation_price': wizard.price,
            })

            # if paid, re-check bounds (keep your logic)
            if wizard.installation == 'paid':
                max_qty = order._get_mrp_blinds_quantity()
                if wizard.quantity <= 0 or wizard.quantity > max_qty:
                    raise UserError(_('Please enter a quantity between 1 and %d for installation.') % max_qty)

            # compute insertion sequence (keep your logic)
            goods_lines = order.order_line.filtered(
                lambda l: l.product_template_id
                          and l.product_template_id.type in ['consu', 'combo']
                          and not getattr(l, 'is_priority_line', False)
                          and not getattr(l, 'is_installation_line', False)
            )
            priority_lines = order.order_line.filtered(lambda l: getattr(l, 'is_priority_line', False))
            new_sequence = max(
                max(goods_lines.mapped('sequence'), default=0),
                max(priority_lines.mapped('sequence'), default=0),
            ) + 1

            # product by XML ID, name, uom, tax mapping (fixes "accountable line" error)
            prod = wizard._get_install_product(wizard.installation)

            self.env['sale.order.line'].create({
                'order_id': order.id,
                'product_id': prod.id,
                'name': prod.get_product_multiline_description_sale(),
                'product_uom_qty': wizard.quantity,
                'product_uom': prod.uom_id.id,     # REQUIRED
                'price_unit': wizard.price,        # 0.0 if free
                'sequence': new_sequence,
                'is_installation_line': True,
                # keep your custom fields; set to False explicitly if you want
                'lx_width_m': False,
                'lx_height_m': False,
                'size': False,
            })

            # keep your custom sequencing if present
            if hasattr(order, '_generate_sequence_numbers_for_lines'):
                order._generate_sequence_numbers_for_lines()

        return {'type': 'ir.actions.act_window_close'}



# # -*- coding: utf-8 -*-
# from odoo import api, fields, models, _
# from odoo.exceptions import UserError, ValidationError


# class SaleOrderInstallationWizard(models.TransientModel):
#     _name = 'sale.order.installation.wizard'
#     _description = 'Installation Service Wizard'

#     order_id = fields.Many2one('sale.order', string='Order',
#                                required=True, readonly=True)
#     installation = fields.Selection([
#         ('paid', 'Paid'),
#         ('free', 'Free'),
#     ], string='Installation Option', required=True, default='paid')
#     quantity = fields.Integer(string='Quantity', default=0)
#     price = fields.Float(string='Price')

#     @api.model
#     def default_get(self, fields_list):
#         res = super().default_get(fields_list)
#         active_id = self.env.context.get('active_id')
#         if active_id:
#             order = self.env['sale.order'].browse(active_id)
#             res['order_id'] = order.id
#             res.setdefault('installation', order.installation_type or 'paid')
#             res['quantity'] = order._get_mrp_blinds_quantity()

#             product = self.env['product.product'].search(
#                 [('default_code', '=', 'INSTALL_SERVICE')], limit=1)
#             price_from_product = product.list_price if product else 0.0
#             res['price'] = price_from_product
#         return res

#     @api.onchange('installation')
#     def _onchange_installation(self):
#         for wizard in self:
#             product = self.env['product.product'].search(
#                 [('default_code', '=', 'INSTALL_SERVICE')], limit=1)
#             price_from_product = product.list_price if product else 0.0

#             if wizard.installation == 'free':
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
#             if wizard.installation == 'paid':
#                 max_qty = wizard.order_id._get_mrp_blinds_quantity()
#                 if wizard.quantity > max_qty or wizard.quantity <= 0:
#                     raise ValidationError(_(
#                         'You cannot specify an installation quantity greater '
#                         'than the number of roller blinds in the order.\n'
#                         'Maximum allowed: %d' % max_qty
#                     ))

#     def action_confirm(self):
#         for wizard in self:
#             order = wizard.order_id
#             if not order:
#                 continue

#             order.order_line.filtered(lambda l: l.is_installation_line).unlink()

#             if wizard.installation == 'free':
#                 order.write({
#                     'installation_type': 'free',
#                     'installation_quantity': 0,
#                     'installation_price': 0.0,
#                 })
#             else:
#                 max_qty = order._get_mrp_blinds_quantity()
#                 if wizard.quantity <= 0 or wizard.quantity > max_qty:
#                     raise UserError(_('Please enter a quantity between 1 and %d for installation.') % max_qty)

#                 order.write({
#                     'installation_type': 'paid',
#                     'installation_quantity': wizard.quantity,
#                     'installation_price': wizard.price,
#                 })

#                 goods_lines = order.order_line.filtered(
#                     lambda l: l.product_template_id and
#                               l.product_template_id.type in ['consu', 'combo'] and
#                               not l.is_priority_line and not l.is_installation_line)
#                 priority_lines = order.order_line.filtered(lambda l: l.is_priority_line)

#                 new_sequence = max(
#                     max(goods_lines.mapped('sequence'), default=0),
#                     max(priority_lines.mapped('sequence'), default=0)
#                 ) + 1

#                 product = self.env['product.product'].search(
#                     [('default_code', '=', 'INSTALL_SERVICE')], limit=1)
#                 if not product:
#                     product = self.env['product.product'].create({
#                         'name': 'Installation Service',
#                         'default_code': 'INSTALL_SERVICE',
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
#                     'is_installation_line': True,
#                     'lx_width_m': False,
#                     'lx_height_m': False,
#                     'size': False,
#                 })
                

#             order._generate_sequence_numbers_for_lines()

#         return {'type': 'ir.actions.act_window_close'}
