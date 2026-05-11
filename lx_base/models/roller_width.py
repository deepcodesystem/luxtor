# -*- coding: utf-8 -*-
from odoo import fields, models


class RollerWidth(models.Model):
    _name = 'roller.width'
    _description = 'Roller Width Tag'
    _order = 'value_cm'

    name = fields.Char(string="Label", required=True)
    value_cm = fields.Float(string="Width (cm)", required=True, digits=(16, 2))
    active = fields.Boolean(default=True)

