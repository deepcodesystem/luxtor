# -*- coding: utf-8 -*-
from odoo import api, fields, models

class ShippingRate(models.Model):
    _name = 'shipping.rate'
    _description = 'City Shipping Rate'

    name = fields.Char(string='City/Suburb', required=True)
    province = fields.Char(string='Province')
    zip_code = fields.Char(string='Zip Code')
    delivery_eta = fields.Char(string='Range Date', help="Example: '24h - 48h'")
    price = fields.Float(string='Price', default=0.0)
    is_intracity = fields.Boolean(
        string='Intracity',
        help='Bill this destination with the Intracity weight brackets.'
    )

    _sql_constraints = [
        ('name_unique', 'unique(name)', 'Each city/suburb must be unique.'),
    ]
