# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class DeliveryBracket(models.Model):
    _name = "delivery.bracket.lx"
    _description = "Weight pricing bracket (intracity/intercity)"
    _order = "carrier_id, kind, min_kg, max_kg"

    KIND_SELECTION = [
        ("intra", "Intracity"),
        ("inter", "Intercity"),
    ]

    carrier_id = fields.Many2one(
        "delivery.carrier",
        string="Carrier",
        required=False,
        ondelete="cascade",
        index=True,
    )
    kind = fields.Selection(KIND_SELECTION, required=True, index=True)

    min_kg = fields.Float(string="Min (Kg)", required=True, index=True)
    max_kg = fields.Float(string="Max (Kg)", required=True, index=True)
    unit_price = fields.Float(string="Unit Price", required=True)

   
    @api.constrains("min_kg", "max_kg")
    def _check_range(self):
        for rec in self:
            if rec.min_kg < 0 or rec.max_kg <= 0 or rec.max_kg <= rec.min_kg:
                raise ValidationError(_("Invalid bracket range."))
