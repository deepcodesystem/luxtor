# -*- coding: utf-8 -*-
from odoo import fields, models


class ProductOpennessFactor(models.Model):
    _name = 'product.openness.factor'
    _description = 'Openness Factor'
    _order = 'name'

    name = fields.Char(string="Label", required=True, index=True)
    active = fields.Boolean(default=True)


class ProductColorFastness(models.Model):
    _name = 'product.color.fastness'
    _description = 'Color Fastness'
    _order = 'name'

    name = fields.Char(string="Grade", required=True, index=True)
    active = fields.Boolean(default=True)


class ProductComposition(models.Model):
    _name = 'product.composition'
    _description = 'Product Composition'
    _order = 'name'

    name = fields.Char(string="Label", required=True, index=True)
    note = fields.Text(string="Notes")
    active = fields.Boolean(default=True)

