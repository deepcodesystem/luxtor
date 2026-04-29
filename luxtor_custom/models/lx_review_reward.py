# -*- coding: utf-8 -*-
from odoo import api, fields, models

class LxReviewReward(models.Model):
    _name = "lx.review.reward"
    _description = "Luxtor review reward (free express one-time)"
    _order = "create_date desc"

    partner_id = fields.Many2one("res.partner", required=True, index=True, ondelete="cascade")
    website_id = fields.Many2one("website", index=True)
    order_id = fields.Many2one("sale.order", index=True)
    product_id = fields.Many2one("product.product", index=True)
    rating = fields.Integer()
    message = fields.Text()

    state = fields.Selection([
        ("available", "Available"),
        ("used", "Used"),
        ("cancelled", "Cancelled"),
    ], default="available", required=True, index=True)

    used_date = fields.Datetime()
