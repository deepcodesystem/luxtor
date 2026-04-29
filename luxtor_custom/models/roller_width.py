# -*- coding: utf-8 -*-
import re
from odoo import api, fields, models


class RollerWidth(models.Model):
    _name = 'roller.width'
    _description = 'Roller Width Tag'
    _order = 'sequence, name'

    name = fields.Char(string='Tag', required=True, index=True,
                       help="Free text tag, e.g. '200', '2.5 m', '250cm'.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    value_cm = fields.Float(
        string='Value (cm)',
        compute='_compute_value_cm',
        store=True,
        help='Numeric value parsed from the tag, normalized to centimeters.'
    )

    @api.depends('name')
    def _compute_value_cm(self):
        num_re = re.compile(r'([0-9]+(?:[.,][0-9]+)?)')
        for rec in self:
            s = (rec.name or '').strip().lower()
            m = num_re.search(s)
            val = 0.0
            if m:
                try:
                    num = float(m.group(1).replace(',', '.'))
                    if 'cm' in s:
                        val = num
                    elif 'm' in s:
                        val = num * 100.0
                    else:
                        val = num
                except Exception:
                    val = 0.0
            rec.value_cm = val
