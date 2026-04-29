# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    # store as integer percentages (0..100)
    lx_browser_factor_pct = fields.Integer(
        string="Browser Markup",
        config_parameter="luxtor.lx_browser_factor_pct",
        default=0,
    )
    lx_quantity_cap_pct = fields.Integer(
        string="Quantity Cap",
        config_parameter="luxtor.lx_quantity_cap_pct",
        default=95,
    )
    lx_new_customer_pct = fields.Integer(
        string="New Customer",
        config_parameter="luxtor.lx_new_customer_pct",
        default=5,
    )
    lx_welcome_reward_pct = fields.Integer(
        string="Welcome Reward",
        config_parameter="luxtor.lx_welcome_reward_pct",
        default=5,
    )
    lx_refer_earn_pct = fields.Integer(
        string="Refer & Earn",
        config_parameter="luxtor.lx_refer_earn_pct",
        default=5,
    )
    lx_order_limit_amount = fields.Float(
        string="Order Limit",
        config_parameter="luxtor.lx_order_limit_amount",
        digits="Product Price",
    )

    lx_free_amount_order = fields.Float(
        string="Free Amount Order (Delivery & Installation)",
        config_parameter="luxtor.lx_free_amount_order",
        digits="Product Price",
        default=5000,
        help="Minimum total order amount to offer free delivery and installation."
    )

    lx_currency_id = fields.Many2one(
        'res.currency',
        string="Currency",
        related='company_id.currency_id',
        readonly=True
    )

    # handy getters for business logic (return float factors 0..1)
    def get_lx_browser_factor(self):
        icp = self.env['ir.config_parameter'].sudo()
        v = int(icp.get_param('luxtor.lx_browser_factor_pct', default='0') or 0)
        return v / 100.0

    def get_lx_quantity_cap_factor(self):
        icp = self.env['ir.config_parameter'].sudo()
        v = int(icp.get_param('luxtor.lx_quantity_cap_pct', default='95') or 95)
        return v / 100.0

    def get_lx_new_customer_factor(self):
        icp = self.env['ir.config_parameter'].sudo()
        v = int(icp.get_param('luxtor.lx_new_customer_pct', default='5') or 5)
        return v / 100.0

    def get_lx_welcome_reward_factor(self):
        icp = self.env['ir.config_parameter'].sudo()
        v = int(icp.get_param('luxtor.lx_welcome_reward_pct', default='5') or 5)
        return v / 100.0

    def get_lx_refer_earn_factor(self):
        icp = self.env['ir.config_parameter'].sudo()
        v = int(icp.get_param('luxtor.lx_refer_earn_pct', default='5') or 5)
        return v / 100.0

    def get_lx_order_limit_amount(self):
        icp = self.env['ir.config_parameter'].sudo()
        return float(icp.get_param('luxtor.lx_order_limit_amount', default='0') or 0.0)
    
    def get_lx_free_amount_order(self):
        icp = self.env['ir.config_parameter'].sudo()
        return float(icp.get_param('luxtor.lx_free_amount_order', default='0') or 0.0)

# class ResConfigSettings(models.TransientModel):
#     _inherit = "res.config.settings"

#     # store as integer percentages (0..100)
#     lx_browser_factor_pct = fields.Integer(
#         string="Browser Markup",
#         config_parameter="luxtor.lx_browser_factor_pct",
#         default=0,
#     )
#     lx_quantity_cap_pct = fields.Integer(
#         string="Quantity Cap",
#         config_parameter="luxtor.lx_quantity_cap_pct",
#         default=95,
#     )
#     lx_new_customer_pct = fields.Integer(
#         string="New Customer",
#         config_parameter="luxtor.lx_new_customer_pct",
#         default=5,
#     )
#     lx_order_limit_amount = fields.Float(
#         string="Order Limit",
#         config_parameter="luxtor.lx_order_limit_amount",
#         digits="Product Price",
#     )

#     lx_free_amount_order = fields.Float(
#         string="Free Amount Order (Delivery & Installation)",
#         config_parameter="luxtor.lx_free_amount_order",
#         digits="Product Price",
#         default=5000,
#         help="Minimum total order amount to offer free delivery and installation."
#     )

#     lx_currency_id = fields.Many2one(
#         'res.currency',
#         string="Currency",
#         related='company_id.currency_id',
#         readonly=True
#     )

    
#     # handy getters for business logic (return float factors 0..1)
#     def get_lx_browser_factor(self):
#         icp = self.env['ir.config_parameter'].sudo()
#         v = int(icp.get_param('luxtor.lx_browser_factor_pct', default='0') or 0)
#         return v / 100.0

#     def get_lx_quantity_cap_factor(self):
#         icp = self.env['ir.config_parameter'].sudo()
#         v = int(icp.get_param('luxtor.lx_quantity_cap_pct', default='95') or 95)
#         return v / 100.0

#     def get_lx_new_customer_factor(self):
#         icp = self.env['ir.config_parameter'].sudo()
#         v = int(icp.get_param('luxtor.lx_new_customer_pct', default='5') or 5)
#         return v / 100.0

#     def get_lx_order_limit_amount(self):
#         icp = self.env['ir.config_parameter'].sudo()
#         return float(icp.get_param('luxtor.lx_order_limit_amount', default='0') or 0.0)
    
#     def get_lx_free_amount_order(self):
#         icp = self.env['ir.config_parameter'].sudo()
#         return float(icp.get_param('luxtor.lx_free_amount_order', default='0') or 0.0)
