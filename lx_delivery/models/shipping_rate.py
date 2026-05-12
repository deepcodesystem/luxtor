# -*- coding: utf-8 -*-
from odoo import fields, models


class ShippingRate(models.Model):
    """Table Ville/ZIP → tarif standard + flag intracity."""

    _name = "shipping.rate"
    _description = "City Shipping Rate"
    _order = "name"

    name = fields.Char(string="City/Suburb", required=True)
    province = fields.Char(string="Province")
    zip_code = fields.Char(string="Zip Code", index=True)
    delivery_eta = fields.Char(string="Delivery ETA", help="Ex: '24h - 48h'")
    price = fields.Float(string="Price", default=0.0)
    is_intracity = fields.Boolean(
        string="Intracity",
        default=False,
        help="Facturer cette destination avec les tranches de poids Intracity.",
    )

    _sql_constraints = [
        ("name_unique", "unique(name)", "Each city/suburb must be unique."),
    ]

