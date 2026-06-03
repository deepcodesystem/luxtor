from odoo import fields, models


class ProductProduct(models.Model):
    _inherit = "product.product"

    fabric_color = fields.Char(string="Fabric Color")
