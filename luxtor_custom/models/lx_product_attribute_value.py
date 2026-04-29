# -*- coding: utf-8 -*-

from odoo import fields, models


class ProductAttributeValue(models.Model):
    _inherit = "product.template.attribute.value"


    lx_motor_label = fields.Char(
        string="Motor Control Name",
        help="Friendly label shown in the product configurator dialog for "
             "Motor Only control type. Leave empty to use the Code value. "
             "Example: 'Remote Motor' or 'Smart Motor'.",
    )