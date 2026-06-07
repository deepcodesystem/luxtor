# -*- coding: utf-8 -*-
from odoo import api, fields, models


class ProductAttributeComponent(models.Model):
    _name = 'product.attribute.component'
    _description = "Component (variant) linked to Attribute Value"
    _order = 'sequence, id'

    # ── Lien vers la valeur d'attribut ──────────────────────────────────────
    ptav_id = fields.Many2one(
        'product.template.attribute.value',
        string='Attribute Value',
        required=True,
        ondelete='cascade',
        index=True,
    )

    # ── Lien vers la VARIANTE du composant (product.product) ───────────────
    component_variant_id = fields.Many2one(
        'product.product',
        string='Component Variant',
        required=True,
        domain="[('product_tmpl_id.lx_is_component', '=', True)]",
        ondelete='restrict',
    )

    # ── Quantité utilisée ───────────────────────────────────────────────────
    quantity = fields.Float(
        string='Quantity',
        default=1.0,
        digits='Product Unit of Measure',
    )

    sequence = fields.Integer(string='Sequence', default=10)

    # ── Champs calculés pour le prix ────────────────────────────────────────
    component_standard_price = fields.Float(
        string='Unit Cost',
        related='component_variant_id.standard_price',
        store=True,
        readonly=True,
        help="Standard price of the component variant. Stored to trigger auto-update.",
    )

    lx_adjusted_cost = fields.Float(
        string='Adjusted Cost',
        related='component_variant_id.lx_adjusted_cost',
        store=True,
        readonly=True,
        help="Coût ajusté (standard_price × (1 + waste/100 + margin/100)) du composant.",
    )

    amount_with_margins = fields.Float(
        string='Amount with Margins',
        compute='_compute_amount_with_margins',
        store=True,
        help="lx_adjusted_cost × Quantity — coût total avec marges intégrées.",
    )

    # =========================================================================
    # COMPUTES
    # =========================================================================

    @api.depends('lx_adjusted_cost', 'quantity')
    def _compute_amount_with_margins(self):
        for rec in self:
            rec.amount_with_margins = (rec.lx_adjusted_cost or 0.0) * (rec.quantity or 0.0)

